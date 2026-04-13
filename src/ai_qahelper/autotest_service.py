from __future__ import annotations

import json
from pathlib import Path

from ai_qahelper.execution import (
    generate_playwright_pytest_tests,
    run_manual_cases,
    run_pytest_suite,
    synthesize_auto_results,
)
from ai_qahelper.junit_parse import parse_junit_failure_messages, pytest_name_to_case_id
from ai_qahelper.models import BugReport, SessionState, TestCase
from ai_qahelper.reporting import export_manual_results_local, save_json
from ai_qahelper.session_service import load_session, save_session, session_path


def _infer_bug_severity_priority(failure_text: str) -> tuple[str, str]:
    t = (failure_text or "").lower()
    if any(x in t for x in ("timeout", "timed out", "connection refused", "errno", "playwright", "browser")):
        return "critical", "urgent"
    if "assert" in t or "assertionerror" in t:
        return "major", "high"
    if "skip" in t or "xfail" in t:
        return "minor", "low"
    return "major", "medium"


def _failure_title(tc_id: str, snippet: str) -> str:
    line = (snippet or "").strip().split("\n", 1)[0].strip()
    if len(line) > 120:
        line = line[:117] + "..."
    if line:
        return f"Автотест {tc_id}: {line}"
    return f"Падение автотеста {tc_id}"


def run_manual(session_id: str) -> SessionState:
    state = load_session(session_id)
    sdir = session_path(session_id)
    test_cases = [TestCase.model_validate(i) for i in json.loads(Path(state.test_cases_path).read_text(encoding="utf-8"))]
    results = run_manual_cases(test_cases, sdir / "evidence")
    results_path = sdir / "manual-results.json"
    save_json(results_path, [r.model_dump() for r in results])
    export_manual_results_local(sdir, results)
    state.manual_results_path = str(results_path)
    save_session(state)
    return state


def generate_autotests(session_id: str) -> SessionState:
    state = load_session(session_id)
    sdir = session_path(session_id)
    test_cases = [TestCase.model_validate(i) for i in json.loads(Path(state.test_cases_path).read_text(encoding="utf-8"))]
    out_dir = Path("generated_tests") / session_id
    generate_playwright_pytest_tests(test_cases[:25], out_dir, str(state.target_url))
    state.generated_tests_dir = str(out_dir)
    save_session(state)
    return state


def run_autotests(session_id: str) -> SessionState:
    state = load_session(session_id)
    test_cases = [TestCase.model_validate(i) for i in json.loads(Path(state.test_cases_path).read_text(encoding="utf-8"))]
    if not state.generated_tests_dir:
        raise RuntimeError("Autotests are not generated yet")
    reports_dir = session_path(session_id) / "reports"
    return_code, junit, html = run_pytest_suite(Path.cwd(), Path(state.generated_tests_dir), reports_dir)
    test_files = list(Path(state.generated_tests_dir).glob("test_*.py"))
    results = synthesize_auto_results(test_cases, test_files, return_code)
    results_path = session_path(session_id) / "auto-results.json"
    save_json(results_path, [r.model_dump() for r in results])
    state.auto_results_path = str(results_path)
    state.junit_report_path = str(junit)
    state.html_report_path = str(html)
    save_session(state)
    return state


def create_bug_drafts_from_failures(session_id: str) -> SessionState:
    state = load_session(session_id)
    if not state.auto_results_path:
        raise RuntimeError("No auto-results found")
    if not state.bug_reports_path:
        state.bug_reports_path = str(session_path(session_id) / "bug-reports.json")
        save_json(Path(state.bug_reports_path), [])

    auto_results = json.loads(Path(state.auto_results_path).read_text(encoding="utf-8"))
    bugs = [BugReport.model_validate(b) for b in json.loads(Path(state.bug_reports_path).read_text(encoding="utf-8"))]

    junit_by_func = {}
    if state.junit_report_path:
        junit_by_func = parse_junit_failure_messages(Path(state.junit_report_path))

    failures_by_case: dict[str, str] = {}
    for fname, text in junit_by_func.items():
        cid = pytest_name_to_case_id(fname)
        if cid:
            failures_by_case[cid] = text

    for idx, result in enumerate(auto_results, start=1):
        if result.get("status") != "failed":
            continue
        tc_id = result.get("test_case_id", f"unknown-{idx}")
        err = result.get("error") or ""
        detail = failures_by_case.get(tc_id) or err or "Automated test failed"
        sev, pri = _infer_bug_severity_priority(detail)
        title = _failure_title(str(tc_id), detail)
        steps = [
            f"Открыть сгенерированный тест для {tc_id}",
            "Запустить pytest для каталога generated_tests",
        ]
        if result.get("test_file"):
            steps.insert(1, f"Файл: {result['test_file']}")

        bugs.append(
            BugReport(
                bug_id=f"AUTO-BUG-{idx:03d}",
                title=title,
                severity=sev,  # type: ignore[arg-type]
                priority=pri,  # type: ignore[arg-type]
                preconditions="Запуск автотестов Playwright/pytest для сессии",
                steps=steps,
                actual_result=detail[:8000],
                expected_result="Автотест завершается без ошибок",
                attachments=result.get("artifacts", []),
                linked_test_case_id=tc_id,
            )
        )
    save_json(Path(state.bug_reports_path), [b.model_dump() for b in bugs])
    save_session(state)
    return state
