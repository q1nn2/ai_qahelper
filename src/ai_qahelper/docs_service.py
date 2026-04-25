from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from ai_qahelper.config import load_config
from ai_qahelper.deduplication import deduplicate_test_cases
from ai_qahelper.documentation_quality import (
    apply_quality_marks_to_checklist,
    apply_quality_marks_to_test_cases,
    evaluate_checklist_items,
    evaluate_test_cases,
)
from ai_qahelper.llm_client import LlmClient
from ai_qahelper.logging_utils import configure_logging
from ai_qahelper.models import BugReport, SessionState, TestAnalysisReport, TestCase, UnifiedRequirementModel
from ai_qahelper.quality import check_consistency
from ai_qahelper.reporting import export_bug_reports_local, export_checklist_local, export_test_cases_local, save_json
from ai_qahelper.session_service import load_session, retry_attempts, save_session, session_path
from ai_qahelper.testdocs import (
    fallback_checklist,
    fallback_test_analysis,
    fallback_test_cases,
    generate_bug_report_templates,
    generate_checklist,
    generate_test_analysis,
    generate_test_cases,
)

logger = logging.getLogger(__name__)

ArtifactType = Literal["testcases", "checklist"]
GenerationFocus = Literal[
    "smoke",
    "regression",
    "negative",
    "api",
    "ui",
    "mobile",
    "security",
    "performance",
    "accessibility",
    "general",
]


def _focused_name(base_name: str, focus: str) -> str:
    if focus == "general":
        return base_name
    stem, suffix = base_name.rsplit(".", 1)
    return f"{stem}-{focus}.{suffix}"


def _focused_prefix(base_prefix: str, focus: str) -> str:
    return base_prefix if focus == "general" else f"{base_prefix}-{focus}"


