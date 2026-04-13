"""Тонкий фасад: команды CLI импортируют из ai_qahelper.orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

from ai_qahelper.autotest_service import (
    create_bug_drafts_from_failures,
    generate_autotests,
    run_autotests,
    run_manual,
)
from ai_qahelper.docs_service import generate_docs
from ai_qahelper.reporting import save_json
from ai_qahelper.session_service import ingest
from ai_qahelper.sync_service import sync_reports

__all__ = [
    "agent_run",
    "create_bug_drafts_from_failures",
    "generate_autotests",
    "generate_docs",
    "ingest",
    "run_autotests",
    "run_manual",
    "sync_reports",
]


def agent_run(
    requirements: list[str],
    requirement_urls: list[str],
    figma_file_key: str | None = None,
    target_url: str | None = None,
    out_dir: str | None = None,
    max_cases: int | None = None,
    *,
    with_bug_drafts: bool = False,
    skip_test_analysis: bool | None = None,
    session_label: str | None = None,
) -> dict:
    target = target_url or "https://example.com"
    session_id = ingest(
        requirements,
        requirement_urls,
        figma_file_key,
        target,
        session_label=session_label,
    )
    bug_templates_arg: bool | None = True if with_bug_drafts else None
    state = generate_docs(
        session_id,
        max_cases=max_cases,
        generate_bug_templates=bug_templates_arg,
        skip_test_analysis=skip_test_analysis,
    )
    consistency = (
        json.loads(Path(state.consistency_report_path).read_text(encoding="utf-8"))
        if state.consistency_report_path
        else {"summary": {"missing": 0, "contradiction": 0, "ambiguity": 0}}
    )
    result = {
        "session_id": session_id,
        "unified_model_path": state.unified_model_path,
        "consistency_report_path": state.consistency_report_path,
        "test_analysis_path": state.test_analysis_path,
        "test_cases_path": state.test_cases_path,
        "bug_reports_path": state.bug_reports_path,
        "summary": {
            "missing": consistency["summary"]["missing"],
            "contradiction": consistency["summary"]["contradiction"],
            "ambiguity": consistency["summary"]["ambiguity"],
            "test_cases": len(json.loads(Path(state.test_cases_path).read_text(encoding="utf-8"))),
        },
    }
    if out_dir:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        save_json(out / f"{session_id}-agent-summary.json", result)
    return result
