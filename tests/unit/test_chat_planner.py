from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ai_qahelper.chat_agent import (
    AgentMemory,
    ChatContext,
    handle_message,
    load_agent_memory,
    save_agent_memory,
    update_context_from_message,
)
from ai_qahelper.chat_executor import PlanExecutor
from ai_qahelper.chat_planner import ChatPlan, PlanAction, plan_message
from ai_qahelper.models import BugReport, ChecklistItem
from ai_qahelper.models import TestCase as QaTestCase
from ai_qahelper.reporting import export_bug_reports_local, export_checklist_local, export_test_cases_local


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
    assert "generate_bug_templates" in action_types


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


def test_message_links_update_context_before_planning() -> None:
    context = ChatContext()

    update_context_from_message(
        context,
        "Вот требования https://docs.example.com/spec.md вот сайт https://app.example.com сделай smoke и negative до 7 кейсов",
    )

    assert context.requirement_urls == ["https://docs.example.com/spec.md"]
    assert context.target_url == "https://app.example.com"
    assert context.max_cases == 7


def test_missing_requirements_and_session_asks_clarification() -> None:
    context = ChatContext(target_url="https://app.example.com")

    response = handle_message(context, "сделай тест-кейсы", allow_llm=False)

    assert response.plan is not None
    assert response.plan.needs_clarification is True
    assert "Загрузи требования" in response.message
    assert "requirements" in response.missing_inputs
    assert response.can_continue is False


def test_missing_all_inputs_returns_friendly_options() -> None:
    response = handle_message(ChatContext(), "сделай тест-кейсы", allow_llm=False)

    assert response.plan is not None
    assert response.plan.needs_clarification is True
    assert "загрузить requirements" in response.message
    assert {"requirements", "target_url"}.issubset(set(response.missing_inputs))
    assert response.suggested_next_steps


def test_chat_response_contains_agent_fields(monkeypatch) -> None:
    class FakeExecutor:
        def execute(self, context, plan, user_message=""):
            context.session_id = "s1"
            context.output = "testcases"
            return [
                {
                    "session_id": "s1",
                    "title": "Smoke testcases",
                    "test_cases_path": "runs/s1/test-cases.json",
                    "summary": {"test_cases": 3},
                }
            ]

    monkeypatch.setattr("ai_qahelper.chat_agent.save_agent_memory", lambda memory: None)
    plan = ChatPlan(actions=[PlanAction(type="generate_docs", artifact_type="testcases", focus="smoke")])

    response = handle_message(ChatContext(session_id="s1"), "сделай smoke", plan=plan, executor=FakeExecutor())

    assert response.summary_for_user
    assert response.artifacts == ["runs/s1/test-cases.json"]
    assert "Сделать negative test cases" in response.suggested_next_steps
    assert response.missing_inputs == []
    assert response.can_continue is True


def test_agent_memory_persists_to_session_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ai_qahelper.chat_agent.session_path", lambda session_id: tmp_path / "runs" / session_id)
    memory = AgentMemory(
        last_requirements=["requirements.md"],
        target_url="https://example.com",
        session_id="s1",
        last_artifact="runs/s1/test-cases.json",
        documentation_type="testcases",
        recent_user_actions=["сделай тест-кейсы"],
        suggested_next_steps=["Сделать чек-лист"],
    )

    path = save_agent_memory(memory)
    loaded = load_agent_memory("s1")

    assert path == tmp_path / "runs" / "s1" / "agent_context.json"
    assert loaded.session_id == "s1"
    assert loaded.last_requirements == ["requirements.md"]
    assert loaded.suggested_next_steps == ["Сделать чек-лист"]


def test_continue_uses_agent_memory_session(monkeypatch) -> None:
    class FakeExecutor:
        def execute(self, context, plan, user_message=""):
            assert context.session_id == "s1"
            return [{"session_id": "s1", "title": "testcases", "test_cases_path": "runs/s1/test-cases.json"}]

    monkeypatch.setattr("ai_qahelper.chat_agent.save_agent_memory", lambda memory: None)
    context = ChatContext(agent_memory=AgentMemory(session_id="s1", documentation_type="testcases"))

    response = handle_message(context, "продолжай", allow_llm=False, executor=FakeExecutor())

    assert response.plan is not None
    assert response.plan.actions[0].type == "generate_docs"
    assert context.session_id == "s1"
    assert response.can_continue is True


