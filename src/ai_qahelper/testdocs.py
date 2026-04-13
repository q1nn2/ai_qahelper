from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from ai_qahelper.llm_client import LlmClient
from ai_qahelper.models import (
    AnalysisTechnique,
    AnalysisTestCondition,
    BugReport,
    LlmConfig,
    TestAnalysisReport,
    TestCase,
    TestCaseExportColumn,
    UnifiedRequirementModel,
)
from ai_qahelper.reporting import default_test_case_export_columns


class TestCaseList(BaseModel):
    test_cases: list[TestCase] = Field(default_factory=list)


class BugReportList(BaseModel):
    bug_reports: list[BugReport] = Field(default_factory=list)


class TestAnalysisRoot(BaseModel):
    test_analysis: TestAnalysisReport


def _normalize_bug_reports(raw_items: list[dict[str, Any]], max_items: int) -> list[BugReport]:
    """Normalize LLM output to strict BugReport schema with safe defaults."""
    items: list[BugReport] = []
    for i, raw in enumerate(raw_items[:max_items], start=1):
        bug_id = str(raw.get("bug_id") or "").strip() or f"BUG-{i:03d}"
        title = str(raw.get("title") or "").strip() or f"Черновик бага #{i}"
        preconditions = str(raw.get("preconditions") or "").strip() or "Открыт целевой стенд и доступна форма маршрута"
        steps_raw = raw.get("steps")
        if isinstance(steps_raw, list):
            steps = [str(s).strip() for s in steps_raw if str(s).strip()]
        else:
            steps = []
        if not steps:
            steps = ["Открыть страницу сервиса", "Выполнить действие согласно тест-кейсу", "Проверить фактический результат"]
        actual_result = str(raw.get("actual_result") or "").strip() or "Наблюдается некорректное поведение"
        expected_result = str(raw.get("expected_result") or "").strip() or "Поведение должно соответствовать требованиям"
        severity = str(raw.get("severity") or "").strip().lower()
        priority = str(raw.get("priority") or "").strip().lower()
        if severity not in {"minor", "major", "critical", "blocker"}:
            severity = "major"
        if priority not in {"low", "medium", "high", "urgent"}:
            priority = "medium"
        attachments_raw = raw.get("attachments")
        attachments = [str(a) for a in attachments_raw] if isinstance(attachments_raw, list) else []
        linked_test_case_id = raw.get("linked_test_case_id")
        items.append(
            BugReport(
                bug_id=bug_id,
                title=title,
                severity=severity,  # type: ignore[arg-type]
                priority=priority,  # type: ignore[arg-type]
                preconditions=preconditions,
                steps=steps,
                actual_result=actual_result,
                expected_result=expected_result,
                attachments=attachments,
                linked_test_case_id=str(linked_test_case_id) if linked_test_case_id else None,
            )
        )
    return items


def _model_digest_for_prompt(model: UnifiedRequirementModel, max_chars_per_source: int) -> str:
    data = model.model_dump(mode="json")
    if max_chars_per_source > 0:
        for req in data.get("requirements", []):
            content = req.get("content") or ""
            if len(content) > max_chars_per_source:
                req["content"] = (
                    content[:max_chars_per_source]
                    + "\n\n[TRUNCATED: source is longer; base cases on the text above and standard flows.]\n"
                )
    return json.dumps(data, ensure_ascii=False, indent=2)


def _export_template_hint(export_columns: list[TestCaseExportColumn] | None) -> str:
    cols = export_columns if export_columns else default_test_case_export_columns()
    mapping = "; ".join(f"{c.field} → колонка «{c.header}»" for c in cols)
    return (
        "Тестовая документация для исполнителя на русском. Поля JSON должны соответствовать выгрузке в таблицу: "
        f"{mapping}. "
        "Колонки «Окружение», «Статус», «ID баг-репорта» в JSON всегда пустые строки — их заполняет исполнитель. "
        "Человекочитаемые поля заполняй так, чтобы их можно было скопировать в шаблон без доработок."
    )


def _clear_executor_columns(tc: TestCase) -> TestCase:
    """Колонки шаблона «Окружение», «Статус», «ID баг-репорта» — для ручного заполнения исполнителем."""
    return tc.model_copy(update={"environment": "", "status": "", "bug_report_id": ""})


def _analysis_digest_for_prompt(report: TestAnalysisReport, max_chars: int) -> str:
    raw = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if max_chars <= 0 or len(raw) <= max_chars:
        return raw
    return (
        raw[:max_chars]
        + "\n\n[TRUNCATED: test analysis JSON was shortened for the case-generation prompt.]\n"
    )


