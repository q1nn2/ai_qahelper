from __future__ import annotations

from pathlib import Path

from ai_qahelper.chat_agent import ChatContext, handle_message
from ai_qahelper.chat_app import (
    MAIN_SCREEN_CAPTION,
    MISSING_API_KEY_MESSAGE,
    MISSING_QUICK_ACTION_API_KEY_WARNING,
    MISSING_QUICK_ACTION_CONTEXT_WARNING,
    SUPPORTED_UPLOAD_TYPES,
    _download_label,
    clear_chat_state,
    remember_warning_once,
    run_validated_ai_action,
    should_remember_message,
    validate_quick_action,
)
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


def test_chat_app_uses_single_professional_main_screen_caption() -> None:
    source = Path("src/ai_qahelper/chat_app.py").read_text(encoding="utf-8")
    old_phrase = "Загрузите требования или вставьте ссылку на сайт, затем напишите задачу обычным языком."
    new_phrase_start = "Загрузите требования или укажите URL тестируемого стенда"

    assert new_phrase_start in MAIN_SCREEN_CAPTION
    assert new_phrase_start in source
    assert "сгенерировать тест-кейсы" in source
    assert old_phrase not in source
    assert source.count(new_phrase_start) == 1


def test_chat_app_replaces_old_api_key_setup_warning() -> None:
    source = Path("src/ai_qahelper/chat_app.py").read_text(encoding="utf-8")

    assert "OPENAI_API_KEY не найден. Вставьте ключ ниже" in MISSING_API_KEY_MESSAGE
    assert "OPENAI_API_KEY не найден. Вставьте ключ ниже" in source
    assert "Добавьте строку `OPENAI_API_KEY=sk-...`" not in source


def test_should_remember_message_skips_duplicate_same_role_message() -> None:
    messages = [
        {"role": "user", "content": "Сделай тест-кейсы"},
        {"role": "assistant", "content": "Ок"},
    ]

    assert should_remember_message(messages, "user", "Сделай тест-кейсы") is False
    assert should_remember_message(messages, "assistant", "Ок") is False
    assert should_remember_message(messages, "user", "Сделай чек-лист") is True


def test_validate_quick_action_without_api_key_returns_warning() -> None:
    warning = validate_quick_action(
        ChatContext(requirements=["requirements.md"], target_url="https://example.com"),
        "Сделай тест-кейсы",
        has_api_key=False,
    )

    assert warning == MISSING_QUICK_ACTION_API_KEY_WARNING


def test_validate_quick_action_without_generation_context_returns_warning() -> None:
    warning = validate_quick_action(ChatContext(), "Сделай тест-кейсы", has_api_key=True)

    assert warning == MISSING_QUICK_ACTION_CONTEXT_WARNING


def test_validate_quick_action_with_api_key_and_context_allows_message() -> None:
    warning = validate_quick_action(ChatContext(target_url="https://example.com"), "Сделай тест-кейсы", has_api_key=True)

    assert warning is None


def test_clear_chat_state_keeps_session_context() -> None:
    state = {
        "messages": [{"role": "user", "content": "Сделай тест-кейсы"}],
        "pending_plan": {"actions": []},
        "pending_message": "Сделай тест-кейсы",
        "last_session_id": "session-1",
        "agent_context": {"session_id": "session-1"},
        "last_requirements": ["requirements.md"],
        "last_target_url": "https://example.com",
    }

    clear_chat_state(state)

    assert state["messages"] == []
    assert state["pending_plan"] is None
    assert state["pending_message"] == ""
    assert state["last_session_id"] == "session-1"
    assert state["agent_context"] == {"session_id": "session-1"}
    assert state["last_requirements"] == ["requirements.md"]
    assert state["last_target_url"] == "https://example.com"


def test_ai_action_without_api_key_does_not_call_runner() -> None:
    calls = []

    def runner(context: ChatContext, prompt: str):
        calls.append((context, prompt))
        raise AssertionError("runner must not be called")

    response, warning = run_validated_ai_action(
        ChatContext(requirements=["requirements.md"], target_url="https://example.com"),
        "Сделай тест-кейсы",
        has_api_key=False,
        ai_runner=runner,
    )

    assert response is None
    assert warning == MISSING_QUICK_ACTION_API_KEY_WARNING
    assert calls == []


def test_ai_action_without_generation_context_does_not_call_runner() -> None:
    calls = []

    def runner(context: ChatContext, prompt: str):
        calls.append((context, prompt))
        raise AssertionError("runner must not be called")

    response, warning = run_validated_ai_action(
        ChatContext(),
        "Сделай тест-кейсы",
        has_api_key=True,
        ai_runner=runner,
    )

    assert response is None
    assert warning == MISSING_QUICK_ACTION_CONTEXT_WARNING
    assert calls == []


def test_duplicate_warning_messages_are_not_added_to_history_twice() -> None:
    messages: list[dict[str, str]] = []

    assert remember_warning_once(messages, MISSING_QUICK_ACTION_API_KEY_WARNING) is True
    assert remember_warning_once(messages, MISSING_QUICK_ACTION_API_KEY_WARNING) is False
    assert messages == [{"role": "assistant", "content": MISSING_QUICK_ACTION_API_KEY_WARNING}]
