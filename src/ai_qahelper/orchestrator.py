from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from ai_qahelper.config import load_config
from ai_qahelper.execution import (
    generate_playwright_pytest_tests,
    run_manual_cases,
    run_pytest_suite,
    synthesize_auto_results,
)
from ai_qahelper.inputs import ingest_figma, parse_requirement_url, parse_requirements
from ai_qahelper.llm_client import LlmClient
from ai_qahelper.logging_utils import configure_logging
from ai_qahelper.models import BugReport, SessionState, TestCase, UnifiedRequirementModel
from ai_qahelper.quality import check_consistency, check_pass_rate, check_requirement_coverage
from ai_qahelper.reporting import (
    export_bug_reports_local,
    export_manual_results_local,
    export_test_cases_local,
    save_json,
    sync_bug_reports_to_sheet,
    sync_test_cases_to_sheet,
)
from ai_qahelper.testdocs import fallback_test_cases, generate_bug_report_templates, generate_test_cases


def _session_root() -> Path:
    cfg = load_config()
    return Path(cfg.sessions_dir)


def _session_path(session_id: str) -> Path:
    return _session_root() / session_id


def _session_file(session_id: str) -> Path:
    return _session_path(session_id) / "session.json"


def _load_session(session_id: str) -> SessionState:
    return SessionState.model_validate_json(_session_file(session_id).read_text(encoding="utf-8"))


