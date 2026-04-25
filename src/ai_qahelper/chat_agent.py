from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ai_qahelper.chat_executor import PlanExecutor, collect_artifacts
from ai_qahelper.chat_planner import ChatPlan, PlannerResult, plan_message

Intent = Literal[
    "agent_run",
    "generate_docs",
    "run_manual",
    "generate_autotests",
    "run_autotests",
    "draft_bugs",
    "sync_reports",
    "help",
    "unknown",
]


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


@dataclass
class ChatResponse:
    message: str
    intent: Intent = "unknown"
    needs_confirmation: bool = False
    plan: ChatPlan | None = None
    results: list[dict] = field(default_factory=list)
    warning: str = ""


def format_plan(plan: ChatPlan) -> str:
    if not plan.actions:
        return "План пуст."
    names = {
        "agent_run": "Анализ требований и базовая генерация",
        "generate_docs": "Генерация документации",
        "run_manual": "Шаблон ручного прогона",
        "generate_autotests": "Подготовка автотестов",
        "run_autotests": "Запуск автотестов",
        "draft_bugs": "Черновики баг-репортов",
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
    if plan is None:
        planner_result = plan_message(message, context, allow_llm=allow_llm)
        plan = planner_result.plan

    if plan.needs_clarification:
        return ChatResponse(plan.clarification_question or "Нужно уточнение перед выполнением.", "unknown", plan=plan)

    if plan.actions and plan.actions[0].type == "help":
        return ChatResponse(
            "Пишите обычным языком: `сделай тест-кейсы`, `сделай чек-лист`, "
            "`подготовь автотесты`, `запусти автотесты`, `создай баг-репорты`, `выгрузи в Google Sheets`.",
            "help",
            plan=plan,
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
        )

    warning = planner_result.warning if planner_result else ""
    try:
        results = (executor or PlanExecutor()).execute(context, plan, message)
    except Exception as exc:  # noqa: BLE001
        action_type = plan.actions[0].type if plan.actions else "unknown"
        return ChatResponse(f"Ошибка при выполнении `{action_type}`: {type(exc).__name__}: {exc}", action_type, plan=plan)

    lines: list[str] = []
    if warning:
        lines.append(warning)
        lines.append("")
    lines.append("Понял задачу. План:")
    lines.append(format_plan(plan))
    lines.append("")
    lines.append("Готово.")
    if context.session_id:
        lines.append(f"Session ID: `{context.session_id}`")
    artifacts = collect_artifacts(results)
    if artifacts:
        lines.append("Артефакты:")
        lines.extend(f"- {path}" for path in artifacts)
    if results:
        lines.append("")
        lines.append("Результаты шагов:")
        for idx, item in enumerate(results, start=1):
            title = item.get("title") or item.get("action") or f"Шаг {idx}"
            lines.append(f"{idx}. {title}: готово")

    return ChatResponse(
        "\n".join(lines),
        plan.actions[0].type if plan.actions else "unknown",
        plan=plan,
        results=results,
        warning=warning,
    )
