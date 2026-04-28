from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from ai_qahelper.llm_client import LlmClient
from ai_qahelper.models import (
    AnalysisTechnique,
    BugReport,
    ChecklistItem,
    LlmConfig,
    TestAnalysisReport,
    TestCase,
    TestCaseExportColumn,
    UnifiedRequirementModel,
)
from ai_qahelper.reporting import default_test_case_export_columns
from ai_qahelper.template_service import DocumentationTemplate, build_template_prompt_hint


class TestCaseList(BaseModel):
    test_cases: list[TestCase] = Field(default_factory=list)


class ChecklistList(BaseModel):
    checklist: list[ChecklistItem] = Field(default_factory=list)


class BugReportList(BaseModel):
    bug_reports: list[BugReport] = Field(default_factory=list)


class TestAnalysisRoot(BaseModel):
    test_analysis: TestAnalysisReport


def _normalize_bug_reports(raw_items: list[dict[str, Any]], max_items: int) -> list[BugReport]:
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


def _normalize_checklist(items: list[ChecklistItem]) -> list[ChecklistItem]:
    normalized: list[ChecklistItem] = []
    for idx, item in enumerate(items, start=1):
        item_id = item.item_id.strip() or f"CL-{idx:03d}"
        area = item.area.strip()
        check = item.check.strip()
        expected = item.expected_result.strip()
        if not check:
            check = f"Проверка по требованию #{idx}"
        if not expected:
            expected = "Поведение соответствует требованиям"
        normalized.append(
            item.model_copy(
                update={
                    "item_id": item_id,
                    "area": area,
                    "check": check,
                    "expected_result": expected,
                }
            )
        )
    return normalized


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


def _export_template_hint(
    export_columns: list[TestCaseExportColumn] | None,
    template: DocumentationTemplate | None = None,
) -> str:
    if template is not None:
        return build_template_prompt_hint(template)
    cols = export_columns if export_columns else default_test_case_export_columns()
    mapping = "; ".join(f"{c.field} → колонка «{c.header}»" for c in cols)
    return (
        "Тестовая документация для исполнителя на русском. Поля JSON должны соответствовать выгрузке в таблицу: "
        f"{mapping}. "
        "Колонки «Окружение», «Статус», «ID баг-репорта» в JSON всегда пустые строки — их заполняет исполнитель. "
        "Человекочитаемые поля заполняй так, чтобы их можно было скопировать в шаблон без доработок."
    )


def _clear_executor_columns(tc: TestCase) -> TestCase:
    return tc.model_copy(update={"environment": "", "status": "", "bug_report_id": ""})


def _analysis_digest_for_prompt(report: TestAnalysisReport, max_chars: int) -> str:
    raw = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if max_chars <= 0 or len(raw) <= max_chars:
        return raw
    return raw[:max_chars] + "\n\n[TRUNCATED: test analysis JSON was shortened for the generation prompt.]\n"


def fallback_test_analysis(
    model: UnifiedRequirementModel,
    consistency_report: dict[str, Any] | None,
) -> TestAnalysisReport:
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
                rationale="Полный тест-анализ недоступен; документацию строить по unified model.",
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
        "All human-readable string values inside test_analysis MUST be in Russian. "
        "IDs (technique id, condition id, technique_id references) use Latin: TECH-01, COND-01, etc. "
        "Do NOT invent UI fields, validation rules, or addresses that are not present in the unified model or consistency findings. "
        "If documentation is thin, state gaps in risks_and_gaps and keep inventory minimal. "
        "Apply several test-design techniques where relevant: equivalence partitioning, boundary value analysis, decision table, pairwise, state/transition, negative cases. "
        "List each applied technique under \"techniques\" with id, name, rationale. "
        "Under \"test_conditions\" list concrete atomic check conditions with unique COND-xx ids."
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


