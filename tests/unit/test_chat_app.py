from __future__ import annotations

from pathlib import Path

from ai_qahelper.chat_agent import ChatContext, handle_message
from ai_qahelper.chat_app import SUPPORTED_UPLOAD_TYPES, _download_label
from ai_qahelper.chat_planner import ChatPlan, PlanAction


def test_supported_upload_types_include_word_and_excel() -> None:
    assert {"docx", "xlsx", "xls"}.issubset(SUPPORTED_UPLOAD_TYPES)


def test_download_labels_are_user_friendly() -> None:
    assert _download_label(Path("runs/s1/test-cases.xlsx")) == "Скачать test-cases.xlsx"
    assert _download_label(Path("runs/s1/checklist.xlsx")) == "Скачать checklist.xlsx"
    assert _download_label(Path("runs/s1/test-cases-quality-report.json")) == "Скачать quality report"
    assert _download_label(Path("runs/s1/exploratory-report.md")) == "Скачать exploratory report"
    assert _download_label(Path("runs/s1/test-cases.json")) == "Скачать JSON"


def test_missing_api_key_error_is_friendly(monkeypatch) -> None:
    class FakeExecutor:
        def execute(self, context, plan, user_message=""):
            raise RuntimeError("Missing API key: OPENAI_API_KEY")

    monkeypatch.setattr("ai_qahelper.chat_agent.save_agent_memory", lambda memory: None)
    response = handle_message(
        ChatContext(requirements=["req.md"], target_url="https://example.com"),
        "сделай тест-кейсы",
        plan=ChatPlan(actions=[PlanAction(type="agent_run", artifact_type="testcases")]),
        executor=FakeExecutor(),
    )

    assert "Не найден OPENAI_API_KEY" in response.message
    assert "OPENAI_API_KEY" in response.missing_inputs
    assert response.technical_error == "RuntimeError: Missing API key: OPENAI_API_KEY"
