from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ai_qahelper.chat_executor import PlanExecutor, collect_artifact_paths
from ai_qahelper.chat_planner import ChatPlan, PlannerResult, plan_message
from ai_qahelper.friendly_errors import format_technical_error, format_user_error
from ai_qahelper.reporting import save_json
from ai_qahelper.session_service import session_path

Intent = Literal[
    "agent_run",
    "discover_site",
    "generate_docs",
    "run_manual",
    "generate_autotests",
    "run_autotests",
    "draft_bugs",
    "generate_bug_templates",
    "sync_reports",
    "help",
    "unknown",
]


@dataclass
class AgentMemory:
    last_requirements: list[str] = field(default_factory=list)
    target_url: str | None = None
    session_id: str | None = None
    last_artifact: str | None = None
    documentation_type: Literal["testcases", "checklist"] | None = None
    recent_user_actions: list[str] = field(default_factory=list)
    suggested_next_steps: list[str] = field(default_factory=list)
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict | None) -> "AgentMemory":
        if not data:
            return cls()
        return cls(
            last_requirements=list(data.get("last_requirements") or []),
            target_url=data.get("target_url"),
            session_id=data.get("session_id"),
            last_artifact=data.get("last_artifact"),
            documentation_type=data.get("documentation_type"),
            recent_user_actions=list(data.get("recent_user_actions") or [])[-10:],
            suggested_next_steps=list(data.get("suggested_next_steps") or []),
            updated_at=data.get("updated_at") or "",
        )

    def to_dict(self) -> dict:
        return {
            "last_requirements": self.last_requirements,
            "target_url": self.target_url,
            "session_id": self.session_id,
            "last_artifact": self.last_artifact,
            "documentation_type": self.documentation_type,
            "recent_user_actions": self.recent_user_actions[-10:],
            "suggested_next_steps": self.suggested_next_steps,
            "updated_at": self.updated_at,
        }


@dataclass
class ChatContext:
    requirements: list[str] = field(default_factory=list)
    requirement_urls: list[str] = field(default_factory=list)
    figma_file_key: str | None = None
    target_url: str | None = None
    session_id: str | None = None
    max_cases: int | None = None
    output: Literal["testcases", "checklist"] = "testcases"
    with_bug_drafts: bool = False
    skip_test_analysis: bool = False
    test_cases_sheet_url: str | None = None
    bug_reports_sheet_url: str | None = None
    site_discovery_max_pages: int = 5
    site_discovery_max_depth: int = 1
    site_discovery_same_domain_only: bool = True
    site_discovery_timeout_seconds: int = 20
    site_discovery_use_playwright: bool = True
    site_discovery_create_screenshots: bool = True
    agent_memory: AgentMemory = field(default_factory=AgentMemory)


@dataclass
class ChatResponse:
    message: str
    intent: Intent = "unknown"
    needs_confirmation: bool = False
    plan: ChatPlan | None = None
    results: list[dict] = field(default_factory=list)
    warning: str = ""
    summary_for_user: str = ""
    artifacts: list[str] = field(default_factory=list)
    suggested_next_steps: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    can_continue: bool = True
    technical_error: str = ""


def format_plan(plan: ChatPlan) -> str:
    if not plan.actions:
        return "План пуст."
    names = {
        "agent_run": "Анализ требований и базовая генерация",
        "discover_site": "Site discovery по фактическому поведению сайта",
        "generate_docs": "Генерация документации",
        "run_manual": "Шаблон ручного прогона",
        "generate_autotests": "Подготовка автотестов",
        "run_autotests": "Запуск автотестов",
        "draft_bugs": "Черновики баг-репортов",
        "generate_bug_templates": "Черновики баг-репортов по требованиям",
        "sync_reports": "Выгрузка в Google Sheets",
        "help": "Справка",
    }
    lines = []
    for idx, action in enumerate(plan.actions, start=1):
        suffix = ""
        if action.focus != "general":
            suffix += f" ({action.focus})"
        if action.artifact_type != "none":
            suffix += f" [{action.artifact_type}]"
        if action.requires_confirmation:
            suffix += " — требует подтверждения"
        lines.append(f"{idx}. {names[action.type]}{suffix}")
    return "\n".join(lines)


