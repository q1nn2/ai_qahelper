from __future__ import annotations

from ai_qahelper.documentation_quality import (
    apply_quality_marks_to_checklist,
    apply_quality_marks_to_test_cases,
    evaluate_checklist_items,
    evaluate_test_cases,
)
from ai_qahelper.models import ChecklistItem, TestCase
from ai_qahelper.template_service import default_template


def _case(
    *,
    case_id: str = "TC-001",
    title: str = "Отображение сообщения при пустом Email",
    preconditions: str = "Пользователь находится на форме входа, поле Email пустое",
    steps: list[str] | None = None,
    expected_result: str = "Под полем Email отображается сообщение об ошибке о причине невалидного значения",
    source_refs: list[str] | None = None,
    note: str = "REQ-1",
) -> TestCase:
    return TestCase(
        case_id=case_id,
        title=title,
        preconditions=preconditions,
        steps=steps or ["Открыть форму входа", "Оставить поле Email пустым и нажать кнопку 'Войти'"],
        expected_result=expected_result,
        note=note,
        source_refs=source_refs if source_refs is not None else ["REQ-1"],
    )


def test_evaluate_test_cases_ready_for_good_case() -> None:
    report = evaluate_test_cases([_case()])

    item = report["items"][0]
    assert item["status"] == "ready"
    assert item["quality_score"] >= 85
    assert item["issues"] == []


def test_evaluate_test_cases_flags_vague_expected_result() -> None:
    report = evaluate_test_cases([_case(expected_result="Форма работает корректно")])

    assert "vague_expected_result" in report["items"][0]["issues"]


def test_evaluate_test_cases_flags_missing_source_refs() -> None:
    report = evaluate_test_cases([_case(source_refs=[])])

    assert "missing_source_refs" in report["items"][0]["issues"]


def test_evaluate_test_cases_flags_missing_test_data() -> None:
    report = evaluate_test_cases(
        [
            _case(
                title="Валидация невалидного Email",
                preconditions="Пользователь находится на форме входа",
                steps=["Открыть форму входа", "Ввести невалидный email и нажать кнопку 'Войти'"],
            )
        ]
    )

    assert "missing_test_data" in report["items"][0]["issues"]


def test_evaluate_test_cases_flags_multiple_checks() -> None:
    report = evaluate_test_cases([_case(title="Регистрация и авторизация нового пользователя")])

    assert "multiple_checks" in report["items"][0]["issues"]


def test_evaluate_test_cases_flags_insufficient_steps() -> None:
    report = evaluate_test_cases([_case(steps=["Проверить всё"])])

    assert "insufficient_steps" in report["items"][0]["issues"]


def test_apply_quality_marks_to_test_cases_adds_note() -> None:
    cases = [_case(expected_result="Форма работает корректно", note="base note")]
    report = evaluate_test_cases(cases)

    marked = apply_quality_marks_to_test_cases(cases, report)

    assert "base note" in marked[0].note
    assert "Quality:" in marked[0].note
    assert "vague_expected_result" in marked[0].note


def test_evaluate_checklist_items_ready_for_good_item() -> None:
    item = ChecklistItem(
        item_id="CL-001",
        area="Авторизация",
        check="Проверить, что кнопка 'Войти' неактивна при пустом обязательном поле Email",
        expected_result="Кнопка 'Войти' остаётся неактивной, пока обязательное поле Email пустое",
        priority="high",
        source_refs=["REQ-1"],
    )

    report = evaluate_checklist_items([item])

    assert report["items"][0]["status"] == "ready"


def test_evaluate_checklist_items_flags_vague_check() -> None:
    item = ChecklistItem(
        item_id="CL-001",
        area="Форма",
        check="Проверить корректность работы формы",
        expected_result="Форма отображает сообщение об ошибке о причине невалидного значения",
        priority="medium",
        source_refs=["REQ-1"],
    )

    report = evaluate_checklist_items([item])

    assert "vague_check" in report["items"][0]["issues"]


def test_apply_quality_marks_to_checklist_adds_note() -> None:
    item = ChecklistItem(
        item_id="CL-001",
        check="Проверить корректность работы формы",
        expected_result="Форма работает корректно",
        source_refs=[],
    )
    report = evaluate_checklist_items([item])

    marked = apply_quality_marks_to_checklist([item], report)

    assert "Quality:" in marked[0].note
    assert "vague_check" in marked[0].note


def test_quality_gate_flags_empty_required_template_field() -> None:
    template = default_template("test_cases")
    report = evaluate_test_cases([_case(title="")], template=template)

    assert "missing_required_field" in report["items"][0]["issues"]


def test_quality_gate_ignores_disabled_optional_template_field() -> None:
    template = default_template("test_cases")
    template.columns = [
        column.model_copy(update={"enabled": column.required})
        for column in template.columns
    ]
    case = _case(preconditions="", source_refs=[])

    report = evaluate_test_cases([case], template=template)

    assert "missing_required_field" not in report["items"][0]["issues"]
    assert "missing_source_refs" not in report["items"][0]["issues"]