def _save_session(state: SessionState) -> None:
    path = _session_file(state.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def _retry(attempts: int, fn):
    last_error = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if i < attempts - 1:
                time.sleep(1 + i)
    raise RuntimeError(f"Operation failed after {attempts} attempts: {last_error}") from last_error


def ingest(requirements: list[str], requirement_urls: list[str], figma_file_key: str | None, target_url: str) -> str:
    session_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    session_dir = _session_path(session_id)
    configure_logging(session_dir)

    allowed = [urlparse(e.base_url.unicode_string()).netloc for e in load_config().envs]
    target_netloc = urlparse(target_url).netloc
    if allowed and target_netloc not in allowed:
        raise RuntimeError(f"Target URL '{target_url}' is not in allowed environments: {allowed}")

    req_items = parse_requirements(requirements) if requirements else []
    req_items.extend(parse_requirement_url(url) for url in requirement_urls)

    design = _retry(2, lambda: ingest_figma(figma_file_key)) if figma_file_key else None
    unified = UnifiedRequirementModel(requirements=req_items, design=design, target_url=target_url)

    unified_path = session_dir / "unified-model.json"
    save_json(unified_path, unified.model_dump(mode="json"))
    state = SessionState(
        session_id=session_id,
        created_at=datetime.now(UTC),
        target_url=target_url,
        requirements_files=requirements + requirement_urls,
        figma_file_key=figma_file_key,
        unified_model_path=str(unified_path),
    )
    _save_session(state)
    return session_id


def generate_docs(session_id: str) -> SessionState:
    cfg = load_config()
    state = _load_session(session_id)
    session_dir = _session_path(session_id)
    configure_logging(session_dir)
    unified = UnifiedRequirementModel.model_validate_json(Path(state.unified_model_path).read_text(encoding="utf-8"))
    llm = LlmClient(cfg.llm)
    consistency = check_consistency(unified)
    consistency_json = session_dir / "consistency-report.json"
    save_json(consistency_json, consistency)

    try:
        test_cases = _retry(2, lambda: generate_test_cases(llm, unified, consistency_report=consistency))
    except Exception:
        test_cases = fallback_test_cases(unified)
    bug_templates: list[BugReport]
    try:
        bug_templates = _retry(2, lambda: generate_bug_report_templates(llm, test_cases))
    except Exception:
        bug_templates = []

    test_cases_json = session_dir / "test-cases.json"
    bugs_json = session_dir / "bug-reports.json"
    save_json(test_cases_json, [t.model_dump() for t in test_cases])
    save_json(bugs_json, [b.model_dump() for b in bug_templates])
    export_test_cases_local(session_dir, test_cases)
    export_bug_reports_local(session_dir, bug_templates)

    state.test_cases_path = str(test_cases_json)
    state.bug_reports_path = str(bugs_json)
    state.consistency_report_path = str(consistency_json)
    _save_session(state)
    return state


def agent_run(
    requirements: list[str],
    requirement_urls: list[str],
    figma_file_key: str | None = None,
    target_url: str | None = None,
    out_dir: str | None = None,
) -> dict:
    target = target_url or "https://example.com"
    session_id = ingest(requirements, requirement_urls, figma_file_key, target)
    state = generate_docs(session_id)
    consistency = (
        json.loads(Path(state.consistency_report_path).read_text(encoding="utf-8"))
        if state.consistency_report_path
        else {"summary": {"missing": 0, "contradiction": 0, "ambiguity": 0}}
    )
    result = {
        "session_id": session_id,
        "unified_model_path": state.unified_model_path,
        "consistency_report_path": state.consistency_report_path,
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


def run_manual(session_id: str) -> SessionState:
    state = _load_session(session_id)
    session_dir = _session_path(session_id)
    test_cases = [TestCase.model_validate(i) for i in json.loads(Path(state.test_cases_path).read_text(encoding="utf-8"))]
    results = run_manual_cases(test_cases, session_dir / "evidence")
    results_path = session_dir / "manual-results.json"
    save_json(results_path, [r.model_dump() for r in results])
    export_manual_results_local(session_dir, results)
    state.manual_results_path = str(results_path)
    _save_session(state)
    return state


def generate_autotests(session_id: str) -> SessionState:
    state = _load_session(session_id)
    session_dir = _session_path(session_id)
    test_cases = [TestCase.model_validate(i) for i in json.loads(Path(state.test_cases_path).read_text(encoding="utf-8"))]
    out_dir = Path("generated_tests") / session_id
    generate_playwright_pytest_tests(test_cases[:25], out_dir, str(state.target_url))
    state.generated_tests_dir = str(out_dir)
    _save_session(state)
    return state


def run_autotests(session_id: str) -> SessionState:
    state = _load_session(session_id)
    test_cases = [TestCase.model_validate(i) for i in json.loads(Path(state.test_cases_path).read_text(encoding="utf-8"))]
    if not state.generated_tests_dir:
        raise RuntimeError("Autotests are not generated yet")
    reports_dir = _session_path(session_id) / "reports"
    return_code, junit, html = run_pytest_suite(Path.cwd(), Path(state.generated_tests_dir), reports_dir)
    test_files = list(Path(state.generated_tests_dir).glob("test_*.py"))
    results = synthesize_auto_results(test_cases, test_files, return_code)
    results_path = _session_path(session_id) / "auto-results.json"
    save_json(results_path, [r.model_dump() for r in results])
    state.auto_results_path = str(results_path)
    state.junit_report_path = str(junit)
    state.html_report_path = str(html)
    _save_session(state)
    return state


def create_bug_drafts_from_failures(session_id: str) -> SessionState:
    state = _load_session(session_id)
    if not state.auto_results_path:
        raise RuntimeError("No auto-results found")
    if not state.bug_reports_path:
        state.bug_reports_path = str(_session_path(session_id) / "bug-reports.json")
        save_json(Path(state.bug_reports_path), [])

    auto_results = json.loads(Path(state.auto_results_path).read_text(encoding="utf-8"))
    bugs = [BugReport.model_validate(b) for b in json.loads(Path(state.bug_reports_path).read_text(encoding="utf-8"))]

    for idx, result in enumerate(auto_results, start=1):
        if result.get("status") != "failed":
            continue
        tc_id = result.get("test_case_id", f"unknown-{idx}")
        bugs.append(
            BugReport(
                bug_id=f"AUTO-BUG-{idx:03d}",
                title=f"Auto failure for {tc_id}",
                severity="major",
                priority="high",
                preconditions="Autotest execution context",
                steps=[f"Run generated test linked to {tc_id}"],
                actual_result=result.get("error") or "Automated test failed",
                expected_result="Automated test should pass",
                attachments=result.get("artifacts", []),
                linked_test_case_id=tc_id,
            )
        )
    save_json(Path(state.bug_reports_path), [b.model_dump() for b in bugs])
    _save_session(state)
    return state


def sync_reports(session_id: str, test_cases_sheet_url: str, bug_reports_sheet_url: str) -> dict:
    state = _load_session(session_id)
    test_cases = [TestCase.model_validate(i) for i in json.loads(Path(state.test_cases_path).read_text(encoding="utf-8"))]
    bug_reports = [BugReport.model_validate(i) for i in json.loads(Path(state.bug_reports_path).read_text(encoding="utf-8"))]

    t_id, t_gid = _parse_sheet(test_cases_sheet_url)
    b_id, b_gid = _parse_sheet(bug_reports_sheet_url)
    test_sync = sync_test_cases_to_sheet(t_id, t_gid, test_cases)
    bug_sync = sync_bug_reports_to_sheet(b_id, b_gid, bug_reports)

    unified = UnifiedRequirementModel.model_validate_json(Path(state.unified_model_path).read_text(encoding="utf-8"))
    coverage = check_requirement_coverage(unified, test_cases)
    pass_rate = {"auto_total": 0, "auto_passed": 0, "pass_rate": 0.0}
    if state.auto_results_path:
        from ai_qahelper.models import AutoExecutionResult

        auto_results = [
            AutoExecutionResult.model_validate(i)
            for i in json.loads(Path(state.auto_results_path).read_text(encoding="utf-8"))
        ]
        pass_rate = check_pass_rate(auto_results)

    quality = {"coverage": coverage, "pass_rate": pass_rate}
    save_json(_session_path(session_id) / "quality-gates.json", quality)
    return {"test_cases_synced": test_sync, "bug_reports_synced": bug_sync, "quality": quality}


def _parse_sheet(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    spreadsheet_id = parsed.path.split("/d/")[1].split("/")[0]
    gid = parse_qs(parsed.fragment).get("gid", ["0"])[0] if parsed.fragment else "0"
    if "gid=" in parsed.fragment:
        gid = parsed.fragment.split("gid=")[-1]
    return spreadsheet_id, gid
