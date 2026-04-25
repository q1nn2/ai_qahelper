from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ai_qahelper import docs_service
from ai_qahelper.docs_service import generate_docs
from ai_qahelper.models import ChecklistItem, RequirementItem, SessionState, TestCase, UnifiedRequirementModel


class _DummyLlm:
    def __init__(self, cfg) -> None:  # noqa: ANN001
        self.cfg = cfg


def _write_session(tmp_path: Path, session_id: str = "quality-session") -> str:
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
    return session_id


def test_generate_docs_writes_test_case_quality_report(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    session_id = _write_session(tmp_path)

    def fake_generate_test_cases(*args, **kwargs):  # noqa: ANN002, ANN003
        return [
            TestCase(
                case_id="TC-001",
                title="Отображение ошибки при пустом Email",
                preconditions="Пользователь находится на форме входа, поле Email пустое",
                steps=["Открыть форму входа", "Оставить поле Email пустым и нажать кнопку 'Войти'"],
                expected_result="Под полем Email отображается сообщение об ошибке о причине невалидного значения",
                source_refs=["REQ-1"],
            ),
            TestCase(
                case_id="TC-002",
                title="Проверка формы",
                preconditions="Открыта форма",
                steps=["Проверить всё"],
                expected_result="Форма работает корректно",
                source_refs=[],
            ),
        ]

    monkeypatch.setattr(docs_service, "LlmClient", _DummyLlm)
    monkeypatch.setattr(docs_service, "generate_test_cases", fake_generate_test_cases)

    result = generate_docs(session_id, skip_test_analysis=True)

    saved_cases = json.loads(Path(result.test_cases_path).read_text(encoding="utf-8"))
    quality_report = json.loads(Path(result.quality_report_path).read_text(encoding="utf-8"))
    assert Path(result.quality_report_path).name == "test-cases-quality-report.json"
    assert quality_report["type"] == "test_cases"
    assert quality_report["total"] == 2
    assert "Quality: ready" in saved_cases[0]["note"]
    assert "Quality:" in saved_cases[1]["note"]
    assert "vague_expected_result" in saved_cases[1]["note"]


def test_generate_docs_writes_checklist_quality_report(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    session_id = _write_session(tmp_path, "checklist-quality-session")

    def fake_generate_checklist(*args, **kwargs):  # noqa: ANN002, ANN003
        return [
            ChecklistItem(
                item_id="CL-001",
                area="Авторизация",
                check="Проверить, что кнопка 'Войти' неактивна при пустом обязательном поле Email",
                expected_result="Кнопка 'Войти' остаётся неактивной, пока обязательное поле Email пустое",
                priority="high",
                source_refs=["REQ-1"],
            ),
            ChecklistItem(
                item_id="CL-002",
                area="Форма",
                check="Проверить корректность работы формы",
                expected_result="Форма работает корректно",
                priority="medium",
                source_refs=[],
            ),
        ]

    monkeypatch.setattr(docs_service, "LlmClient", _DummyLlm)
    monkeypatch.setattr(docs_service, "generate_checklist", fake_generate_checklist)

    result = generate_docs(session_id, skip_test_analysis=True, artifact_type="checklist")

    saved_items = json.loads(Path(result.checklist_path).read_text(encoding="utf-8"))
    quality_report = json.loads(Path(result.quality_report_path).read_text(encoding="utf-8"))
    assert Path(result.quality_report_path).name == "checklist-quality-report.json"
    assert quality_report["type"] == "checklist"
    assert quality_report["total"] == 2
    assert "Quality: ready" in saved_items[0]["note"]
    assert "vague_check" in saved_items[1]["note"]
