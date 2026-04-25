from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_qahelper.config import load_config
from ai_qahelper.llm_client import LlmClient

ActionType = Literal[
    "agent_run",
    "generate_docs",
    "run_manual",
    "generate_autotests",
    "run_autotests",
    "draft_bugs",
    "sync_reports",
    "help",
]
ArtifactType = Literal["testcases", "checklist", "none"]
Focus = Literal[
    "smoke",
    "regression",
    "negative",
    "api",
    "ui",
    "mobile",
    "security",
    "performance",
    "accessibility",
    "general",
]

CONFIRMATION_ACTIONS: set[ActionType] = {"run_autotests", "sync_reports"}
SUPPORTED_ACTIONS: tuple[ActionType, ...] = (
    "agent_run",
    "generate_docs",
    "run_manual",
    "generate_autotests",
    "run_autotests",
    "draft_bugs",
    "sync_reports",
    "help",
)
SUPPORTED_FOCUS: tuple[Focus, ...] = (
    "smoke",
    "regression",
    "negative",
    "api",
    "ui",
    "mobile",
    "security",
    "performance",
    "accessibility",
    "general",
)


class PlanAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ActionType
    artifact_type: ArtifactType = "none"
    focus: Focus = "general"
    max_cases: int | None = None
    requires_confirmation: bool = False
    reason: str = ""

    @field_validator("max_cases")
    @classmethod
    def _positive_max_cases(cls, value: int | None) -> int | None:
        if value is None:
            return value
        return max(1, min(value, 200))


class ChatPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = ""
    needs_clarification: bool = False
    clarification_question: str = ""
    actions: list[PlanAction] = Field(default_factory=list)
    risks_to_analyze: list[str] = Field(default_factory=list)
    user_friendly_summary: str = ""


class PlannerResult(BaseModel):
    plan: ChatPlan
    used_fallback: bool = False
    warning: str = ""


PLANNER_SYSTEM_PROMPT = """
Ты AI QA Lead и test architect. Твоя задача — понять сообщение пользователя и вернуть строгий JSON-план.
Не выполняй задачу сам. Используй только поддерживаемые action types:
agent_run, generate_docs, run_manual, generate_autotests, run_autotests, draft_bugs, sync_reports, help.

Для каждого action верни поля:
type, artifact_type, focus, max_cases, requires_confirmation, reason.

artifact_type: testcases | checklist | none.
focus: smoke | regression | negative | api | ui | mobile | security | performance | accessibility | general.
Если не хватает обязательных данных, верни needs_clarification=true и clarification_question.
Если действие запускает браузер, меняет внешние таблицы или запускает автотесты — requires_confirmation=true.
Для run_autotests и sync_reports always requires_confirmation=true.

Верни только JSON без markdown.
""".strip()


@dataclass(frozen=True)
class FallbackActionRule:
    action_type: ActionType
    artifact_type: ArtifactType
    focus: Focus
    aliases: tuple[str, ...]
    reason: str
    blocked_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class FallbackSignals:
    wants_help: bool
    artifact_type: ArtifactType
    wants_docs: bool
    focuses: list[Focus]
    actions: list[PlanAction]


FALLBACK_ACTION_RULES: tuple[FallbackActionRule, ...] = (
    FallbackActionRule("sync_reports", "none", "general", ("выгруз", "google sheets", "таблиц", "sync"), "Пользователь просит выгрузить отчёты"),
    FallbackActionRule(
        "run_autotests",
        "none",
        "general",
        ("запусти автотест", "прогони автотест", "run autotest", "pytest"),
        "Пользователь просит запустить автотесты",
        blocked_by=("не запускай", "не запускать", "без запуска", "don't run", "do not run"),
    ),
    FallbackActionRule(
        "generate_autotests",
        "none",
        "general",
        ("автотест", "playwright", "pytest"),
        "Пользователь просит подготовить автотесты",
        blocked_by=("запусти автотест", "прогони автотест", "run autotest"),
    ),
    FallbackActionRule("run_manual", "none", "general", ("ручной прогон", "manual"), "Пользователь просит ручной прогон"),
    FallbackActionRule("draft_bugs", "none", "general", ("баг", "bug", "дефект"), "Пользователь просит подготовить баг-репорты"),
)

FALLBACK_DOC_ALIASES = (
    "требован",
    "риски",
    "риск",
    "противореч",
    "серые зоны",
    "тест-кейс",
    "test case",
    "suite",
    "провер",
    "документац",
    "шаблон",
)