def fallback_test_analysis(
    model: UnifiedRequirementModel,
    consistency_report: dict[str, Any] | None,
) -> TestAnalysisReport:
    """Минимальный отчёт без LLM (ошибка анализа или пустой ввод)."""
    sources: list[str] = [r.source for r in model.requirements]
    if model.design:
        sources.append(f"figma:{model.design.file_key}")
    sources.append("consistency-report")
    risks: list[str] = []
    if consistency_report:
        for f in (consistency_report.get("findings") or [])[:15]:
            t = f.get("type", "")
            r = f.get("reason") or f.get("requirement") or ""
            if r:
                risks.append(f"[{t}] {str(r)[:200]}")
    inv: list[str] = []
    if not model.requirements and not model.design:
        inv.append("Требования и макет не переданы — анализ ограничен URL стенда.")
    return TestAnalysisReport(
        scope=f"Веб-сервис по адресу {model.target_url}",
        assumptions="Автоматический резервный анализ без ответа LLM.",
        sources_used=sources,
        risks_and_gaps=risks or ["Нет данных отчёта консистентности или требований."],
        inventory=inv,
        techniques=[
            AnalysisTechnique(
                id="TECH-FB",
                name="Резервный режим",
                rationale="Полный тест-анализ недоступен; кейсы строить по unified model.",
            )
        ],
        test_conditions=[],
    )


def generate_test_analysis(
    llm: LlmClient,
    model: UnifiedRequirementModel,
    consistency_report: dict[str, Any] | None,
    *,
    llm_cfg: LlmConfig,
) -> TestAnalysisReport:
    system = (
        "You are a senior QA analyst. Reply with a single JSON object only — no markdown fences, no extra text. "
        "Top-level key must be \"test_analysis\" (object). "
        "All human-readable string values inside test_analysis MUST be in Russian (scope, assumptions, lists of "
        "strings, technique names and rationales, condition descriptions, requirement_ref). "
        "IDs (technique id, condition id, technique_id references) use Latin: TECH-01, COND-01, etc. "
        "Do NOT invent UI fields, validation rules, or addresses that are not present in the unified model or "
        "consistency findings. If documentation is thin, state gaps in risks_and_gaps and keep inventory minimal. "
        "You MUST apply several test-design techniques where relevant, for example: "
        "equivalence partitioning, boundary value analysis, decision table, pairwise combinations, state/transition "
        "for modes, negative cases. List each applied technique under \"techniques\" with id, name, rationale. "
        "Under \"test_conditions\" list concrete check conditions with unique COND-xx ids, each linked to a "
        "technique_id and requirement_ref (quote or section hint from sources). "
        "Use consistency findings to populate risks_and_gaps (ambiguity, missing design coverage, contradictions)."
    )
    user = (
        "Проведи тест-анализ по следующим данным. "
        "sources_used — перечисли явно: пути/URL требований, наличие Figma (file_key), отчёт консистентности, target_url.\n"
        "inventory — функции, поля формы, правила валидации, режимы UI, всё строго из текста требований/описания дизайна.\n"
        f"Consistency (subset):\n{_consistency_digest_for_prompt(consistency_report, llm_cfg.max_consistency_findings)}\n"
        f"Unified model:\n{_model_digest_for_prompt(model, llm_cfg.max_requirement_chars_per_source)}"
    )
    payload = llm.complete_json(system, user, TestAnalysisRoot)
    return payload.test_analysis


def _consistency_digest_for_prompt(consistency_report: dict[str, Any] | None, max_findings: int) -> str:
    if not consistency_report:
        return "{}"
    findings = consistency_report.get("findings") or []
    slim: dict[str, Any] = {"summary": consistency_report.get("summary", {})}
    if max_findings > 0:
        slim["findings"] = findings[:max_findings]
        if len(findings) > max_findings:
            slim["truncated_findings_note"] = f"{len(findings) - max_findings} more findings omitted"
    else:
        slim["findings"] = findings
    return json.dumps(slim, ensure_ascii=False, indent=2)


