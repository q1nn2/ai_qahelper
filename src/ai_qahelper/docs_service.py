from __future__ import annotations

import logging
from pathlib import Path

from ai_qahelper.config import load_config
from ai_qahelper.llm_client import LlmClient
from ai_qahelper.logging_utils import configure_logging
from ai_qahelper.models import BugReport, SessionState, TestAnalysisReport, UnifiedRequirementModel
from ai_qahelper.quality import check_consistency
from ai_qahelper.reporting import export_bug_reports_local, export_test_cases_local, save_json
from ai_qahelper.session_service import load_session, retry_attempts, save_session, session_path
from ai_qahelper.testdocs import (
    fallback_test_analysis,
    fallback_test_cases,
    generate_bug_report_templates,
    generate_test_analysis,
    generate_test_cases,
)

logger = logging.getLogger(__name__)


def generate_docs(
    session_id: str,
    max_cases: int | None = None,
    generate_bug_templates: bool | None = None,
    skip_test_analysis: bool | None = None,
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

    n_cases = max_cases if max_cases is not None else cfg.llm.max_test_cases
    n_cases = max(1, min(n_cases, 100))

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

    try:
        test_cases = retry_attempts(
            2,
            lambda: generate_test_cases(
                llm,
                unified,
                consistency_report=consistency,
                max_cases=n_cases,
                llm_cfg=cfg.llm,
                export_columns=cfg.test_cases_export,
                analysis=analysis if run_analysis else None,
            ),
        )
    except Exception as exc:
        logger.exception("generate_test_cases failed, using fallback")
        with err_path.open("a", encoding="utf-8") as f:
            f.write(f"\ngenerate_test_cases:\n{type(exc).__name__}: {exc}\n")
        test_cases = fallback_test_cases(unified, max_cases=n_cases)
    bug_templates: list[BugReport] = []
    if do_bugs:
        try:
            bug_templates = retry_attempts(2, lambda: generate_bug_report_templates(llm, test_cases))
        except Exception as exc:
            logger.exception("generate_bug_report_templates failed, skipping bug drafts")
            with err_path.open("a", encoding="utf-8") as f:
                f.write(f"\ngenerate_bug_report_templates:\n{type(exc).__name__}: {exc}\n")
            bug_templates = []

    test_cases_json = sdir / "test-cases.json"
    bugs_json = sdir / "bug-reports.json"
    save_json(test_cases_json, [t.model_dump() for t in test_cases])
    save_json(bugs_json, [b.model_dump() for b in bug_templates])
    export_test_cases_local(sdir, test_cases, cfg.test_cases_export)
    export_bug_reports_local(sdir, bug_templates)

    state.test_cases_path = str(test_cases_json)
    state.bug_reports_path = str(bugs_json)
    state.consistency_report_path = str(consistency_json)
    if not run_analysis:
        state.test_analysis_path = None
    save_session(state)
    return state