def plan_message(
    user_message: str,
    context: Any,
    *,
    requirements: list[str] | None = None,
    requirement_urls: list[str] | None = None,
    target_url: str | None = None,
    session_id: str | None = None,
    output: str | None = None,
    max_cases: int | None = None,
    figma_file_key: str | None = None,
    test_cases_sheet_url: str | None = None,
    bug_reports_sheet_url: str | None = None,
    allow_llm: bool = True,
) -> PlannerResult:
    """Plan a chat message with LLM first and deterministic keyword fallback second."""

    effective_requirements = requirements if requirements is not None else list(getattr(context, "requirements", []) or [])
    effective_requirement_urls = (
        requirement_urls if requirement_urls is not None else list(getattr(context, "requirement_urls", []) or [])
    )
    effective_target_url = target_url if target_url is not None else getattr(context, "target_url", None)
    effective_session_id = session_id if session_id is not None else getattr(context, "session_id", None)
    effective_output = output if output is not None else getattr(context, "output", "testcases")
    effective_max_cases = max_cases if max_cases is not None else getattr(context, "max_cases", None)
    effective_figma_file_key = figma_file_key if figma_file_key is not None else getattr(context, "figma_file_key", None)
    effective_test_cases_sheet_url = (
        test_cases_sheet_url if test_cases_sheet_url is not None else getattr(context, "test_cases_sheet_url", None)
    )
    effective_bug_reports_sheet_url = (
        bug_reports_sheet_url if bug_reports_sheet_url is not None else getattr(context, "bug_reports_sheet_url", None)
    )

    if allow_llm:
        try:
            cfg = load_config()
            llm = LlmClient(cfg.llm)
            plan = llm.complete_json(
                PLANNER_SYSTEM_PROMPT,
                _build_user_prompt(
                    user_message,
                    requirements=effective_requirements,
                    requirement_urls=effective_requirement_urls,
                    target_url=effective_target_url,
                    session_id=effective_session_id,
                    output=effective_output,
                    max_cases=effective_max_cases,
                    figma_file_key=effective_figma_file_key,
                    test_cases_sheet_url=effective_test_cases_sheet_url,
                    bug_reports_sheet_url=effective_bug_reports_sheet_url,
                ),
                ChatPlan,
            )
            return PlannerResult(plan=_normalize_plan(plan, effective_output, effective_max_cases))
        except Exception as exc:  # noqa: BLE001 - planner must gracefully fall back for chat UX
            return PlannerResult(
                plan=fallback_plan_message(
                    user_message,
                    context,
                    requirements=effective_requirements,
                    requirement_urls=effective_requirement_urls,
                    target_url=effective_target_url,
                    session_id=effective_session_id,
                    output=effective_output,
                    max_cases=effective_max_cases,
                ),
                used_fallback=True,
                warning=f"LLM planner недоступен, использую базовое распознавание команд. ({type(exc).__name__})",
            )

    return PlannerResult(
        plan=fallback_plan_message(
            user_message,
            context,
            requirements=effective_requirements,
            requirement_urls=effective_requirement_urls,
            target_url=effective_target_url,
            session_id=effective_session_id,
            output=effective_output,
            max_cases=effective_max_cases,
        ),
        used_fallback=True,
        warning="LLM planner недоступен, использую базовое распознавание команд.",
    )