def _focus_instruction(focus: str) -> str:
    hints = {
        "smoke": "Фокус: smoke. Покрой только критический happy path и базовую доступность основных функций.",
        "regression": "Фокус: regression. Покрой основные устойчивые сценарии, которые важно повторять перед релизом.",
        "negative": "Фокус: negative. Делай упор на ошибки, невалидные данные, пустые поля и отказные сценарии.",
        "api": "Фокус: API. Проверяй контракты, статусы ответов, обязательные параметры и обработку ошибок API.",
        "ui": "Фокус: UI. Проверяй отображение, состояния элементов, тексты, навигацию и UX-серые зоны.",
        "mobile": "Фокус: mobile. Учитывай мобильные экраны, адаптивность, touch-сценарии и платформенные различия.",
        "security": "Фокус: security. Проверяй доступы, приватность данных, некорректные права и безопасную обработку ввода.",
        "performance": "Фокус: performance. Проверяй скорость, задержки, тяжёлые сценарии и деградацию под нагрузкой.",
        "accessibility": "Фокус: accessibility. Проверяй клавиатурную навигацию, labels, контрастность и screen reader сценарии.",
    }
    return hints.get(focus, "Фокус: general. Покрой требования сбалансированно.")


_BAD_QA_PHRASES = (
    "Запрещённые общие формулировки: «проверить корректность», «работает корректно», "
    "«работает правильно», «система работает», «данные обрабатываются корректно», "
    "«отображается корректно», «проверить функциональность», «всё работает», "
    "«ошибка отображается» без причины/места/условия, «проверить UI» без конкретного элемента."
)


def generate_checklist(
    llm: LlmClient,
    model: UnifiedRequirementModel,
    consistency_report: dict[str, Any] | None = None,
    max_items: int | None = None,
    *,
    llm_cfg: LlmConfig,
    analysis: TestAnalysisReport | None = None,
    focus: str = "general",
    template: DocumentationTemplate | None = None,
) -> list[ChecklistItem]:
    template_keys = (
        ", ".join(column.key for column in template.columns if column.enabled or column.required)
        if template is not None
        else "item_id, area, check, expected_result, priority, note, source_refs"
    )
    system = (
        "You are a senior QA engineer. Reply with a single JSON object only. "
        "Top-level key must be \"checklist\" (array). "
        f"Each checklist item must use keys: {template_keys}. "
        "All human-readable fields must be in Russian. "
        "Checklist is concise: each item is one check line, not a detailed step-by-step test case. "
        "Keep items professional, executable, atomic, and grounded only in provided requirements and analysis. "
        "Each checklist item is exactly one concrete check with one observable expected_result and source_refs. "
        "Never use vague QA filler phrases."
    )
    user_parts = [
        "Сначала проанализируй требования и test_conditions, затем создай столько пунктов чек-листа, сколько необходимо для полного покрытия.",
        "Не используй искусственное фиксированное количество пунктов и не создавай дубли.",
        "Один пункт = одна конкретная проверка одного элемента/правила/состояния. Не превращай чек-лист в пошаговый тест-кейс.",
        "Покрой все функции, правила валидации, основные UI-состояния, негативные проверки и граничные значения, если они есть в требованиях.",
        "Если требование невозможно покрыть из-за недостатка информации, явно укажи gap/risk в note.",
        "В check — краткая формулировка проверки для исполнителя. В expected_result — конкретный наблюдаемый итог этой проверки.",
        "Расставь priority по важности: low / medium / high / critical.",
        "Каждый item должен иметь source_refs. Если данных не хватает, укажи gap/risk в note, не придумывай правило.",
        "Expected_result должен описывать наблюдаемый результат: кнопка активна/неактивна, сообщение отображается, поле подсвечено, пользователь остаётся на странице или перенаправляется.",
        "Пример хорошего item: check=\"Проверить, что кнопка 'Войти' неактивна при пустом обязательном поле Email\"; expected_result=\"Кнопка 'Войти' остаётся неактивной, пока обязательное поле Email пустое\".",
        "Плохой item: «Проверить корректность авторизации».",
        _BAD_QA_PHRASES,
    ]
    if template is not None:
        user_parts.append(build_template_prompt_hint(template))
    if focus != "general":
        user_parts.append(_focus_instruction(focus))
    if analysis is not None:
        user_parts.append("Тест-анализ (JSON):\n" + _analysis_digest_for_prompt(analysis, llm_cfg.max_analysis_json_chars))
        if analysis.test_conditions:
            user_parts.append(
                "Опирайся на test_conditions. В source_refs указывай COND-xx и источник требований там, где это уместно."
            )
    else:
        user_parts.append("Если тест-анализ отсутствует, выведи пункты из unified model и consistency report.")
    user_parts.append(
        "Consistency (subset):\n" + _consistency_digest_for_prompt(consistency_report, llm_cfg.max_consistency_findings)
    )
    user_parts.append("Unified model:\n" + _model_digest_for_prompt(model, llm_cfg.max_requirement_chars_per_source))
    payload = llm.complete_json(system, "\n".join(user_parts), ChecklistList, root_list_key="checklist")
    return _normalize_checklist(payload.checklist)


