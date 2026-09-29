from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ai_qahelper.session_service import session_path
from ai_qahelper.template_service import (
    DocumentationTemplate,
    enabled_columns,
    load_active_template,
    required_columns,
    template_record_value,
)

TEST_CASE_COLUMNS = [
    "case_id",
    "requirement_id",
    "title",
    "preconditions",
    "steps",
    "expected_result",
    "priority",
    "status",
    "quality_status",
    "note",
    "source_refs",
]
CHECKLIST_COLUMNS = [
    "item_id",
    "requirement_id",
    "area",
    "check",
    "expected_result",
    "priority",
    "status",
    "quality_status",
    "note",
    "source_refs",
]
BUG_REPORT_COLUMNS = [
    "bug_id",
    "title",
    "steps",
    "expected_result",
    "actual_result",
    "status",
    "priority",
    "severity",
    "preconditions",
    "environment",
    "comment",
    "attachment",
    "linked_test_case_id",
]
_LIST_COLUMNS = {"steps", "source_refs"}
_WEAK_EXPECTED_PHRASES = (
    "работает корректно",
    "работает правильно",
    "отображается корректно",
    "успешно",
    "ok",
)
_SPACE_RE = re.compile(r"\s+")


def find_session_artifacts(session_id: str) -> dict:
    sdir = _session_dir(session_id)
    return {
        "session_dir": str(sdir),
        "test_cases_original": _first_existing(sdir, ["test-cases.json"]),
        "test_cases_edited": _first_existing(sdir, ["test-cases.edited.json"]),
        "test_cases_final": _first_existing(sdir, ["test-cases.final.json"]),
        "test_cases_final_xlsx": _first_existing(sdir, ["test-cases.final.xlsx"]),
        "checklist_original": _first_existing(sdir, ["checklist.json"]),
        "checklist_edited": _first_existing(sdir, ["checklist.edited.json"]),
        "checklist_final": _first_existing(sdir, ["checklist.final.json"]),
        "checklist_final_xlsx": _first_existing(sdir, ["checklist.final.xlsx"]),
        "bug_reports_original": _first_existing(sdir, ["bug-reports.json"]),
        "bug_reports_edited": _first_existing(sdir, ["bug-reports.edited.json"]),
        "bug_reports_final": _first_existing(sdir, ["bug-reports.final.json"]),
        "bug_reports_final_xlsx": _first_existing(sdir, ["bug-reports.final.xlsx"]),
    }


def load_test_cases_for_ui(session_id: str, prefer_edited: bool = True) -> pd.DataFrame:
    path = _artifact_path(session_id, "test-cases", prefer_edited)
    if path is None:
        return pd.DataFrame(columns=TEST_CASE_COLUMNS)
    return _load_table(path, TEST_CASE_COLUMNS, "case_id")


def save_test_cases_from_ui(session_id: str, df: pd.DataFrame) -> dict:
    path = _session_dir(session_id) / "test-cases.edited.json"
    rows = _df_to_records(df, TEST_CASE_COLUMNS)
    _save_json(path, rows)
    return {"path": str(path), "rows": len(rows)}


def load_checklist_for_ui(session_id: str, prefer_edited: bool = True) -> pd.DataFrame:
    path = _artifact_path(session_id, "checklist", prefer_edited)
    if path is None:
        return pd.DataFrame(columns=CHECKLIST_COLUMNS)
    return _load_table(path, CHECKLIST_COLUMNS, "item_id")


def save_checklist_from_ui(session_id: str, df: pd.DataFrame) -> dict:
    path = _session_dir(session_id) / "checklist.edited.json"
    rows = _df_to_records(df, CHECKLIST_COLUMNS)
    _save_json(path, rows)
    return {"path": str(path), "rows": len(rows)}


def load_bug_reports_for_ui(session_id: str, prefer_edited: bool = True) -> pd.DataFrame:
    path = _artifact_path(session_id, "bug-reports", prefer_edited)
    if path is None:
        return pd.DataFrame(columns=BUG_REPORT_COLUMNS)
    return _load_table(path, BUG_REPORT_COLUMNS, "bug_id")


def save_bug_reports_from_ui(session_id: str, df: pd.DataFrame) -> dict:
    path = _session_dir(session_id) / "bug-reports.edited.json"
    rows = _df_to_records(df, BUG_REPORT_COLUMNS)
    _save_json(path, rows)
    return {"path": str(path), "rows": len(rows)}


def build_local_quality_status(
    df: pd.DataFrame,
    artifact_type: str,
    template: DocumentationTemplate | None = None,
) -> pd.DataFrame:
    result = df.copy()
    if result.empty:
        result["quality_status"] = []
        result["quality_issues"] = []
        result["duplicate_candidate"] = []
        return result

    duplicate_keys = _duplicate_keys(result, artifact_type)
    statuses: list[str] = []
    issue_texts: list[str] = []
    duplicates: list[bool] = []
    for _, row in result.iterrows():
        issues = _quality_issues(row, artifact_type, template)
        key = _duplicate_key(row, artifact_type)
        is_duplicate = bool(key and duplicate_keys.get(key, 0) > 1)
        if is_duplicate:
            issues.append("Duplicate candidate")
        statuses.append("Good" if not issues else "Needs review")
        issue_texts.append(", ".join(dict.fromkeys(issues)))
        duplicates.append(is_duplicate)

    result["quality_status"] = statuses
    result["quality_issues"] = issue_texts
    result["duplicate_candidate"] = duplicates
    return result


