from __future__ import annotations

from ai_qahelper.chat_agent import ChatContext, handle_message
from ai_qahelper.chat_planner import plan_message


def _action_types(result) -> list[str]:
    return [action.type for action in result.plan.actions]


def test_complex_risk_smoke_negative_bugs_plan() -> None:
    context = ChatContext(requirements=["requirements.md"], target_url="https://example.com")

    result = plan_message(
        "Посмотри требования, найди риски, сначала сделай smoke, потом negative cases, потом подготовь баги",
        context,
        allow_llm=False,
    )

    action_types = _action_types(result)
    assert "agent_run" in action_types or "generate_docs" in action_types
    assert any(action.type == "generate_docs" and action.focus == "smoke" for action in result.plan.actions)
    assert any(action.type == "generate_docs" and action.focus == "negative" for action in result.plan.actions)
    assert "draft_bugs" in action_types


def test_run_autotests_requires_confirmation() -> None:
    context = ChatContext(session_id="demo-session")

    result = plan_message("Запусти автотесты", context, allow_llm=False)

    assert any(action.type == "run_autotests" and action.requires_confirmation for action in result.plan.actions)


def test_sync_reports_requires_confirmation() -> None:
    context = ChatContext(session_id="demo-session")

    result = plan_message("Выгрузи отчёты в Google Sheets", context, allow_llm=False)

    assert any(action.type == "sync_reports" and action.requires_confirmation for action in result.plan.actions)


def test_mobile_checklist_and_negative_plan() -> None:
    context = ChatContext(requirements=["requirements.md"], target_url="https://example.com")

    result = plan_message(
        "Сделай чек-лист для мобильного приложения и отдельно негативные проверки",
        context,
        allow_llm=False,
    )

    assert any(action.artifact_type == "checklist" for action in result.plan.actions)
    assert any(action.focus in {"mobile", "negative"} for action in result.plan.actions)


def test_llm_planner_failure_uses_keyword_fallback(monkeypatch) -> None:
    def _raise_config_error():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr("ai_qahelper.chat_planner.load_config", _raise_config_error)
    context = ChatContext(requirements=["requirements.md"], target_url="https://example.com")

    result = plan_message("Запусти автотесты", context)

    assert result.used_fallback is True
    assert "LLM planner недоступен" in result.warning
    assert any(action.type == "run_autotests" for action in result.plan.actions)


def test_chat_agent_returns_confirmation_for_dangerous_plan() -> None:
    context = ChatContext(session_id="demo-session")

    response = handle_message(context, "Запусти автотесты", allow_llm=False)

    assert response.needs_confirmation is True
    assert response.plan is not None
    assert any(action.type == "run_autotests" for action in response.plan.actions)
