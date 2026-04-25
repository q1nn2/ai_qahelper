from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ai_qahelper.orchestrator import (
    agent_run,
    create_bug_drafts_from_failures,
    generate_autotests,
    generate_docs,
    run_autotests,
    run_manual,
    sync_reports,
)

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


def detect_intent(message: str) -> Intent:
    text = message.lower()
    if any(x in text for x in ("помощ", "help", "что умеешь")):
        return "help"
    if any(x in text for x in ("выгруз", "google sheets", "таблиц")):
        return "sync_reports"
    if any(x in text for x in ("баг", "bug", "дефект")):
        return "draft_bugs"
    if any(x in text for x in ("запусти автотест", "прогони автотест", "pytest", "run-autotest")):
        return "run_autotests"
    if any(x in text for x in ("автотест", "playwright")):
        return "generate_autotests"
    if any(x in text for x in ("ручной прогон", "manual")):
        return "run_manual"
    if any(x in text for x in ("обнови", "перегенер", "generate-docs")):
        return "generate_docs"
    if any(x in text for x in ("тест-кейс", "тест кейс", "чек-лист", "чеклист", "тестовую документац", "сделай тест")):
        return "agent_run"
    return "unknown"


def format_state(data: dict) -> str:
    names = {
        "session_id": "Сессия",
        "test_cases_path": "Тест-кейсы",
        "checklist_path": "Чек-лист",
        "test_analysis_path": "Тест-анализ",
        "consistency_report_path": "Consistency report",
        "bug_reports_path": "Баг-репорты",
        "generated_tests_dir": "Автотесты",
        "manual_results_path": "Ручной прогон",
        "auto_results_path": "Результаты автотестов",
        "html_report_path": "HTML-отчёт",
    }
    lines: list[str] = []
    for key, title in names.items():
        value = data.get(key)
        if value:
            lines.append(f"- {title}: `{value}`")
    summary = data.get("summary")
    if summary:
        lines.append("- Сводка: " + ", ".join(f"{k}: {v}" for k, v in summary.items()))
    return "\n".join(lines)


def handle_message(context: ChatContext, message: str, *, confirmed: bool = False) -> ChatResponse:
    intent = detect_intent(message)
    if intent == "help":
        return ChatResponse(
            "Пишите обычным языком: `сделай тест-кейсы`, `сделай чек-лист`, "
            "`подготовь автотесты`, `запусти автотесты`, `создай баг-репорты`, `выгрузи в Google Sheets`.",
            intent,
        )
    if intent == "unknown":
        return ChatResponse("Не понял действие. Напишите, например: `сделай тест-кейсы` или `запусти автотесты`.", intent)

    try:
        if intent == "agent_run":
            if "чек" in message.lower():
                context.output = "checklist"
            data = agent_run(
                context.requirements,
                context.requirement_urls,
                context.figma_file_key,
                target_url=context.target_url,
                max_cases=context.max_cases,
                with_bug_drafts=context.with_bug_drafts,
                skip_test_analysis=True if context.skip_test_analysis else None,
                artifact_type=context.output,
            )
            context.session_id = data.get("session_id")
            return ChatResponse("Готово.\n\n" + format_state(data), intent)

        if not context.session_id:
            return ChatResponse("Сначала создайте сессию: загрузите требования и напишите `сделай тест-кейсы`.", intent)

        if intent == "generate_docs":
            state = generate_docs(context.session_id, max_cases=context.max_cases, artifact_type=context.output)
            return ChatResponse("Документация обновлена.\n\n" + format_state(state.model_dump(mode="json")), intent)
        if intent == "run_manual":
            state = run_manual(context.session_id)
            return ChatResponse("Шаблон ручного прогона создан.\n\n" + format_state(state.model_dump(mode="json")), intent)
        if intent == "generate_autotests":
            state = generate_autotests(context.session_id)
            return ChatResponse("Автотесты подготовлены.\n\n" + format_state(state.model_dump(mode="json")), intent)
        if intent == "run_autotests":
            if not confirmed:
                return ChatResponse("Подтвердите запуск автотестов кнопкой ниже.", intent, needs_confirmation=True)
            state = run_autotests(context.session_id)
            return ChatResponse("Автотесты запущены.\n\n" + format_state(state.model_dump(mode="json")), intent)
        if intent == "draft_bugs":
            state = create_bug_drafts_from_failures(context.session_id)
            return ChatResponse("Баг-репорты созданы.\n\n" + format_state(state.model_dump(mode="json")), intent)
        if intent == "sync_reports":
            if not context.test_cases_sheet_url or not context.bug_reports_sheet_url:
                return ChatResponse("Добавьте ссылки Google Sheets в боковой панели и повторите команду.", intent)
            if not confirmed:
                return ChatResponse("Подтвердите выгрузку в Google Sheets кнопкой ниже.", intent, needs_confirmation=True)
            data = sync_reports(context.session_id, context.test_cases_sheet_url, context.bug_reports_sheet_url)
            return ChatResponse("Выгрузка завершена.\n\n" + format_state(data), intent)
    except Exception as exc:  # noqa: BLE001
        return ChatResponse(f"Ошибка при выполнении `{intent}`: {type(exc).__name__}: {exc}", intent)

    return ChatResponse("Действие пока не поддерживается.", intent)