def list_export_files(session_id: str) -> list[dict]:
    sdir = _session_dir(session_id)
    if not sdir.exists():
        return []
    files: list[dict] = []
    for path in sorted((p for p in sdir.rglob("*") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "path": str(path),
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "type": _file_type(path),
            }
        )
    return files


def export_final_test_cases_xlsx(session_id: str) -> Path:
    final_path = _ensure_final_json(session_id, "test-cases")
    xlsx_path = final_path.with_suffix(".xlsx")
    _records_to_excel(final_path, xlsx_path, load_active_template("test_cases", session_id))
    return xlsx_path


def export_final_checklist_xlsx(session_id: str) -> Path:
    final_path = _ensure_final_json(session_id, "checklist")
    xlsx_path = final_path.with_suffix(".xlsx")
    _records_to_excel(final_path, xlsx_path, load_active_template("checklist", session_id))
    return xlsx_path


def export_final_bug_reports_xlsx(session_id: str) -> Path:
    final_path = _ensure_final_json(session_id, "bug-reports")
    xlsx_path = final_path.with_suffix(".xlsx")
    _records_to_excel(final_path, xlsx_path, load_active_template("bug_reports", session_id))
    return xlsx_path


def approve_test_cases_final(session_id: str) -> Path:
    return _approve_final(session_id, "test-cases")


def approve_checklist_final(session_id: str) -> Path:
    return _approve_final(session_id, "checklist")


def approve_bug_reports_final(session_id: str) -> Path:
    return _approve_final(session_id, "bug-reports")


def create_final_files_zip(session_id: str) -> Path:
    sdir = _session_dir(session_id)
    zip_path = sdir / "final-files.zip"
    final_files = [p for p in sdir.glob("*.final.*") if p.is_file()]
    if not final_files:
        approve_test_cases_final(session_id) if (sdir / "test-cases.json").exists() else None
        approve_checklist_final(session_id) if (sdir / "checklist.json").exists() else None
        approve_bug_reports_final(session_id) if (sdir / "bug-reports.json").exists() else None
        final_files = [p for p in sdir.glob("*.final.*") if p.is_file()]
    _write_zip(zip_path, final_files, sdir)
    return zip_path


def create_session_zip(session_id: str) -> Path:
    sdir = _session_dir(session_id)
    zip_path = sdir / "session.zip"
    _write_zip(zip_path, [p for p in sdir.rglob("*") if p.is_file() and p.name != "session.zip"], sdir)
    return zip_path


def _session_dir(session_id: str) -> Path:
    clean_id = (session_id or "").strip()
    if not clean_id:
        return Path("runs") / ""
    try:
        return session_path(clean_id)
    except Exception:  # noqa: BLE001 - local UI should stay usable even if config is not loaded yet
        return Path("runs") / clean_id


def _artifact_path(session_id: str, prefix: str, prefer_edited: bool) -> Path | None:
    sdir = _session_dir(session_id)
    names = [f"{prefix}.edited.json", f"{prefix}.json"] if prefer_edited else [f"{prefix}.json", f"{prefix}.edited.json"]
    return _first_existing(sdir, names)


def _first_existing(base_dir: Path, names: list[str]) -> Path | None:
    for name in names:
        path = base_dir / name
        if path.is_file():
            return path
    return None


