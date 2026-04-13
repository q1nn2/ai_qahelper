from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from ai_qahelper.models import BugReport, ManualExecutionResult, TestCase, TestCaseExportColumn

# В выгрузке таблицы эти поля всегда пустые — их заполняет исполнитель (как в шаблоне TestRail/Excel).
_EXPORT_BLANK_EXECUTOR_FIELDS = frozenset({"environment", "status", "bug_report_id"})


def save_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_test_case_export_columns() -> list[TestCaseExportColumn]:
    return [
        TestCaseExportColumn(field="case_id", header="ID"),
        TestCaseExportColumn(field="title", header="Название тест-кейса"),
        TestCaseExportColumn(field="preconditions", header="Предусловия"),
        TestCaseExportColumn(field="steps", header="Описание шагов"),
        TestCaseExportColumn(field="expected_result", header="Ожидаемый результат"),
        TestCaseExportColumn(field="environment", header="Окружение"),
        TestCaseExportColumn(field="status", header="Статус"),
        TestCaseExportColumn(field="bug_report_id", header="ID баг-репорта"),
        TestCaseExportColumn(field="note", header="Примечание"),
    ]


def _test_case_cell(test_case: TestCase, field: str) -> str:
    if field in _EXPORT_BLANK_EXECUTOR_FIELDS:
        return ""
    if field == "steps":
        return "\n".join(test_case.steps)
    if field == "source_refs":
        return "; ".join(test_case.source_refs)
    return str(getattr(test_case, field))


def export_test_cases_local(
    base_dir: Path,
    test_cases: list[TestCase],
    columns: list[TestCaseExportColumn] | None = None,
) -> tuple[Path, Path]:
    base_dir.mkdir(parents=True, exist_ok=True)
    csv_path = base_dir / "test-cases.csv"
    xlsx_path = base_dir / "test-cases.xlsx"
    cols = columns if columns else default_test_case_export_columns()
    headers = [c.header for c in cols]
    rows = [{col.header: _test_case_cell(c, col.field) for col in cols} for c in test_cases]
    _write_csv(csv_path, rows, fieldnames=headers)
    pd.DataFrame(rows, columns=headers).to_excel(xlsx_path, index=False)
    return csv_path, xlsx_path


_BUG_EXPORT_KEYS = [
    "bug_id",
    "title",
    "severity",
    "priority",
    "preconditions",
    "steps",
    "actual_result",
    "expected_result",
    "attachments",
    "linked_test_case_id",
]


def export_bug_reports_local(base_dir: Path, bug_reports: list[BugReport]) -> tuple[Path, Path]:
    base_dir.mkdir(parents=True, exist_ok=True)
    csv_path = base_dir / "bug-reports.csv"
    xlsx_path = base_dir / "bug-reports.xlsx"
    rows = [
        {
            "bug_id": b.bug_id,
            "title": b.title,
            "severity": b.severity,
            "priority": b.priority,
            "preconditions": b.preconditions,
            "steps": " | ".join(b.steps),
            "actual_result": b.actual_result,
            "expected_result": b.expected_result,
            "attachments": ",".join(b.attachments),
            "linked_test_case_id": b.linked_test_case_id or "",
        }
        for b in bug_reports
    ]
    _write_csv(csv_path, rows, fieldnames=_BUG_EXPORT_KEYS)
    pd.DataFrame(rows, columns=_BUG_EXPORT_KEYS).to_excel(xlsx_path, index=False)
    return csv_path, xlsx_path


def export_manual_results_local(base_dir: Path, results: list[ManualExecutionResult]) -> Path:
    path = base_dir / "manual-results.csv"
    keys = ["test_case_id", "status", "notes", "evidence_files"]
    rows = [
        {
            "test_case_id": r.test_case_id,
            "status": r.status,
            "notes": r.notes,
            "evidence_files": ",".join(r.evidence_files),
        }
        for r in results
    ]
    _write_csv(path, rows, fieldnames=keys)
    return path


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = fieldnames if fieldnames is not None else (list(rows[0].keys()) if rows else [])
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _get_gspread_client() -> gspread.Client | None:
    cred_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not cred_path:
        return None
    creds = Credentials.from_service_account_file(
        cred_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def sync_test_cases_to_sheet(spreadsheet_id: str, worksheet_gid: str, test_cases: list[TestCase]) -> bool:
    client = _get_gspread_client()
    if not client:
        return False
    sh = client.open_by_key(spreadsheet_id)
    ws = next((w for w in sh.worksheets() if str(w.id) == str(worksheet_gid)), None)
    if ws is None:
        return False
    rows = [
        [
            c.case_id,
            c.title,
            c.preconditions,
            "\n".join(c.steps),
            c.expected_result,
            "",
            "",
            "",
            c.note,
        ]
        for c in test_cases
    ]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    return True


def sync_bug_reports_to_sheet(spreadsheet_id: str, worksheet_gid: str, bug_reports: list[BugReport]) -> bool:
    client = _get_gspread_client()
    if not client:
        return False
    sh = client.open_by_key(spreadsheet_id)
    ws = next((w for w in sh.worksheets() if str(w.id) == str(worksheet_gid)), None)
    if ws is None:
        return False
    rows = [
        [
            b.bug_id,
            b.title,
            b.severity,
            b.priority,
            b.preconditions,
            "\n".join(b.steps),
            b.actual_result,
            b.expected_result,
            ",".join(b.attachments),
            b.linked_test_case_id or "",
        ]
        for b in bug_reports
    ]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    return True
