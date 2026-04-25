from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_qahelper.chat_planner import ChatPlan, PlanAction
from ai_qahelper.orchestrator import (
    agent_run,
    create_bug_drafts_from_failures,
    discover_site,
    generate_autotests,
    generate_bug_templates_for_session,
    generate_docs,
    run_autotests,
    run_manual,
    sync_reports,
)
from ai_qahelper.session_service import load_session


class PlanExecutor:
    """Executes an already validated JSON plan. It does not infer user intent."""

    def execute(self, context: Any, plan: ChatPlan, user_message: str = "") -> list[dict]:
        results: list[dict] = []
        for action in plan.actions:
            data = self.execute_action(context, action, user_message)
            if data:
                if data.get("session_id"):
                    context.session_id = data["session_id"]
                results.append(data)
        return results

    def execute_action(self, context: Any, action: PlanAction, user_message: str = "") -> dict:
        handler = _ACTION_HANDLERS[action.type]
        return handler(context, action, user_message)


def collect_artifacts(results: list[dict]) -> list[str]:
    keys = [
        "unified_model_path",
        "input_coverage_report_path",
        "consistency_report_path",
        "test_analysis_path",
        "quality_report_path",
        "site_model_path",
        "exploratory_report_path",
        "exploratory_report_md_path",
        "checklist_path",
        "test_cases_path",
        "dedup_report_path",
        "bug_reports_path",
        "generated_tests_dir",
        "manual_results_path",
        "auto_results_path",
        "junit_report_path",
        "html_report_path",
    ]
    artifacts: list[str] = []
    for result in results:
        for key in keys:
            value = result.get(key)
            if value and value not in artifacts:
                artifacts.append(f"`{value}`")
    return artifacts


def _handle_help(context: Any, action: PlanAction, user_message: str) -> dict:
    return {"action": action.type, "title": "Справка"}


def _handle_agent_run(context: Any, action: PlanAction, user_message: str) -> dict:
    artifact_type = "checklist" if action.artifact_type == "checklist" else "testcases"
    context.output = artifact_type
    requirements = context.requirements
    requirement_urls = context.requirement_urls
    if not requirements and not requirement_urls:
        raise ValueError("Загрузи требования или вставь текст требований.")
    if not context.target_url:
        raise ValueError("Укажи target URL для новой сессии.")
    data = agent_run(
        requirements,
        requirement_urls,
        context.figma_file_key,
        target_url=context.target_url,
        max_cases=action.max_cases or context.max_cases,
        with_bug_drafts=context.with_bug_drafts,
        skip_test_analysis=True if context.skip_test_analysis else None,
        artifact_type=artifact_type,
    )
    data["action"] = action.type
    data["title"] = _action_title(action)
    return data


def _handle_discover_site(context: Any, action: PlanAction, user_message: str) -> dict:
    if not context.target_url:
        raise ValueError("Укажи target URL для site discovery.")
    state = discover_site(
        context.target_url,
        max_pages=getattr(context, "site_discovery_max_pages", 5),
        same_domain_only=getattr(context, "site_discovery_same_domain_only", True),
        max_depth=getattr(context, "site_discovery_max_depth", 1),
        timeout_seconds=getattr(context, "site_discovery_timeout_seconds", 20),
        use_playwright=getattr(context, "site_discovery_use_playwright", True),
        create_screenshots=getattr(context, "site_discovery_create_screenshots", True),
    )
    data = state.model_dump(mode="json")
    site_model_path = data.get("site_model_path")
    if site_model_path and Path(site_model_path).is_file():
        data["summary"] = json.loads(Path(site_model_path).read_text(encoding="utf-8")).get("summary", {})
    data["action"] = action.type
    data["title"] = _action_title(action)
    return data


