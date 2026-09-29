from __future__ import annotations

import inspect
from pathlib import Path

from ai_qahelper.chat_agent import ChatContext, handle_message
from ai_qahelper.chat_app import (
    MAIN_SCREEN_CAPTION,
    MISSING_API_KEY_MESSAGE,
    MISSING_TASK_API_KEY_WARNING,
    MISSING_TASK_CONTEXT_WARNING,
    SUPPORTED_UPLOAD_TYPES,
    TASK_FOCUS_OPTIONS,
    TASK_TYPES,
    _download_label,
    _load_coverage_report_for_ui,
    _render_task_launcher,
    _render_workflow_cards,
    build_task_prompt,
    clear_chat_state,
    remember_warning_once,
    run_validated_ai_action,
    should_remember_message,
    validate_task_run,
)
from ai_qahelper.chat_planner import ChatPlan, PlanAction


def test_supported_upload_types_include_word_and_excel() -> None:
    assert {"docx", "xlsx", "xls"}.issubset(SUPPORTED_UPLOAD_TYPES)


def test_download_labels_are_user_friendly() -> None:
    assert _download_label(Path("runs/s1/test-cases.xlsx")) == "Скачать test-cases.xlsx"
    assert _download_label(Path("runs/s1/checklist.xlsx")) == "Скачать checklist.xlsx"
    assert _download_label(Path("runs/s1/test-cases-quality-report.json")) == "Скачать quality report"
    assert _download_label(Path("runs/s1/coverage-report.json")) == "Скачать coverage report"
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


def test_task_launcher_options_are_professional() -> None:
    assert TASK_TYPES == (
        "Test cases",
        "Checklist",
        "Quality check",
        "Risk analysis",
        "Bug reports draft",
        "Autotests draft",
    )
    assert TASK_FOCUS_OPTIONS == (
        "General",
        "Smoke",
        "Negative",
        "Regression",
        "Boundary",
        "UI",
        "API",
        "Mobile",
        "Accessibility",
    )


def test_task_launcher_is_render_only_until_run_button() -> None:
    source = inspect.getsource(_render_workflow_cards)

    assert "QA Workflow" in source
    assert "Generate test cases" in source
    assert "Coverage report" in source
    assert "st.button" in source
    assert "st.selectbox" not in source
    assert "handle_message" not in source
    assert "run_ai_action" not in source
    assert "_render_task_launcher" in inspect.getsource(_render_task_launcher)


def test_build_task_prompt_for_test_cases_general() -> None:
    assert build_task_prompt("Test cases", "General", 30) == (
        "Сгенерируй test cases по текущему контексту с полным покрытием требований."
    )


def test_build_task_prompt_for_test_cases_smoke() -> None:
    assert build_task_prompt("Test cases", "Smoke", 10) == (
        "Сгенерируй smoke test cases по текущему контексту с полным покрытием требований."
    )


def test_build_task_prompt_for_test_cases_negative() -> None:
    assert build_task_prompt("Test cases", "Negative", 15) == (
        "Сгенерируй negative test cases по текущему контексту с полным покрытием требований."
    )


def test_build_task_prompt_for_checklist() -> None:
    assert build_task_prompt("Checklist", "General", 30) == (
        "Сгенерируй checklist по текущему контексту с полным покрытием требований."
    )


def test_task_launcher_no_longer_exposes_case_count() -> None:
    source = Path("src/ai_qahelper/chat_app.py").read_text(encoding="utf-8")

    assert "Количество проверок" not in source
    assert "Агент сам определяет объём документации" in source


def test_coverage_report_loader_reads_latest_report(monkeypatch, tmp_path: Path) -> None:
    report_path = tmp_path / "coverage-report.json"
    report_path.write_text('{"summary": {"requirements_total": 1}}', encoding="utf-8")
    monkeypatch.setattr(
        "ai_qahelper.chat_app.list_export_files",
        lambda session_id: [{"name": report_path.name, "path": str(report_path)}],
    )

    report = _load_coverage_report_for_ui("s1")

    assert report == {"summary": {"requirements_total": 1}}


def test_build_task_prompt_for_quality_check() -> None:
    assert build_task_prompt("Quality check", "General", 30) == "Проверь качество текущей тестовой документации."


def test_build_task_prompt_for_risk_analysis() -> None:
    assert build_task_prompt("Risk analysis", "General", 30) == "Найди риски, противоречия и серые зоны в требованиях."


def test_build_task_prompt_for_bug_reports_draft() -> None:
    assert build_task_prompt("Bug reports draft", "General", 30) == (
        "Создай черновики bug reports по текущей сессии и найденным проблемам."
    )


def test_build_task_prompt_for_autotests_draft() -> None:
    assert build_task_prompt("Autotests draft", "General", 30) == (
        "Подготовь Playwright/pytest автотесты по текущей сессии, но не запускай их."
    )


def test_should_remember_message_skips_duplicate_same_role_message() -> None:
    messages = [
        {"role": "user", "content": "Сделай тест-кейсы"},
        {"role": "assistant", "content": "Ок"},
    ]

    assert should_remember_message(messages, "user", "Сделай тест-кейсы") is False
    assert should_remember_message(messages, "assistant", "Ок") is False
    assert should_remember_message(messages, "user", "Сделай чек-лист") is True


def test_validate_task_run_without_api_key_returns_warning() -> None:
    warning = validate_task_run(
        ChatContext(requirements=["requirements.md"], target_url="https://example.com"),
        has_api_key=False,
    )

    assert warning == MISSING_TASK_API_KEY_WARNING


def test_validate_task_run_without_generation_context_returns_warning() -> None:
    warning = validate_task_run(ChatContext(), has_api_key=True)

    assert warning == MISSING_TASK_CONTEXT_WARNING


def test_validate_task_run_with_api_key_and_requirements_allows_message() -> None:
    warning = validate_task_run(ChatContext(requirements=["requirements.md"]), has_api_key=True)

    assert warning is None


def test_validate_task_run_with_api_key_and_target_url_allows_message() -> None:
    warning = validate_task_run(ChatContext(target_url="https://example.com"), has_api_key=True)

    assert warning is None


def test_validate_task_run_with_api_key_and_session_id_allows_message() -> None:
    warning = validate_task_run(ChatContext(session_id="session-1"), has_api_key=True)

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
    assert warning == MISSING_TASK_API_KEY_WARNING
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
    assert warning == MISSING_TASK_CONTEXT_WARNING
    assert calls == []


def test_ai_action_warning_is_not_added_to_chat_history() -> None:
    messages: list[dict[str, str]] = []

    response, warning = run_validated_ai_action(
        ChatContext(),
        "Сделай тест-кейсы",
        has_api_key=True,
        messages=messages,
    )

    assert response is None
    assert warning == MISSING_TASK_CONTEXT_WARNING
    assert messages == []


def test_duplicate_warning_messages_are_not_added_to_history_twice() -> None:
    messages: list[dict[str, str]] = []

    assert remember_warning_once(messages, MISSING_TASK_API_KEY_WARNING) is True
    assert remember_warning_once(messages, MISSING_TASK_API_KEY_WARNING) is False
    assert messages == [{"role": "assistant", "content": MISSING_TASK_API_KEY_WARNING}]