def _load_table(path: Path, columns: list[str], id_column: str) -> pd.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("items", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        records = []
    normalized = [_normalize_record(record, columns) for record in records if isinstance(record, dict)]
    df = pd.DataFrame(normalized)
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    if id_column in df.columns:
        df = df.sort_values(id_column, kind="stable", ignore_index=True)
    return df


def _normalize_record(record: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    normalized = dict(record)
    for column in _LIST_COLUMNS:
        if column in normalized:
            normalized[column] = _list_to_text(normalized[column])
    normalized.setdefault("requirement_id", _requirement_id_from_refs(normalized.get("source_refs", "")))
    normalized.setdefault("priority", "")
    normalized.setdefault("status", "Draft")
    normalized.setdefault("quality_status", "")
    for column in columns:
        normalized.setdefault(column, "")
    return normalized


def _df_to_records(df: pd.DataFrame, preferred_columns: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    columns = list(dict.fromkeys([*preferred_columns, *df.columns.tolist()]))
    for _, row in df.fillna("").iterrows():
        item: dict[str, Any] = {}
        for column in columns:
            value = row.get(column, "")
            if column in _LIST_COLUMNS:
                item[column] = _text_to_list(value)
            else:
                item[column] = _clean_scalar(value)
        records.append(item)
    return records


def _quality_issues(
    row: pd.Series,
    artifact_type: str,
    template: DocumentationTemplate | None = None,
) -> list[str]:
    title_field = "check" if artifact_type == "checklist" else "title"
    title = _clean_scalar(row.get(title_field, ""))
    expected = _clean_scalar(row.get("expected_result", ""))
    requirement_id = _clean_scalar(row.get("requirement_id", ""))
    source_refs = _text_to_list(row.get("source_refs", ""))
    issues: list[str] = []
    if _missing_required_template_fields(row, template) or (template is None and (not title or not expected)):
        issues.append("Missing fields")
    if artifact_type == "test_cases" and not _text_to_list(row.get("steps", "")):
        issues.append("Empty steps")
    if _is_weak_expected(expected):
        issues.append("Weak expected result")
    if not requirement_id and not source_refs:
        issues.append("No requirement link")
    if _too_generic_title(title, artifact_type):
        issues.append("Too generic title")
    return issues


def _duplicate_keys(df: pd.DataFrame, artifact_type: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, row in df.iterrows():
        key = _duplicate_key(row, artifact_type)
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _duplicate_key(row: pd.Series, artifact_type: str) -> str:
    if artifact_type == "checklist":
        return _normalize_text(f"{row.get('check', '')} {row.get('expected_result', '')}")
    return _normalize_text(f"{row.get('title', '')} {row.get('steps', '')}")


def _is_weak_expected(value: str) -> bool:
    text = _normalize_text(value)
    if len(text) < 20:
        return True
    return any(phrase in text for phrase in _WEAK_EXPECTED_PHRASES)


def _too_generic_title(value: str, artifact_type: str) -> bool:
    text = _normalize_text(value)
    min_words = 4 if artifact_type == "checklist" else 3
    return len(text.split()) < min_words or text in {"проверка", "тест", "проверка формы", "проверка функциональности"}


def _requirement_id_from_refs(value: Any) -> str:
    refs = _text_to_list(value)
    return refs[0] if refs else ""


def _ensure_final_json(session_id: str, prefix: str) -> Path:
    final_path = _session_dir(session_id) / f"{prefix}.final.json"
    if final_path.exists():
        return final_path
    return _approve_final(session_id, prefix)


def _approve_final(session_id: str, prefix: str) -> Path:
    sdir = _session_dir(session_id)
    source = _first_existing(sdir, [f"{prefix}.edited.json", f"{prefix}.json"])
    if source is None:
        raise FileNotFoundError(f"Не найден {prefix}.json или {prefix}.edited.json для сессии {session_id}")
    final_path = sdir / f"{prefix}.final.json"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, final_path)
    return final_path


def _records_to_excel(json_path: Path, xlsx_path: Path, template: DocumentationTemplate | None = None) -> None:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    records = payload.get("items", payload) if isinstance(payload, dict) else payload
    rows = records if isinstance(records, list) else []
    normalized = []
    if template is not None:
        columns = enabled_columns(template)
        for row in rows:
            if isinstance(row, dict):
                normalized.append({column.label: _list_to_text(template_record_value(row, column.key)) for column in columns})
        headers = [column.label for column in columns]
    else:
        for row in rows:
            if isinstance(row, dict):
                normalized.append({key: _list_to_text(value) for key, value in row.items()})
        headers = None
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(normalized, columns=headers).to_excel(xlsx_path, index=False)


def _save_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_zip(zip_path: Path, files: list[Path], base_dir: Path) -> None:
    import zipfile

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            if path.is_file():
                zf.write(path, path.relative_to(base_dir))


def _file_type(path: Path) -> str:
    name = path.name
    if ".final." in name:
        return "final"
    if ".edited." in name:
        return "edited"
    if "report" in name:
        return "reports"
    if path.suffix.lower() in {".json", ".xlsx", ".csv", ".md"}:
        return "generated"
    return "other"


def _missing_required_template_fields(row: pd.Series, template: DocumentationTemplate | None) -> bool:
    if template is None:
        return False
    for column in required_columns(template):
        value = template_record_value(row.to_dict(), column.key)
        if isinstance(value, list):
            if not [item for item in value if _clean_scalar(item)]:
                return True
        elif not _clean_scalar(value):
            return True
    return False


def _list_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(_clean_scalar(item) for item in value if _clean_scalar(item))
    if isinstance(value, tuple):
        return "\n".join(_clean_scalar(item) for item in value if _clean_scalar(item))
    return _clean_scalar(value)


def _text_to_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_clean_scalar(item) for item in value if _clean_scalar(item)]
    text = _clean_scalar(value)
    if not text:
        return []
    parts = re.split(r"\r?\n| \| |;", text)
    return [part.strip() for part in parts if part.strip()]


def _clean_scalar(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", _clean_scalar(value).replace("ё", "е").lower()).strip()
