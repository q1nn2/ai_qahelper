from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from ai_qahelper.ui_documents import (
    approve_checklist_final,
    approve_test_cases_final,
    build_local_quality_status,
    export_final_checklist_xlsx,
    export_final_test_cases_xlsx,
    list_export_files,
    load_checklist_for_ui,
    load_test_cases_for_ui,
    save_checklist_from_ui,
    save_test_cases_from_ui,
)


def _configure_tmp_project(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    config = {
        "llm": {"model": "gpt-4.1-mini", "api_key_env": "OPENAI_API_KEY"},
        "docs_dir": "examples/input",
        "sessions_dir": "runs",
        "envs": [],
    }
    Path("ai-tester.config.yaml").write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
    session_dir = tmp_path / "runs" / "s1"
    session_dir.mkdir(parents=True)
    return session_dir


def _test_cases() -> list[dict]:
    return [
        {
            "case_id": "TC-001",
            "requirement_id": "REQ-1",
            "title": "Пользователь входит по валидному email",
            "preconditions": "Пользователь зарегистрирован",
            "steps": ["Открыть страницу входа", "Ввести test@example.com и пароль"],
            "expected_result": "Пользователь перенаправлен в личный кабинет, отображается имя профиля.",
            "priority": "high",
            "status": "Draft",
            "source_refs": ["REQ-1"],
        },
        {
            "case_id": "TC-002",
            "requirement_id": "",
            "title": "",
            "preconditions": "",
            "steps": [],
            "expected_result": "ОК",
            "priority": "medium",
            "status": "Draft",
            "source_refs": [],
        },
    ]


def _checklist() -> list[dict]:
    return [
        {
            "item_id": "CH-001",
            "requirement_id": "REQ-1",
            "area": "Login",
            "check": "Проверить успешный вход по валидным данным",
            "expected_result": "Пользователь видит личный кабинет и активную сессию.",
            "priority": "high",
            "status": "Draft",
            "source_refs": ["REQ-1"],
        }
    ]


def test_load_test_cases_for_ui_does_not_call_llm(tmp_path: Path, monkeypatch) -> None:
    session_dir = _configure_tmp_project(tmp_path, monkeypatch)
    (session_dir / "test-cases.json").write_text(json.dumps(_test_cases(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("ai_qahelper.chat_agent.handle_message", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError))

    df = load_test_cases_for_ui("s1")

    assert len(df) == 2
    assert df.loc[0, "case_id"] == "TC-001"


def test_save_test_cases_from_ui_creates_edited_json_and_keeps_original(tmp_path: Path, monkeypatch) -> None:
    session_dir = _configure_tmp_project(tmp_path, monkeypatch)
    original = _test_cases()
    original_path = session_dir / "test-cases.json"
    original_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

    result = save_test_cases_from_ui("s1", pd.DataFrame(original).assign(title="Edited"))

    assert Path(result["path"]).name == "test-cases.edited.json"
    assert (session_dir / "test-cases.edited.json").is_file()
    assert json.loads(original_path.read_text(encoding="utf-8")) == original


def test_build_local_quality_status_marks_problem_types_and_good() -> None:
    df = pd.DataFrame(_test_cases())

    result = build_local_quality_status(df, "test_cases")

    good = result[result["case_id"] == "TC-001"].iloc[0]
    weak = result[result["case_id"] == "TC-002"].iloc[0]
    assert good["quality_status"] == "Good"
    assert "Missing fields" in weak["quality_issues"]
    assert "Empty steps" in weak["quality_issues"]
    assert "Weak expected result" in weak["quality_issues"]
    assert "No requirement link" in weak["quality_issues"]


def test_build_local_quality_status_marks_duplicate_candidates() -> None:
    cases = _test_cases()
    cases.append({**cases[0], "case_id": "TC-003"})

    result = build_local_quality_status(pd.DataFrame(cases), "test_cases")

    assert result["duplicate_candidate"].tolist().count(True) == 2


def test_list_export_files_returns_size_and_modified_at(tmp_path: Path, monkeypatch) -> None:
    session_dir = _configure_tmp_project(tmp_path, monkeypatch)
    (session_dir / "test-cases.json").write_text("[]", encoding="utf-8")

    files = list_export_files("s1")

    assert files[0]["name"] == "test-cases.json"
    assert files[0]["size"] == 2
    assert files[0]["modified_at"]


def test_approve_and_export_final_test_cases(tmp_path: Path, monkeypatch) -> None:
    session_dir = _configure_tmp_project(tmp_path, monkeypatch)
    (session_dir / "test-cases.json").write_text(json.dumps(_test_cases(), ensure_ascii=False), encoding="utf-8")

    final_json = approve_test_cases_final("s1")
    final_xlsx = export_final_test_cases_xlsx("s1")

    assert final_json.name == "test-cases.final.json"
    assert final_json.is_file()
    assert final_xlsx.name == "test-cases.final.xlsx"
    assert final_xlsx.is_file()


def test_checklist_functions_work_like_test_cases(tmp_path: Path, monkeypatch) -> None:
    session_dir = _configure_tmp_project(tmp_path, monkeypatch)
    (session_dir / "checklist.json").write_text(json.dumps(_checklist(), ensure_ascii=False), encoding="utf-8")

    df = load_checklist_for_ui("s1")
    saved = save_checklist_from_ui("s1", df.assign(status="Approved"))
    final_json = approve_checklist_final("s1")
    final_xlsx = export_final_checklist_xlsx("s1")

    assert len(df) == 1
    assert Path(saved["path"]).name == "checklist.edited.json"
    assert final_json.name == "checklist.final.json"
    assert final_xlsx.name == "checklist.final.xlsx"
    assert final_xlsx.is_file()