def handle_message(
    context: ChatContext,
    message: str,
    *,
    confirmed: bool = False,
    plan: ChatPlan | None = None,
    allow_llm: bool = True,
    executor: PlanExecutor | None = None,
) -> ChatResponse:
    planner_result: PlannerResult | None = None
    _hydrate_context_from_memory(context)
    _remember_user_action(context, message)
    if plan is None:
        update_context_from_message(context, message)
        planner_result = plan_message(message, context, allow_llm=allow_llm)
        plan = planner_result.plan

    if plan.needs_clarification:
        missing_inputs = _missing_inputs_for_clarification(plan.clarification_question)
        message_text = _format_clarification(plan.clarification_question, context)
        _update_agent_memory(context, [], [], missing_inputs=missing_inputs)
        return ChatResponse(
            message_text,
            "unknown",
            plan=plan,
            summary_for_user="Нужно уточнение перед выполнением.",
            missing_inputs=missing_inputs,
            suggested_next_steps=context.agent_memory.suggested_next_steps,
            can_continue=False,
        )

    if plan.actions and plan.actions[0].type == "help":
        suggested_next_steps = default_next_steps(context)
        _update_agent_memory(context, [], suggested_next_steps)
        return ChatResponse(
            "Пишите обычным языком: `сделай тест-кейсы`, `сделай чек-лист`, "
            "`подготовь автотесты`, `запусти автотесты`, `создай баг-репорты`, `выгрузи в Google Sheets`.",
            "help",
            plan=plan,
            summary_for_user="Показал справку по chat mode.",
            suggested_next_steps=suggested_next_steps,
        )

    if any(action.requires_confirmation for action in plan.actions) and not confirmed:
        warning = planner_result.warning if planner_result else ""
        prefix = (warning + "\n\n") if warning else ""
        return ChatResponse(
            prefix
            + "Понял задачу. План:\n"
            + format_plan(plan)
            + "\n\nНужно подтверждение перед выполнением опасных действий.",
            plan.actions[0].type if plan.actions else "unknown",
            needs_confirmation=True,
            plan=plan,
            warning=warning,
            summary_for_user="План готов, требуется подтверждение.",
            suggested_next_steps=["Подтвердить выполнение плана", "Изменить команду или параметры"],
            can_continue=True,
        )

    warning = planner_result.warning if planner_result else ""
    try:
        results = (executor or PlanExecutor()).execute(context, plan, message)
    except Exception as exc:  # noqa: BLE001
        action_type = plan.actions[0].type if plan.actions else "unknown"
        friendly = format_user_error(exc)
        missing_inputs = _missing_inputs_for_error(friendly)
        _update_agent_memory(context, [], [], missing_inputs=missing_inputs)
        return ChatResponse(
            friendly,
            action_type,
            plan=plan,
            summary_for_user="Действие не выполнено.",
            missing_inputs=missing_inputs,
            suggested_next_steps=context.agent_memory.suggested_next_steps,
            can_continue=bool(context.session_id),
            technical_error=format_technical_error(exc),
        )

    lines: list[str] = []
    if warning:
        lines.append(warning)
        lines.append("")
    lines.append("Понял задачу. План:")
    lines.append(format_plan(plan))
    lines.append("")
    artifacts = collect_artifact_paths(results)
    suggested_next_steps = suggest_next_steps(plan, results, context)
    summary_for_user = _build_summary_for_user(plan, results, context, artifacts)
    _update_agent_memory(context, results, suggested_next_steps)
    lines.append(summary_for_user)
    if context.session_id:
        lines.append(f"Session ID: `{context.session_id}`")
    if artifacts:
        lines.append("Артефакты:")
        lines.extend(f"- `{path}`" for path in artifacts)
    if results:
        lines.append("")
        lines.append("Результаты шагов:")
        for idx, item in enumerate(results, start=1):
            title = item.get("title") or item.get("action") or f"Шаг {idx}"
            lines.append(f"{idx}. {title}: готово")
    if any(action.type == "discover_site" for action in plan.actions):
        lines.append("")
        lines.append("Тест-кейсы созданы по фактическому поведению сайта, а не по требованиям.")
    if suggested_next_steps:
        lines.append("")
        lines.append("Что можно сделать дальше:")
        lines.extend(f"- {step}" for step in suggested_next_steps)

    return ChatResponse(
        "\n".join(lines),
        plan.actions[0].type if plan.actions else "unknown",
        plan=plan,
        results=results,
        warning=warning,
        summary_for_user=summary_for_user,
        artifacts=artifacts,
        suggested_next_steps=suggested_next_steps,
        can_continue=bool(context.session_id),
    )