def generate_docs(
    session_id: str,
    max_cases: int | None = None,
    generate_bug_templates: bool | None = None,
    skip_test_analysis: bool | None = None,
    artifact_type: ArtifactType = "testcases",
    focus: GenerationFocus = "general",
) -> SessionState:
    cfg = load_config()
    do_bugs = cfg.generate_bug_templates if generate_bug_templates is None else generate_bug_templates
    state = load_session(session_id)
    sdir = session_path(session_id)
    configure_logging(sdir)
    unified = UnifiedRequirementModel.model_validate_json(Path(state.unified_model_path).read_text(encoding="utf-8"))
    llm = LlmClient(cfg.llm)
    consistency = check_consistency(unified)
    consistency_json = sdir / "consistency-report.json"
    save_json(consistency_json, consistency)

    n_items = max_cases if max_cases is not None else cfg.llm.max_test_cases
    max_default = 100 if artifact_type == "testcases" else 200
    n_items = max(1, min(n_items, max_default))

    err_path = sdir / "llm-generation-errors.log"
    run_analysis = cfg.generate_test_analysis and skip_test_analysis is not True
    analysis: TestAnalysisReport | None = None
    analysis_json = sdir / "test-analysis.json"
    if run_analysis:
        try:
            analysis = retry_attempts(
                2,
                lambda: generate_test_analysis(llm, unified, consistency, llm_cfg=cfg.llm),
            )
        except Exception as exc:
            logger.exception("generate_test_analysis failed, using fallback")
            with err_path.open("a", encoding="utf-8") as f:
                f.write(f"generate_test_analysis:\n{type(exc).__name__}: {exc}\n")
            analysis = fallback_test_analysis(unified, consistency)
        save_json(analysis_json, analysis.model_dump(mode="json"))
        state.test_analysis_path = str(analysis_json)

    bug_templates: list[BugReport] = []
    if artifact_type == "checklist":
        try:
            checklist = retry_attempts(
                2,
                lambda: generate_checklist(
                    llm,
                    unified,
                    consistency_report=consistency,
                    llm_cfg=cfg.llm,
                    analysis=analysis if run_analysis and analysis is not None else fallback_test_analysis(unified, consistency),
                    max_items=n_items,
                    focus=focus,
                ),
            )
        except Exception as exc:
            logger.exception("generate_checklist failed, using fallback")
            with err_path.open("a", encoding="utf-8") as f:
                f.write(f"\ngenerate_checklist:\n{type(exc).__name__}: {exc}\n")
            checklist = fallback_checklist(unified, max_items=n_items)
        quality_report = evaluate_checklist_items(checklist)
        checklist = apply_quality_marks_to_checklist(checklist, quality_report)
        checklist_json = sdir / _focused_name("checklist.json", focus)
        quality_json = sdir / _focused_name("checklist-quality-report.json", focus)
        save_json(checklist_json, [c.model_dump() for c in checklist])
        save_json(quality_json, quality_report)
        export_checklist_local(sdir, checklist, filename_prefix=_focused_prefix("checklist", focus))
        state.checklist_path = str(checklist_json)
        state.quality_report_path = str(quality_json)
        state.test_cases_path = None
        state.dedup_report_path = None
        state.bug_reports_path = None
    else:
        try:
            test_cases = retry_attempts(
                2,
                lambda: generate_test_cases(
                    llm,
                    unified,
                    consistency_report=consistency,
                    max_cases=n_items,
                    llm_cfg=cfg.llm,
                    export_columns=cfg.test_cases_export,
                    analysis=analysis if run_analysis else None,
                    focus=focus,
                ),
            )
        except Exception as exc:
            logger.exception("generate_test_cases failed, using fallback")
            with err_path.open("a", encoding="utf-8") as f:
                f.write(f"\ngenerate_test_cases:\n{type(exc).__name__}: {exc}\n")
            test_cases = fallback_test_cases(unified, max_cases=n_items)
        test_cases, dedup_report = deduplicate_test_cases(test_cases)
        dedup_json = sdir / _focused_name("dedup-report.json", focus)
        save_json(dedup_json, dedup_report)
        quality_report = evaluate_test_cases(test_cases)
        test_cases = apply_quality_marks_to_test_cases(test_cases, quality_report)
        if do_bugs:
            try:
                bug_templates = retry_attempts(2, lambda: generate_bug_report_templates(llm, test_cases))
            except Exception as exc:
                logger.exception("generate_bug_report_templates failed, skipping bug drafts")
                with err_path.open("a", encoding="utf-8") as f:
                    f.write(f"\ngenerate_bug_report_templates:\n{type(exc).__name__}: {exc}\n")
                bug_templates = []

        test_cases_json = sdir / _focused_name("test-cases.json", focus)
        quality_json = sdir / _focused_name("test-cases-quality-report.json", focus)
        bugs_json = sdir / _focused_name("bug-reports.json", focus)
        save_json(test_cases_json, [t.model_dump() for t in test_cases])
        save_json(quality_json, quality_report)
        save_json(bugs_json, [b.model_dump() for b in bug_templates])
        export_test_cases_local(sdir, test_cases, cfg.test_cases_export, filename_prefix=_focused_prefix("test-cases", focus))
        export_bug_reports_local(sdir, bug_templates, filename_prefix=_focused_prefix("bug-reports", focus))

        state.test_cases_path = str(test_cases_json)
        state.dedup_report_path = str(dedup_json)
        state.quality_report_path = str(quality_json)
        state.bug_reports_path = str(bugs_json)
        state.checklist_path = None

    state.consistency_report_path = str(consistency_json)
    if not run_analysis:
        state.test_analysis_path = None
    save_session(state)
    return state


def generate_bug_templates_for_session(session_id: str, max_items: int = 20) -> SessionState:
    cfg = load_config()
    state = load_session(session_id)
    if not state.test_cases_path:
        state = generate_docs(session_id, generate_bug_templates=True, skip_test_analysis=True)
        if not state.test_cases_path:
            raise RuntimeError("No test cases found for bug template generation")
    sdir = session_path(session_id)
    configure_logging(sdir)
    llm = LlmClient(cfg.llm)
    test_cases = [
        item
        for item in json.loads(Path(state.test_cases_path).read_text(encoding="utf-8"))
    ]
    parsed_cases = [TestCase.model_validate(item) for item in test_cases]
    try:
        bug_templates = retry_attempts(2, lambda: generate_bug_report_templates(llm, parsed_cases, max_items=max_items))
    except Exception as exc:
        logger.exception("generate_bug_report_templates failed")
        err_path = sdir / "llm-generation-errors.log"
        with err_path.open("a", encoding="utf-8") as f:
            f.write(f"\ngenerate_bug_templates_for_session:\n{type(exc).__name__}: {exc}\n")
        bug_templates = []
    bugs_json = sdir / "bug-reports.json"
    save_json(bugs_json, [b.model_dump() for b in bug_templates])
    export_bug_reports_local(sdir, bug_templates)
    state.bug_reports_path = str(bugs_json)
    save_session(state)
    return state