def test_site_discovery_message_creates_discover_plan() -> None:
    context = ChatContext(target_url="https://example.com")

    result = plan_message(
        "Требований нет, проанализируй сайт https://example.com и напиши тест-кейсы",
        context,
        allow_llm=False,
    )

    assert result.plan.needs_clarification is False
    assert [action.type for action in result.plan.actions[:2]] == ["discover_site", "generate_docs"]
    assert result.plan.actions[1].artifact_type == "testcases"
    assert result.plan.actions[1].focus == "general"


def test_site_discovery_does_not_ask_for_requirements() -> None:
    context = ChatContext(target_url="https://example.com")

    result = plan_message("Нет требований, посмотри сайт и составь тест-кейсы по сайту", context, allow_llm=False)

    assert result.plan.needs_clarification is False
    assert "discover_site" in _action_types(result)


def test_site_discovery_without_target_url_asks_clarification() -> None:
    context = ChatContext()

    result = plan_message("Требований нет, проанализируй сайт и напиши тест-кейсы", context, allow_llm=False)

    assert result.plan.needs_clarification is True
    assert "target URL" in result.plan.clarification_question


def test_site_discovery_smoke_plan() -> None:
    context = ChatContext(target_url="https://example.com")

    result = plan_message(
        "Требований нет, пройди по сайту https://example.com и сделай smoke тесты",
        context,
        allow_llm=False,
    )

    assert [action.type for action in result.plan.actions[:2]] == ["discover_site", "generate_docs"]
    assert result.plan.actions[1].focus == "smoke"


def test_site_discovery_accessibility_plan() -> None:
    context = ChatContext(target_url="https://example.com")

    result = plan_message(
        "Проверь сайт без требований и проверь accessibility basics",
        context,
        allow_llm=False,
    )

    assert [action.type for action in result.plan.actions[:2]] == ["discover_site", "generate_docs"]
    assert result.plan.actions[1].focus == "accessibility"


def test_prepare_bugs_without_auto_results_generates_bug_templates(monkeypatch) -> None:
    calls: list[str] = []

    class FakeState:
        auto_results_path = None

        def model_dump(self, mode: str = "json") -> dict:
            return {"session_id": "s1", "bug_reports_path": "runs/s1/bug-reports.json"}

    monkeypatch.setattr("ai_qahelper.chat_executor.load_session", lambda session_id: FakeState())

    def _fake_generate_bug_templates(session_id: str):
        calls.append(session_id)
        return FakeState()

    monkeypatch.setattr("ai_qahelper.chat_executor.generate_bug_templates_for_session", _fake_generate_bug_templates)

    response = handle_message(ChatContext(session_id="s1"), "подготовь баги", allow_llm=False)

    assert response.results[0]["bug_reports_path"] == "runs/s1/bug-reports.json"
    assert calls == ["s1"]


def test_focus_exports_create_distinct_filenames(tmp_path: Path) -> None:
    test_cases = [
        QaTestCase(
            case_id="TC-001",
            title="Smoke",
            preconditions="Open app",
            steps=["Open page"],
            expected_result="Page is open",
        )
    ]
    checklist = [
        ChecklistItem(
            item_id="CL-001",
            check="Open app",
            expected_result="App opens",
        )
    ]
    bugs = [
        BugReport(
            bug_id="BUG-001",
            title="Bug",
            preconditions="Open app",
            steps=["Open page"],
            actual_result="Error",
            expected_result="No error",
        )
    ]

    smoke_csv, smoke_xlsx = export_test_cases_local(tmp_path, test_cases, filename_prefix="test-cases-smoke")
    negative_csv, negative_xlsx = export_test_cases_local(tmp_path, test_cases, filename_prefix="test-cases-negative")
    checklist_csv, checklist_xlsx = export_checklist_local(tmp_path, checklist, filename_prefix="checklist-smoke")
    bugs_csv, bugs_xlsx = export_bug_reports_local(tmp_path, bugs, filename_prefix="bug-reports-negative")

    for path in [smoke_csv, smoke_xlsx, negative_csv, negative_xlsx, checklist_csv, checklist_xlsx, bugs_csv, bugs_xlsx]:
        assert path.is_file()
    assert smoke_csv.name == "test-cases-smoke.csv"
    assert negative_xlsx.name == "test-cases-negative.xlsx"


def test_llm_planner_success_uses_mock_client(monkeypatch) -> None:
    class FakeLlmClient:
        def __init__(self, cfg) -> None:
            self.cfg = cfg

        def complete_json(self, system_prompt, user_prompt, schema):
            return ChatPlan(
                goal="Smoke",
                actions=[
                    PlanAction(
                        type="generate_docs",
                        artifact_type="testcases",
                        focus="smoke",
                        reason="LLM planned smoke checks",
                    )
                ],
            )

    monkeypatch.setattr("ai_qahelper.chat_planner.load_config", lambda: SimpleNamespace(llm=SimpleNamespace()))
    monkeypatch.setattr("ai_qahelper.chat_planner.LlmClient", FakeLlmClient)

    result = plan_message("сделай smoke", ChatContext(session_id="s1"))

    assert result.used_fallback is False
    assert result.plan.actions[0].type == "generate_docs"
    assert result.plan.actions[0].focus == "smoke"


