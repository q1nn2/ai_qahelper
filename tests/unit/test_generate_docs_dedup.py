from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ai_qahelper import docs_service
from ai_qahelper.docs_service import generate_docs
from ai_qahelper.models import RequirementItem, SessionState, TestCase, UnifiedRequirementModel


class _DummyLlm:
    def __init__(self, cfg) -> None:  # noqa: ANN001
        self.cfg = cfg


def test_generate_docs_deduplicates_before_saving_and_export(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "ai-tester.config.yaml").write_text(
        yaml.dump(
            {
                "llm": {"api_key": "test-key"},
                "sessions_dir": "runs",
                "generate_test_analysis": False,
                "generate_bug_templates": False,
                "envs": [],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    session_id = "unit-session"
    session_dir = tmp_path / "runs" / session_id
    session_dir.mkdir(parents=True)
    unified = UnifiedRequirementModel(
        requirements=[RequirementItem(source="req.md", content="Login requirement")],
        target_url="https://example.com",
    )
    unified_path = session_dir / "unified-model.json"
    unified_path.write_text(unified.model_dump_json(), encoding="utf-8")
    state = SessionState(
        session_id=session_id,
        created_at=datetime.now(UTC),
        target_url="https://example.com",
        unified_model_path=str(unified_path),
    )
    (session_dir / "session.json").write_text(state.model_dump_json(), encoding="utf-8")

    def fake_generate_test_cases(*args, **kwargs):  # noqa: ANN002, ANN003
        return [
            TestCase(
                case_id="TC-001",
                title="Логин",
                preconditions="Открыта форма",
                steps=["Ввести логин", "Нажать Войти"],
                expected_result="Открыт кабинет",
                source_refs=["REQ-1"],
            ),
            TestCase(
                case_id="TC-002",
                title="Логин",
                preconditions="Открыта форма",
                steps=["1. Ввести логин", "2. Нажать Войти"],
                expected_result="Открыт кабинет",
                source_refs=["REQ-2"],
            ),
        ]

    monkeypatch.setattr(docs_service, "LlmClient", _DummyLlm)
    monkeypatch.setattr(docs_service, "generate_test_cases", fake_generate_test_cases)

    result = generate_docs(session_id, skip_test_analysis=True)

    saved_cases = json.loads(Path(result.test_cases_path).read_text(encoding="utf-8"))
    dedup_report = json.loads(Path(result.dedup_report_path).read_text(encoding="utf-8"))
    coverage_report = json.loads(Path(result.coverage_report_path).read_text(encoding="utf-8"))
    assert len(saved_cases) == 1
    assert saved_cases[0]["case_id"] == "TC-001"
    assert saved_cases[0]["source_refs"] == ["REQ-1", "REQ-2"]
    assert dedup_report["before"] == 2
    assert dedup_report["after"] == 1
    assert dedup_report["removed"] == 1
    assert dedup_report["duplicate_groups"][0]["removed_case_ids"] == ["TC-002"]
    assert Path(result.coverage_report_path).name == "coverage-report.json"
    assert coverage_report["summary"]["requirements_total"] == 1
    assert coverage_report["summary"]["requirements_covered"] == 1