def _build_user_prompt(
    user_message: str,
    *,
    requirements: list[str],
    requirement_urls: list[str],
    target_url: str | None,
    session_id: str | None,
    output: str,
    max_cases: int | None,
    figma_file_key: str | None,
    test_cases_sheet_url: str | None,
    bug_reports_sheet_url: str | None,
) -> str:
    payload = {
        "user_message": user_message,
        "context": {
            "requirements": requirements,
            "requirement_urls": requirement_urls,
            "target_url": target_url,
            "session_id": session_id,
            "output": output,
            "max_cases": max_cases,
            "figma_file_key": figma_file_key,
            "test_cases_sheet_url": bool(test_cases_sheet_url),
            "bug_reports_sheet_url": bool(bug_reports_sheet_url),
        },
        "instructions": {
            "agent_run": "Use when a new session must be created from requirements and initial analysis/docs should run.",
            "generate_docs": "Use for additional testcases/checklist generation in a specific focus.",
            "draft_bugs": "Use when the user asks to prepare bug reports.",
            "generate_autotests": "Use when the user asks to prepare Playwright/pytest autotests but not run them.",
            "run_autotests": "Use only when the user explicitly asks to run autotests; requires confirmation.",
            "sync_reports": "Use only when the user asks to upload/sync to Google Sheets; requires confirmation.",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def fallback_plan_message(
    user_message: str,
    context: Any,
    *,
    requirements: list[str] | None = None,
    requirement_urls: list[str] | None = None,
    target_url: str | None = None,
    session_id: str | None = None,
    output: str | None = None,
    max_cases: int | None = None,
) -> ChatPlan:
    text = user_message.lower()
    effective_session_id = session_id if session_id is not None else getattr(context, "session_id", None)
    effective_output = output if output is not None else getattr(context, "output", "testcases")
    effective_max_cases = max_cases if max_cases is not None else getattr(context, "max_cases", None)
    signals = _collect_fallback_signals(text, effective_output)

    if signals.wants_help:
        return ChatPlan(
            goal="Показать справку по возможностям chat-agent",
            actions=[_action("help", "none", "general", None, "Пользователь просит помощь")],
            user_friendly_summary="Покажу, какие QA-действия можно запускать обычным языком.",
        )

    actions = list(signals.actions)
    if signals.wants_docs or signals.focuses:
        if not effective_session_id:
            first_focus = signals.focuses[0] if signals.artifact_type == "checklist" and signals.focuses else "general"
            actions.insert(
                0,
                _action(
                    "agent_run",
                    signals.artifact_type,
                    first_focus,
                    effective_max_cases,
                    "Создать базовую сессию и выполнить анализ требований",
                ),
            )
            for focus in signals.focuses:
                if focus != first_focus or focus in {"smoke", "negative", "regression"}:
                    actions.append(
                        _action(
                            "generate_docs",
                            signals.artifact_type,
                            focus,
                            _focus_max_cases(focus, effective_max_cases),
                            f"Пользователь просит {focus} проверки",
                        )
                    )
        else:
            focus_sequence = signals.focuses or ["general"]
            for focus in focus_sequence:
                actions.append(
                    _action(
                        "generate_docs",
                        signals.artifact_type,
                        focus,
                        _focus_max_cases(focus, effective_max_cases),
                        f"Пользователь просит обновить документацию: {focus}",
                    )
                )

    if not actions:
        actions.append(
            _action(
                "agent_run" if not effective_session_id else "generate_docs",
                signals.artifact_type,
                "general",
                effective_max_cases,
                "Базовое действие для QA-задачи пользователя",
            )
        )

    return _normalize_plan(
        ChatPlan(
            goal=_build_goal(actions),
            actions=_deduplicate_actions(actions),
            risks_to_analyze=_risks_for_message(text),
            user_friendly_summary=_summary_for_actions(actions),
        ),
        signals.artifact_type,
        effective_max_cases,
    )


def _normalize_plan(plan: ChatPlan, default_output: str | None, default_max_cases: int | None) -> ChatPlan:
    normalized: list[PlanAction] = []
    for action in plan.actions:
        artifact_type = action.artifact_type
        if action.type in {"agent_run", "generate_docs"} and artifact_type == "none":
            artifact_type = "checklist" if default_output == "checklist" else "testcases"
        if action.type not in {"agent_run", "generate_docs"}:
            artifact_type = "none"
        normalized.append(
            PlanAction(
                type=action.type,
                artifact_type=artifact_type,
                focus=action.focus,
                max_cases=action.max_cases if action.max_cases is not None else default_max_cases,
                requires_confirmation=action.requires_confirmation or action.type in CONFIRMATION_ACTIONS,
                reason=action.reason,
            )
        )
    plan.actions = _deduplicate_actions(normalized)
    return plan


def _action(
    action_type: ActionType,
    artifact_type: ArtifactType,
    focus: Focus,
    max_cases: int | None,
    reason: str,
) -> PlanAction:
    return PlanAction(
        type=action_type,
        artifact_type=artifact_type,
        focus=focus,
        max_cases=max_cases,
        requires_confirmation=action_type in CONFIRMATION_ACTIONS,
        reason=reason,
    )


def _has_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _collect_fallback_signals(text: str, output: str | None) -> FallbackSignals:
    artifact_type: ArtifactType = "checklist" if _wants_checklist(text, output) else "testcases"
    actions = [
        _action(rule.action_type, rule.artifact_type, rule.focus, None, rule.reason)
        for rule in FALLBACK_ACTION_RULES
        if _rule_matches(text, rule)
    ]
    focuses = _extract_focus_sequence(text)
    return FallbackSignals(
        wants_help=_has_any(text, "помощ", "help", "что умеешь"),
        artifact_type=artifact_type,
        wants_docs=_has_any(text, *FALLBACK_DOC_ALIASES) or artifact_type == "checklist",
        focuses=focuses,
        actions=actions,
    )


def _rule_matches(text: str, rule: FallbackActionRule) -> bool:
    return _has_any(text, *rule.aliases) and not _has_any(text, *rule.blocked_by)


def _wants_checklist(text: str, output: str | None) -> bool:
    return output == "checklist" or _has_any(text, "чек-лист", "чеклист", "checklist")


def _wants_docs(text: str) -> bool:
    return _has_any(text, *FALLBACK_DOC_ALIASES)


def _extract_focus_sequence(text: str) -> list[Focus]:
    patterns: list[tuple[Focus, tuple[str, ...]]] = [
        ("smoke", ("smoke", "смоук", "дым")),
        ("regression", ("regression", "регресс")),
        ("negative", ("negative", "негатив")),
        ("api", ("api", "апи")),
        ("ui", ("ui", "интерфейс", "ux")),
        ("mobile", ("mobile", "мобиль")),
        ("security", ("security", "безопас")),
        ("performance", ("performance", "нагруз", "производитель")),
        ("accessibility", ("accessibility", "a11y", "доступност")),
    ]
    found: list[tuple[int, Focus]] = []
    for focus, aliases in patterns:
        positions = [text.find(alias) for alias in aliases if alias in text]
        if positions:
            found.append((min(pos for pos in positions if pos >= 0), focus))
    ordered = [focus for _, focus in sorted(found, key=lambda item: item[0])]
    return list(dict.fromkeys(ordered))


def _focus_max_cases(focus: Focus, default: int | None) -> int | None:
    if default is not None:
        return default
    if focus == "smoke":
        return 10
    if focus == "negative":
        return 15
    return None


def _risks_for_message(text: str) -> list[str]:
    risks = ["неполные требования", "неясная валидация", "неописанные ошибки", "серые зоны UX"]
    if _has_any(text, "api", "апи"):
        risks.append("неописанные API-контракты")
    if _has_any(text, "mobile", "мобиль"):
        risks.append("различия платформ и экранов")
    if _has_any(text, "security", "безопас"):
        risks.append("неописанные ограничения доступа")
    return risks


def _build_goal(actions: list[PlanAction]) -> str:
    parts: list[str] = []
    for action in actions:
        if action.type == "agent_run":
            parts.append("анализ требований")
        elif action.type == "generate_docs":
            parts.append(f"{action.focus} {action.artifact_type}")
        elif action.type == "draft_bugs":
            parts.append("баг-репорты")
        elif action.type == "generate_autotests":
            parts.append("автотесты")
        elif action.type == "run_autotests":
            parts.append("запуск автотестов")
        elif action.type == "sync_reports":
            parts.append("выгрузку отчётов")
    return "Сделать " + ", ".join(parts) if parts else "Выполнить QA-задачу"


def _summary_for_actions(actions: list[PlanAction]) -> str:
    readable = {
        "agent_run": "проанализирую требования",
        "generate_docs": "подготовлю QA-документацию",
        "run_manual": "создам ручной прогон",
        "generate_autotests": "подготовлю автотесты",
        "run_autotests": "запущу автотесты после подтверждения",
        "draft_bugs": "подготовлю баг-репорты",
        "sync_reports": "выгружу отчёты после подтверждения",
        "help": "покажу справку",
    }
    seen: list[str] = []
    for action in actions:
        text = readable[action.type]
        if action.type == "generate_docs" and action.focus != "general":
            text = f"подготовлю {action.focus} проверки"
        if text not in seen:
            seen.append(text)
    return "Я " + ", затем ".join(seen) + "."


def _deduplicate_actions(actions: list[PlanAction]) -> list[PlanAction]:
    result: list[PlanAction] = []
    seen: set[tuple[str, str, str]] = set()
    for action in actions:
        key = (action.type, action.artifact_type, action.focus)
        if key in seen:
            continue
        seen.add(key)
        result.append(action)
    return result