def load_agent_memory(session_id: str) -> AgentMemory:
    try:
        path = session_path(session_id) / "agent_context.json"
        if not path.is_file():
            return AgentMemory(session_id=session_id)
        return AgentMemory.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - missing config/file should not break chat startup
        return AgentMemory(session_id=session_id)


def save_agent_memory(memory: AgentMemory) -> Path | None:
    if not memory.session_id:
        return None
    memory.updated_at = datetime.now(UTC).isoformat()
    try:
        path = session_path(memory.session_id) / "agent_context.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        save_json(path, memory.to_dict())
        return path
    except Exception:  # noqa: BLE001 - file persistence is best effort for chat UX
        return None


def suggest_next_steps(plan: ChatPlan, results: list[dict], context: ChatContext) -> list[str]:
    action_types = {action.type for action in plan.actions}
    artifact_types = {action.artifact_type for action in plan.actions}
    focus_types = {action.focus for action in plan.actions}
    artifacts = collect_artifact_paths(results)
    suggestions: list[str] = []
    if "testcases" in artifact_types and "negative" not in focus_types:
        suggestions.append("Сделать negative test cases")
    if "checklist" not in artifact_types:
        suggestions.append("Сделать чек-лист")
    if "generate_bug_templates" not in action_types and context.session_id:
        suggestions.append("Создать черновики баг-репортов")
    if "generate_autotests" not in action_types and context.session_id:
        suggestions.append("Подготовить Playwright/pytest автотесты")
    if any("quality-report" in artifact for artifact in artifacts):
        suggestions.append("Показать quality report")
    if context.test_cases_sheet_url or context.bug_reports_sheet_url:
        suggestions.append("Выгрузить в XLSX/Google Sheets")
    return _unique(suggestions or default_next_steps(context))[:4]


def default_next_steps(context: ChatContext) -> list[str]:
    if context.session_id:
        return [
            "Сделать negative test cases",
            "Сделать чек-лист",
            "Создать черновики баг-репортов",
            "Подготовить Playwright/pytest автотесты",
        ]
    return [
        "Загрузить требования",
        "Вставить target URL сайта",
        "Продолжить с текущей сессией, если есть Session ID",
    ]


def _hydrate_context_from_memory(context: ChatContext) -> None:
    memory = context.agent_memory
    if not context.requirements and memory.last_requirements:
        context.requirements = list(memory.last_requirements)
    if not context.target_url and memory.target_url:
        context.target_url = memory.target_url
    if not context.session_id and memory.session_id:
        context.session_id = memory.session_id
    if memory.documentation_type:
        context.output = memory.documentation_type


def _remember_user_action(context: ChatContext, message: str) -> None:
    cleaned = " ".join(message.strip().split())
    if not cleaned:
        return
    context.agent_memory.recent_user_actions = [*context.agent_memory.recent_user_actions, cleaned][-10:]


def _update_agent_memory(
    context: ChatContext,
    results: list[dict],
    suggested_next_steps: list[str],
    *,
    missing_inputs: list[str] | None = None,
) -> None:
    memory = context.agent_memory
    memory.last_requirements = list(context.requirements)
    memory.target_url = context.target_url
    memory.session_id = context.session_id
    memory.documentation_type = context.output
    artifacts = collect_artifact_paths(results)
    if artifacts:
        memory.last_artifact = artifacts[-1]
    memory.suggested_next_steps = suggested_next_steps or (
        _clarification_next_steps(missing_inputs or []) if missing_inputs else default_next_steps(context)
    )
    if memory.session_id:
        save_agent_memory(memory)


def _build_summary_for_user(
    plan: ChatPlan,
    results: list[dict],
    context: ChatContext,
    artifacts: list[str],
) -> str:
    if not results:
        return "Готово."
    action_titles = [item.get("title") or item.get("action") for item in results if item.get("title") or item.get("action")]
    summary = "Готово: " + ", ".join(action_titles) if action_titles else "Готово."
    counts = _result_counts(results)
    if counts:
        summary += " " + ", ".join(counts) + "."
    elif artifacts:
        summary += f" Создано файлов: {len(artifacts)}."
    if context.session_id and any(action.type == "agent_run" for action in plan.actions):
        summary += " Новая QA-сессия сохранена."
    return summary


