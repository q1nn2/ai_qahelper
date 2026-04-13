from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import ParseResult, parse_qs, urlparse

from ai_qahelper.models import BugReport, TestCase, UnifiedRequirementModel
from ai_qahelper.quality import check_pass_rate, check_requirement_coverage
from ai_qahelper.reporting import save_json, sync_bug_reports_to_sheet, sync_test_cases_to_sheet
from ai_qahelper.session_service import load_session, session_path


def parse_sheet_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    spreadsheet_id = parsed.path.split("/d/")[1].split("/")[0]
    gid = worksheet_gid_from_url(parsed)
    return spreadsheet_id, gid


def worksheet_gid_from_url(parsed: ParseResult) -> str:
    q = parse_qs(parsed.query)
    if q.get("gid") and q["gid"][0].strip():
        return q["gid"][0].strip()
    if parsed.fragment:
        fq = parse_qs(parsed.fragment)
        if fq.get("gid") and fq["gid"][0].strip():
            return fq["gid"][0].strip()
        if "gid=" in parsed.fragment:
            tail = parsed.fragment.split("gid=", 1)[-1]
            return tail.split("&", 1)[0].strip() or "0"
    return "0"


def sync_reports(session_id: str, test_cases_sheet_url: str, bug_reports_sheet_url: str) -> dict:
    state = load_session(session_id)
    test_cases = [TestCase.model_validate(i) for i in json.loads(Path(state.test_cases_path).read_text(encoding="utf-8"))]
    bug_reports = [BugReport.model_validate(i) for i in json.loads(Path(state.bug_reports_path).read_text(encoding="utf-8"))]

    t_id, t_gid = parse_sheet_url(test_cases_sheet_url)
    b_id, b_gid = parse_sheet_url(bug_reports_sheet_url)
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
    save_json(session_path(session_id) / "quality-gates.json", quality)
    return {"test_cases_synced": test_sync, "bug_reports_synced": bug_sync, "quality": quality}