def generate_test_cases(
    llm: LlmClient,
    model: UnifiedRequirementModel,
    consistency_report: dict[str, Any] | None = None,
    max_cases: int = 30,
    *,
    llm_cfg: LlmConfig,
    export_columns: list[TestCaseExportColumn] | None = None,
    analysis: TestAnalysisReport | None = None,
) -> list[TestCase]:
    class Payload(BaseModel):
        test_cases: list[TestCase]

    system = (
        "You are a senior QA engineer. "
        "You MUST respond with a single JSON object only — no markdown fences, no text before or after. "
        "The JSON must have exactly one top-level key: \"test_cases\" (array of objects). "
        "Do not include bug reports or any keys other than test_cases. "
        "Each object uses keys: case_id, title, preconditions, steps (array of strings), expected_result, "
        "environment, status, bug_report_id, note, source_refs (array of strings). "
        "LANGUAGE: All human-readable fields MUST be in Russian: title, preconditions, every step string, "
        "expected_result, note. Use Russian UI strings from requirements (кнопки, подписи полей, тексты ошибок). "
        "Only case_id may stay Latin like TC-001 or T1. "
        "CRITICAL: environment, status, and bug_report_id MUST each be the empty string \"\" — "
        "these columns are filled by the human executor later; do not put URLs or draft/passed there. "
        "Put the stand URL in preconditions if needed (e.g. «Открыть сервис … [URL]»). "
        "Steps must be concrete and executable (имена полей, значения, ожидаемые сообщения на русском)."
    )
    if analysis is not None and analysis.test_conditions:
        system += (
            " A test analysis with test_conditions (COND-xx) was provided. Each test case MUST reference at least one "
            "condition id: include every applicable COND-xx in source_refs AND start the note field with "
            "\"Условия: COND-01, COND-02\" (example) listing those ids. Prefer covering diverse techniques from the "
            "analysis; do not duplicate the same condition across all cases if others exist."
        )

    user_parts = [
        f"Сгенерируй ровно {max_cases} различных тест-кейсов (не меньше и не больше).",
        "Все формулировки для исполнителя — на русском языке.",
        "Поля environment, status и bug_report_id оставь пустыми строками \"\" (шаблон под ручное заполнение).",
        "URL стенда при необходимости укажи в предусловиях, не в environment.",
    ]
    if analysis is not None:
        user_parts.append(
            "Тест-анализ (JSON):\n"
            + _analysis_digest_for_prompt(analysis, llm_cfg.max_analysis_json_chars)
        )
        if analysis.test_conditions:
            user_parts.append(
                "Опирайся на тест-анализ: каждый кейс проверяет хотя бы одно условие из test_conditions; "
                "в source_refs укажи COND-xx и при необходимости путь к файлу требований."
            )
        else:
            user_parts.append(
                "В анализе нет списка test_conditions — сформируй кейсы по inventory, рискам и unified model; "
                "в source_refs укажи пути к источникам."
            )
    else:
        user_parts.append(
            "Покрывай валидацию, основные сценарии и граничные случаи по возможности по unified model."
        )
        user_parts.append(
            "source_refs: пути к источникам или намёк на раздел из unified model."
        )

    user_parts.append(_export_template_hint(export_columns))
    user_parts.append(
        "Consistency (subset):\n"
        + _consistency_digest_for_prompt(consistency_report, llm_cfg.max_consistency_findings)
    )
    user_parts.append(
        "Unified model:\n" + _model_digest_for_prompt(model, llm_cfg.max_requirement_chars_per_source)
    )
    user = "\n".join(user_parts)
    payload = llm.complete_json(system, user, Payload, root_list_key="test_cases")
    return [_clear_executor_columns(tc) for tc in payload.test_cases[:max_cases]]


def generate_bug_report_templates(
    llm: LlmClient,
    test_cases: list[TestCase],
    max_items: int = 20,
) -> list[BugReport]:
    class Payload(BaseModel):
        bug_reports: list[dict[str, Any]]

    system = (
        "You are QA lead. Reply with a single JSON object only — no markdown. "
        "Top-level key must be \"bug_reports\" (array). "
        "All narrative fields (title, preconditions, steps, actual_result, expected_result) MUST be in Russian."
    )
    user = (
        f"Сгенерируй до {max_items} правдоподобных черновиков баг-репортов по этим тест-кейсам. "
        "Не придумывай невозможные сценарии. Всё на русском.\n"
        f"{json.dumps([c.model_dump() for c in test_cases], ensure_ascii=False)}"
    )
    payload = llm.complete_json(system, user, Payload, root_list_key="bug_reports")
    return _normalize_bug_reports(payload.bug_reports, max_items)


def fallback_test_cases(model: UnifiedRequirementModel, max_cases: int = 30) -> list[TestCase]:
    items: list[TestCase] = []
    base_steps = [
        f"Открыть в браузере URL: {model.target_url}",
        "Убедиться, что страница загрузилась без ошибок",
        "Проверить по требованиям видимость ключевых элементов интерфейса",
    ]
    cap = max(1, min(max_cases, 50))
    for i, req in enumerate(model.requirements[:cap], start=1):
        figma_ref = f"figma:{model.design.file_key}" if model.design else None
        refs = [req.source]
        if figma_ref:
            refs.append(figma_ref)
        items.append(
            TestCase(
                case_id=f"TC-{i:03d}",
                title=f"Покрытие требований: {req.source}",
                preconditions="Приложение доступно, пользователь на странице сервиса",
                steps=base_steps + [f"Сверить фрагмент требований: {req.content[:120]}"],
                expected_result="Поведение соответствует описанным требованиям",
                environment="",
                status="",
                bug_report_id="",
                note="Черновик без ответа LLM (резервный режим)",
                source_refs=refs,
            )
        )
    return items
