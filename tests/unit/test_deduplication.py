from __future__ import annotations

from ai_qahelper.deduplication import deduplicate_test_cases
from ai_qahelper.models import TestCase


def _case(
    case_id: str,
    title: str,
    expected: str = "Ожидаемый результат",
    steps: list[str] | None = None,
    refs: list[str] | None = None,
    note: str = "",
) -> TestCase:
    return TestCase(
        case_id=case_id,
        title=title,
        preconditions="Пользователь на странице",
        steps=steps or ["Открыть страницу", "Нажать кнопку"],
        expected_result=expected,
        note=note,
        source_refs=refs or [],
    )


def test_deduplicate_removes_same_title() -> None:
    cases = [_case("TC-001", "Логин", "Успех"), _case("TC-002", "Логин", "Ошибка")]

    unique, report = deduplicate_test_cases(cases)

    assert len(unique) == 1
    assert report["removed"] == 1
    assert report["items"][0]["reason"] == "same_title"


def test_deduplicate_removes_same_title_expected() -> None:
    cases = [_case("TC-001", "Логин", "Успех"), _case("TC-002", "Логин", "Успех")]

    unique, report = deduplicate_test_cases(cases)

    assert len(unique) == 1
    assert report["items"][0]["reason"] == "same_title_expected"


def test_deduplicate_removes_similar_steps_expected() -> None:
    cases = [
        _case(
            "TC-001",
            "Оплата картой",
            "Платеж успешно создан",
            ["1. Открыть корзину", "2. Нажать Оплатить", "3. Подтвердить платеж"],
        ),
        _case(
            "TC-002",
            "Создание платежа",
            "Платеж успешно создан",
            ["Открыть корзину", "Нажать Оплатить", "Подтвердить платеж"],
        ),
    ]

    unique, report = deduplicate_test_cases(cases)

    assert len(unique) == 1
    assert report["items"][0]["reason"] == "similar_steps_expected"


def test_deduplicate_keeps_different_cases() -> None:
    cases = [
        _case("TC-001", "Логин успешный", "Открыт кабинет", ["Ввести валидные данные"]),
        _case("TC-002", "Ошибка оплаты", "Показана ошибка", ["Ввести отклоненную карту"]),
    ]

    unique, report = deduplicate_test_cases(cases)

    assert len(unique) == 2
    assert report["removed"] == 0


def test_deduplicate_renumbers_and_merges_refs_and_note() -> None:
    cases = [
        _case("TC-010", "Логин", "Успех", refs=["REQ-1"], note="base"),
        _case("TC-020", "Логин", "Успех", refs=["REQ-2"], note="extra"),
        _case("TC-030", "Выход", "Сессия завершена", refs=["REQ-3"]),
    ]

    unique, report = deduplicate_test_cases(cases)

    assert [case.case_id for case in unique] == ["TC-001", "TC-002"]
    assert unique[0].source_refs == ["REQ-1", "REQ-2"]
    assert "Merged duplicate: TC-020" in unique[0].note
    assert report == {
        "before": 3,
        "after": 2,
        "removed": 1,
        "items": [
            {
                "removed_case_id": "TC-020",
                "kept_case_id": "TC-010",
                "reason": "same_title_expected",
                "similarity": 1.0,
            }
        ],
    }