def generate_test_cases(
    llm: LlmClient,
    model: UnifiedRequirementModel,
    consistency_report: dict[str, Any] | None = None,
    max_cases: int | None = None,
    *,
    llm_cfg: LlmConfig,
    export_columns: list[TestCaseExportColumn] | None = None,
    analysis: TestAnalysisReport | None = None,
    focus: str = "general",
    template: DocumentationTemplate | None = None,
    coverage_gap_report: dict[str, Any] | None = None,
) -> list[TestCase]:
    class Payload(BaseModel):
        test_cases: list[TestCase]

    template_keys = (
        ", ".join(column.key for column in template.columns if column.enabled or column.required)
        if template is not None
        else "case_id, title, preconditions, steps, expected_result, environment, status, bug_report_id, note, source_refs"
    )
    system = (
        "You are a senior QA engineer. "
        "You MUST respond with a single JSON object only — no markdown fences, no text before or after. "
        "The JSON must have exactly one top-level key: \"test_cases\" (array of objects). "
        f"Each object uses keys: {template_keys}. "
        "All human-readable fields MUST be in Russian. "
        "environment, status, and bug_report_id MUST be empty strings. "
        "Steps must be concrete, executable, and atomic. One test case = one verification. "
        "Every test case must be understandable for manual execution and suitable for future automation. "
        "Do not invent business rules that are absent from requirements, site model, analysis, or consistency findings. "
        "Stop only when all requirements and test_conditions are covered."
    )
    if analysis is not None and analysis.test_conditions:
        system += (
            " Each test case MUST reference exactly one primary condition in source_refs and start note with \"Условия: COND-xx\"."
        )

    user_parts = [
        "Сначала проанализируй требования и разбей их на атомарные test conditions.",
        "Сгенерируй столько тест-кейсов, сколько необходимо для полного покрытия всех требований, test_conditions, позитивных, негативных и граничных сценариев.",
        "Не используй искусственное фиксированное количество и не создавай дубли.",
        "Строгий QA-standard: каждый кейс проверяет одну конкретную вещь (одно значение, одно правило, одно сообщение, одно состояние) — не склеивай проверки.",
        "Название должно содержать конкретный объект проверки, не «Проверка формы» и не «Проверка функциональности».",
        "Предусловия должны быть конкретными: где находится пользователь, какое состояние/данные уже подготовлены.",
        "Шаги должны быть конкретными и исполнимыми. Если есть ввод, укажи конкретные тестовые данные.",
        "Expected_result должен быть наблюдаемым: кнопка активна/неактивна, сообщение отображается, пользователь остаётся на странице, пользователь перенаправляется, поле подсвечивается, значение сохраняется, API-запрос завершается конкретным статусом, если API описан.",
        "Если точный текст ошибки неизвестен, пиши: «отображается сообщение об ошибке о причине невалидного значения», не выдумывай точную строку.",
        "Для negative cases указывай конкретное невалидное значение. Для boundary cases указывай конкретную границу только если она есть в требованиях.",
        "Если данных не хватает — добавляй gap/risk в note, а не придумывай правило.",
        "Каждый кейс должен иметь source_refs: ссылку на требование, файл, URL или COND-xx.",
        "Для Site Discovery case в note укажи, что кейс основан на фактически найденном UI, а не на продуктовых требованиях.",
        _BAD_QA_PHRASES,
        "Все формулировки для исполнителя — на русском языке.",
        "Поля environment, status и bug_report_id оставь пустыми строками \"\".",
        "URL стенда при необходимости укажи в предусловиях, не в environment.",
    ]
    if focus != "general":
        user_parts.append(_focus_instruction(focus))
    if analysis is not None:
        user_parts.append("Тест-анализ (JSON):\n" + _analysis_digest_for_prompt(analysis, llm_cfg.max_analysis_json_chars))
        if analysis.test_conditions:
            user_parts.append(
                "Опирайся на тест-анализ: каждый кейс проверяет хотя бы одно условие из test_conditions; в source_refs укажи COND-xx и источник."
            )
        else:
            user_parts.append(
                "В анализе нет списка test_conditions — сформируй кейсы по inventory, рискам и unified model; в source_refs укажи пути к источникам."
            )
    else:
        user_parts.append("Покрывай валидацию, основные сценарии и граничные случаи по unified model.")
        user_parts.append("source_refs: пути к источникам или намёк на раздел из unified model.")
    if coverage_gap_report is not None:
        user_parts.append(
            "Coverage gaps после дедупликации (сгенерируй только недостающие проверки, не повторяй уже покрытые):\n"
            + json.dumps(coverage_gap_report, ensure_ascii=False, indent=2)
        )

    user_parts.append(_export_template_hint(export_columns, template))
    user_parts.append("Consistency (subset):\n" + _consistency_digest_for_prompt(consistency_report, llm_cfg.max_consistency_findings))
    user_parts.append("Unified model:\n" + _model_digest_for_prompt(model, llm_cfg.max_requirement_chars_per_source))
    payload = llm.complete_json(system, "\n".join(user_parts), Payload, root_list_key="test_cases")
    return [_clear_executor_columns(tc) for tc in payload.test_cases]