def _result_counts(results: list[dict]) -> list[str]:
    counts: list[str] = []
    for result in results:
        summary = result.get("summary")
        if not isinstance(summary, dict):
            continue
        if summary.get("test_cases") is not None:
            counts.append(f"test cases: {summary['test_cases']}")
        if summary.get("checklist_items") is not None:
            counts.append(f"checklist items: {summary['checklist_items']}")
        for key in ("missing", "contradiction", "ambiguity"):
            if summary.get(key):
                counts.append(f"{key}: {summary[key]}")
    return _unique(counts)


def _format_clarification(question: str, context: ChatContext) -> str:
    base = question or "Нужно уточнение перед выполнением."
    if context.session_id:
        return f"{base}\n\nМогу продолжить с текущей сессией `{context.session_id}`."
    return (
        f"{base}\n\nМожно сделать одно из трёх:\n"
        "- загрузить requirements в боковой панели;\n"
        "- вставить target URL сайта для Site Discovery;\n"
        "- указать существующий Session ID, если нужно продолжить прошлую сессию."
    )


def _missing_inputs_for_clarification(question: str) -> list[str]:
    text = question.lower()
    missing: list[str] = []
    if "требован" in text or "requirements" in text:
        missing.append("requirements")
    if "target url" in text or "url" in text:
        missing.append("target_url")
    if "openai_api_key" in text or "api key" in text:
        missing.append("OPENAI_API_KEY")
    if not missing:
        missing.append("input")
    return missing


def _missing_inputs_for_error(error: str) -> list[str]:
    return _missing_inputs_for_clarification(error)


def _clarification_next_steps(missing_inputs: list[str]) -> list[str]:
    steps: list[str] = []
    if "requirements" in missing_inputs:
        steps.append("Загрузить требования")
    if "target_url" in missing_inputs:
        steps.append("Вставить target URL сайта")
    steps.append("Продолжить с текущей сессией, если есть Session ID")
    return _unique(steps)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


_URL_RE = re.compile(r"https?://[^\s)\],;!]+")
_FIGMA_KEY_RE = re.compile(r"figma\.com/(?:file|design)/([^/\s?]+)", re.IGNORECASE)
_MAX_CASES_RE = re.compile(
    r"(?:max[-_\s]?cases|максимум|до|ровно|сделай)\s*(\d+)|(\d+)\s*(?:тест[-_\s]?кейсов|кейсов|проверок|чек[-_\s]?лист)",
    re.IGNORECASE,
)


def update_context_from_message(context: ChatContext, message: str) -> None:
    urls = [_clean_url(url) for url in _URL_RE.findall(message)]
    if not urls:
        _extract_max_cases(context, message)
        return

    sheets = [url for url in urls if "docs.google.com/spreadsheets" in url.lower()]
    if sheets:
        context.test_cases_sheet_url = context.test_cases_sheet_url or sheets[0]
        if len(sheets) > 1:
            context.bug_reports_sheet_url = context.bug_reports_sheet_url or sheets[1]

    figma_match = _FIGMA_KEY_RE.search(message)
    if figma_match:
        context.figma_file_key = context.figma_file_key or figma_match.group(1)

    regular_urls = [
        url
        for url in urls
        if "figma.com" not in url.lower() and "docs.google.com/spreadsheets" not in url.lower()
    ]
    target_url = _detect_target_url(message, regular_urls)
    if target_url and not context.target_url:
        context.target_url = target_url
    for url in regular_urls:
        if url != context.target_url and url not in context.requirement_urls:
            context.requirement_urls.append(url)
    _extract_max_cases(context, message)


def _clean_url(url: str) -> str:
    return url.rstrip(".,;!?)\"]}")


def _extract_max_cases(context: ChatContext, message: str) -> None:
    match = _MAX_CASES_RE.search(message)
    if not match:
        return
    value = next((group for group in match.groups() if group), None)
    if value:
        context.max_cases = int(value)


def _detect_target_url(message: str, urls: list[str]) -> str | None:
    if not urls:
        return None
    lowered = message.lower()
    target_markers = ("target", "сайт", "стенд", "приложение", "url стенда", "target url")
    requirement_markers = ("требован", "requirement", "спека", "spec", "документ")
    for url in urls:
        before = lowered[: lowered.find(url.lower())]
        window = before[-60:]
        if any(marker in window for marker in target_markers):
            return url
    for url in urls:
        before = lowered[: lowered.find(url.lower())]
        window = before[-60:]
        if not any(marker in window for marker in requirement_markers):
            if len(urls) == 1:
                return url
    if len(urls) >= 2:
        return urls[-1]
    return None