def _handle_generate_docs(context: Any, action: PlanAction, user_message: str) -> dict:
    _require_session(context)
    artifact_type = "checklist" if action.artifact_type == "checklist" else "testcases"
    context.output = artifact_type
    state = generate_docs(
        context.session_id,
        max_cases=action.max_cases or context.max_cases,
        generate_bug_templates=True if context.with_bug_drafts else None,
        skip_test_analysis=True if context.skip_test_analysis else None,
        artifact_type=artifact_type,
        focus=action.focus,
    )
    data = state.model_dump(mode="json")
    data["action"] = action.type
    data["title"] = _action_title(action)
    return data


def _handle_run_manual(context: Any, action: PlanAction, user_message: str) -> dict:
    _require_session(context)
    state = run_manual(context.session_id)
    data = state.model_dump(mode="json")
    data["action"] = action.type
    data["title"] = _action_title(action)
    return data


def _handle_generate_autotests(context: Any, action: PlanAction, user_message: str) -> dict:
    _require_session(context)
    state = generate_autotests(context.session_id)
    data = state.model_dump(mode="json")
    data["action"] = action.type
    data["title"] = _action_title(action)
    return data


def _handle_run_autotests(context: Any, action: PlanAction, user_message: str) -> dict:
    _require_session(context)
    state = run_autotests(context.session_id)
    data = state.model_dump(mode="json")
    data["action"] = action.type
    data["title"] = _action_title(action)
    return data


def _handle_draft_bugs(context: Any, action: PlanAction, user_message: str) -> dict:
    _require_session(context)
    current_state = load_session(context.session_id)
    if current_state.auto_results_path:
        state = create_bug_drafts_from_failures(context.session_id)
    else:
        state = generate_bug_templates_for_session(context.session_id)
    data = state.model_dump(mode="json")
    data["action"] = action.type
    data["title"] = _action_title(action)
    return data


def _handle_generate_bug_templates(context: Any, action: PlanAction, user_message: str) -> dict:
    _require_session(context)
    state = generate_bug_templates_for_session(context.session_id)
    data = state.model_dump(mode="json")
    data["action"] = action.type
    data["title"] = _action_title(action)
    return data


def _handle_sync_reports(context: Any, action: PlanAction, user_message: str) -> dict:
    _require_session(context)
    if not context.test_cases_sheet_url or not context.bug_reports_sheet_url:
        raise ValueError("Добавьте ссылки Google Sheets в боковой панели и повторите команду.")
    data = sync_reports(context.session_id, context.test_cases_sheet_url, context.bug_reports_sheet_url)
    data["action"] = action.type
    data["title"] = _action_title(action)
    return data


_ACTION_HANDLERS = {
    "agent_run": _handle_agent_run,
    "discover_site": _handle_discover_site,
    "generate_docs": _handle_generate_docs,
    "run_manual": _handle_run_manual,
    "generate_autotests": _handle_generate_autotests,
    "run_autotests": _handle_run_autotests,
    "draft_bugs": _handle_draft_bugs,
    "generate_bug_templates": _handle_generate_bug_templates,
    "sync_reports": _handle_sync_reports,
    "help": _handle_help,
}


def _require_session(context: Any) -> None:
    if not context.session_id:
        raise ValueError("Сначала создайте сессию: загрузите требования и попросите сделать анализ или тест-кейсы.")


def _action_title(action: PlanAction) -> str:
    if action.type == "agent_run":
        return "Анализ требований"
    if action.type == "discover_site":
        return "Site discovery"
    if action.type == "generate_docs":
        if action.focus != "general":
            return f"{action.focus} {action.artifact_type}"
        return action.artifact_type
    titles = {
        "draft_bugs": "Баг-репорты",
        "generate_bug_templates": "Черновики баг-репортов",
        "generate_autotests": "Автотесты подготовлены",
        "run_autotests": "Автотесты запущены",
        "sync_reports": "Google Sheets",
        "run_manual": "Ручной прогон",
        "help": "Справка",
    }
    return titles.get(action.type, action.type)