def generate_bug_report_templates(
    llm: LlmClient,
    test_cases: list[TestCase],
    max_items: int = 20,
    template: DocumentationTemplate | None = None,
) -> list[BugReport]:
    class Payload(BaseModel):
        bug_reports: list[dict[str, Any]]

    system = (
        "You are QA lead. Reply with a single JSON object only — no markdown. "
        "Top-level key must be \"bug_reports\" (array). "
        "All narrative fields MUST be in Russian."
    )
    user_parts = [
        f"Сгенерируй до {max_items} правдоподобных черновиков баг-репортов по этим тест-кейсам.",
        "Не придумывай невозможные сценарии. Всё на русском.",
    ]
    if template is not None:
        user_parts.append(build_template_prompt_hint(template))
    user_parts.append(json.dumps([c.model_dump() for c in test_cases], ensure_ascii=False))
    user = "\n".join(user_parts)
    payload = llm.complete_json(system, user, Payload, root_list_key="bug_reports")
    return _normalize_bug_reports(payload.bug_reports, max_items)


def fallback_checklist(model: UnifiedRequirementModel, max_items: int | None = None) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    for idx, req in enumerate(model.requirements, start=1):
        refs = [req.source]
        if model.design:
            refs.append(f"figma:{model.design.file_key}")
        items.append(
            ChecklistItem(
                item_id=f"CL-{idx:03d}",
                area="Требования",
                check=f"Проверить реализацию требований из источника {req.source}",
                expected_result="Поведение соответствует описанным требованиям",
                priority="medium",
                note="Черновик без ответа LLM (резервный режим)",
                source_refs=refs,
            )
        )
    if not items:
        items.append(
            ChecklistItem(
                item_id="CL-001",
                area="Общий доступ",
                check=f"Открыть страницу {model.target_url} и убедиться, что сервис доступен",
                expected_result="Страница открывается без критических ошибок",
                priority="high",
                note="Черновик без ответа LLM (резервный режим)",
                source_refs=[str(model.target_url)],
            )
        )
    return items


def fallback_test_cases(model: UnifiedRequirementModel, max_cases: int | None = None) -> list[TestCase]:
    items: list[TestCase] = []
    base_steps = [
        f"Открыть в браузере URL: {model.target_url}",
        "Убедиться, что страница загрузилась без ошибок",
        "Проверить по требованиям видимость ключевых элементов интерфейса",
    ]
    for i, req in enumerate(model.requirements, start=1):
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
    if not items:
        items.append(
            TestCase(
                case_id="TC-001",
                title="Доступность тестируемого стенда",
                preconditions="Приложение доступно по URL стенда",
                steps=base_steps,
                expected_result="Страница открывается без критических ошибок",
                environment="",
                status="",
                bug_report_id="",
                note="Черновик без ответа LLM (резервный режим); requirements отсутствуют, это gap/risk.",
                source_refs=[str(model.target_url)],
            )
        )
    return items