def test_executor_runs_agent_then_smoke_then_negative(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    class FakeState:
        def __init__(self, session_id: str, test_cases_path: str) -> None:
            self.session_id = session_id
            self.test_cases_path = test_cases_path

        def model_dump(self, mode: str = "json") -> dict:
            return {"session_id": self.session_id, "test_cases_path": self.test_cases_path}

    def _fake_agent_run(*args, **kwargs):
        calls.append(("agent_run", kwargs.get("artifact_type")))
        return {"session_id": "s1", "test_cases_path": "runs/s1/test-cases.json"}

    def _fake_generate_docs(session_id: str, **kwargs):
        calls.append(("generate_docs", kwargs.get("focus")))
        return FakeState(session_id, f"runs/{session_id}/test-cases-{kwargs.get('focus')}.json")

    monkeypatch.setattr("ai_qahelper.chat_executor.agent_run", _fake_agent_run)
    monkeypatch.setattr("ai_qahelper.chat_executor.generate_docs", _fake_generate_docs)

    plan = ChatPlan(
        actions=[
            PlanAction(type="agent_run", artifact_type="testcases", focus="general"),
            PlanAction(type="generate_docs", artifact_type="testcases", focus="smoke"),
            PlanAction(type="generate_docs", artifact_type="testcases", focus="negative"),
        ]
    )
    context = ChatContext(requirements=["req.md"], target_url="https://app.example.com")

    results = PlanExecutor().execute(context, plan)

    assert context.session_id == "s1"
    assert calls == [("agent_run", "testcases"), ("generate_docs", "smoke"), ("generate_docs", "negative")]
    assert results[-1]["test_cases_path"] == "runs/s1/test-cases-negative.json"


def test_executor_discover_site_updates_session_id(monkeypatch) -> None:
    class FakeState:
        def model_dump(self, mode: str = "json") -> dict:
            return {
                "session_id": "site-s1",
                "site_model_path": "runs/site-s1/site-model.json",
                "exploratory_report_path": "runs/site-s1/exploratory-report.json",
                "unified_model_path": "runs/site-s1/unified-model.json",
            }

    monkeypatch.setattr("ai_qahelper.chat_executor.discover_site", lambda target_url, **kwargs: FakeState())

    plan = ChatPlan(actions=[PlanAction(type="discover_site")])
    context = ChatContext(target_url="https://example.com")

    results = PlanExecutor().execute(context, plan)

    assert context.session_id == "site-s1"
    assert results[0]["site_model_path"] == "runs/site-s1/site-model.json"
    assert results[0]["exploratory_report_path"] == "runs/site-s1/exploratory-report.json"


def test_executor_can_generate_docs_after_discover_site(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    class FakeDiscoveryState:
        def model_dump(self, mode: str = "json") -> dict:
            return {
                "session_id": "site-s1",
                "site_model_path": "runs/site-s1/site-model.json",
                "exploratory_report_path": "runs/site-s1/exploratory-report.json",
                "unified_model_path": "runs/site-s1/unified-model.json",
            }

    class FakeDocsState:
        def model_dump(self, mode: str = "json") -> dict:
            return {
                "session_id": "site-s1",
                "test_cases_path": "runs/site-s1/test-cases-ui.json",
            }

    def _fake_discover_site(target_url: str, **kwargs):
        calls.append(("discover_site", target_url))
        return FakeDiscoveryState()

    def _fake_generate_docs(session_id: str, **kwargs):
        calls.append(("generate_docs", kwargs.get("focus")))
        return FakeDocsState()

    monkeypatch.setattr("ai_qahelper.chat_executor.discover_site", _fake_discover_site)
    monkeypatch.setattr("ai_qahelper.chat_executor.generate_docs", _fake_generate_docs)

    plan = ChatPlan(
        actions=[
            PlanAction(type="discover_site"),
            PlanAction(type="generate_docs", artifact_type="testcases", focus="ui"),
        ]
    )
    context = ChatContext(target_url="https://example.com")

    results = PlanExecutor().execute(context, plan)

    assert context.session_id == "site-s1"
    assert calls == [("discover_site", "https://example.com"), ("generate_docs", "ui")]
    assert results[-1]["test_cases_path"] == "runs/site-s1/test-cases-ui.json"
