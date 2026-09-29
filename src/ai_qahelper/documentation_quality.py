from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ai_qahelper.models import ChecklistItem, TestCase
from ai_qahelper.template_service import DocumentationTemplate, required_columns, template_record_value

_SPACE_RE = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")

_QUALITY_LINE_RE = re.compile(r"(?m)^Quality: .*$")
_GENERIC_TITLE_PATTERNS = (
    "проверка формы",
    "проверка функциональности",
    "проверка ui",
    "проверка интерфейса",
)
_BAD_EXPECTED_PHRASES = (
    "работает корректно",
    "работает правильно",
    "система работает",
    "данные обрабатываются корректно",
    "отображается корректно",
    "проверить корректность",
    "проверить функциональность",
    "все работает",
    "всё работает",
)
_BAD_CHECK_PHRASES = (
    "проверить корректность",
    "проверить работу",
    "проверить функциональность",
    "проверить ui",
    "проверка корректности",
    "проверка работы",
)
_MULTIPLE_CHECK_PAIRS = (
    ("регистрац", "авторизац"),
    ("авторизац", "выход"),
    ("создан", "удален"),
    ("создать", "удалить"),
    ("добавлен", "редактирован"),
    ("добавить", "редактировать"),
    ("оплат", "отмен"),
    ("поиск", "фильтрац"),
    ("фильтрац", "сортиров"),
)
_INVENTION_TERMS = (
    "sms",
    "смс",
    "email notification",
    "push",
    "payment",
    "оплат",
    "discount",
    "скид",
    "role",
    "admin",
    "админ",
    "two-factor",
    "2fa",
    "captcha",
    "капч",
    "promo code",
    "промокод",
    "delivery",
    "достав",
    "refund",
    "возврат",
    "api status",
    "http status",
)
_INPUT_TERMS = (
    "ввести",
    "ввод",
    "заполнить",
    "значение",
    "валид",
    "невалид",
    "negative",
    "boundary",
    "границ",
    "email",
    "телефон",
    "пароль",
)
_WEAK_AUTOMATION_PHRASES = (
    "визуально оценить",
    "убедиться в удобстве",
    "проверить красиво",
    "оценить удобство",
)
_POSITIVE_FLOW_MARKERS = ("успеш", "создан", "сохран", "открыт", "доступен", "переход")
_NEGATIVE_FLOW_MARKERS = ("ошиб", "невалид", "пуст", "запрещ", "нельзя", "отклон", "недопуст")
_BOUNDARY_FLOW_MARKERS = ("boundary", "границ", "миним", "максим", "лимит", "длина", "больше", "меньше")
_OBSERVABLE_EXPECTED_MARKERS = (
    "отображ",
    "сообщ",
    "статус",
    "сохран",
    "создан",
    "открыт",
    "перенаправ",
    "заблок",
    "неактив",
    "ошиб",
    "доступ",
)

_PENALTIES = {
    "required_fields": 40,
    "vague_title": 15,
    "vague_expected_result": 20,
    "vague_check": 15,
    "insufficient_steps": 15,
    "multiple_checks": 20,
    "missing_test_data": 15,
    "missing_source_refs": 10,
    "missing_priority": 10,
    "mixed_positive_negative": 15,
    "missing_boundary_value": 15,
    "non_observable_expected_result": 15,
    "possible_invented_requirement": 20,
    "automation_weakness": 10,
}


def evaluate_test_cases(test_cases: list[TestCase], template: DocumentationTemplate | None = None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for test_case in test_cases:
        issues = _test_case_issues(test_case, template)
        score = _score(issues)
        items.append(
            {
                "case_id": test_case.case_id,
                "quality_score": score,
                "status": _status(score),
                "issues": issues,
            }
        )
    return _build_report("test_cases", items)


def apply_quality_marks_to_test_cases(test_cases: list[TestCase], quality_report: dict[str, Any]) -> list[TestCase]:
    by_id = {item["case_id"]: item for item in quality_report.get("items", [])}
    marked: list[TestCase] = []
    for test_case in test_cases:
        item = by_id.get(test_case.case_id)
        if item is None:
            marked.append(test_case)
            continue
        marked.append(test_case.model_copy(update={"note": _append_quality_note(test_case.note, item)}))
    return marked


def evaluate_checklist_items(
    checklist: list[ChecklistItem],
    template: DocumentationTemplate | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in checklist:
        issues = _checklist_issues(item, template)
        score = _score(issues)
        items.append(
            {
                "item_id": item.item_id,
                "quality_score": score,
                "status": _status(score),
                "issues": issues,
            }
        )
    return _build_report("checklist", items)


def apply_quality_marks_to_checklist(checklist: list[ChecklistItem], quality_report: dict[str, Any]) -> list[ChecklistItem]:
    by_id = {item["item_id"]: item for item in quality_report.get("items", [])}
    marked: list[ChecklistItem] = []
    for checklist_item in checklist:
        item = by_id.get(checklist_item.item_id)
        if item is None:
            marked.append(checklist_item)
            continue
        marked.append(checklist_item.model_copy(update={"note": _append_quality_note(checklist_item.note, item)}))
    return marked


def _test_case_issues(test_case: TestCase, template: DocumentationTemplate | None = None) -> list[str]:
    issues: list[str] = []
    title = _norm(test_case.title)
    preconditions = _norm(test_case.preconditions)
    expected = _norm(test_case.expected_result)
    steps = [_norm(step) for step in test_case.steps if _norm(step)]
    joined = " ".join([title, preconditions, expected, " ".join(steps)])

    if _has_missing_required_fields(test_case, template) or (template is None and (not title or not preconditions or not steps or not expected)):
        issues.append("required_fields")
    if _has_missing_required_fields(test_case, template):
        issues.append("missing_required_field")
    if _is_vague_title(title):
        issues.append("vague_title")
    if _is_vague_expected(expected):
        issues.append("vague_expected_result")
    if _has_insufficient_steps(steps):
        issues.append("insufficient_steps")
    if _has_multiple_checks(joined):
        issues.append("multiple_checks")
    if _mixes_positive_negative(" ".join([title, expected])):
        issues.append("mixed_positive_negative")
    if _missing_boundary_value(joined):
        issues.append("missing_boundary_value")
    if _non_observable_expected(expected):
        issues.append("non_observable_expected_result")
    if _missing_test_data(joined):
        issues.append("missing_test_data")
    if _should_check_column(template, "source_refs") and not test_case.source_refs:
        issues.append("missing_source_refs")
    if _possible_invented_requirement(joined, test_case.source_refs, test_case.note):
        issues.append("possible_invented_requirement")
    if _automation_weakness(joined, steps, expected):
        issues.append("automation_weakness")
    return issues


def _checklist_issues(item: ChecklistItem, template: DocumentationTemplate | None = None) -> list[str]:
    issues: list[str] = []
    check = _norm(item.check)
    expected = _norm(item.expected_result)
    joined = f"{check} {expected}"
    if _has_missing_required_fields(item, template) or (template is None and (not check or not expected)):
        issues.append("required_fields")
    if _has_missing_required_fields(item, template):
        issues.append("missing_required_field")
    if _is_vague_check(check):
        issues.append("vague_check")
    if _is_vague_expected(expected):
        issues.append("vague_expected_result")
    if _mixes_positive_negative(joined):
        issues.append("mixed_positive_negative")
    if _missing_boundary_value(joined):
        issues.append("missing_boundary_value")
    if _non_observable_expected(expected):
        issues.append("non_observable_expected_result")
    if _should_check_column(template, "source_refs") and not item.source_refs:
        issues.append("missing_source_refs")
    if _should_check_column(template, "priority") and not item.priority:
        issues.append("missing_priority")
    if _automation_weakness(joined, [check], expected):
        issues.append("automation_weakness")
    return issues


def _build_report(report_type: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    summary = Counter(issue for item in items for issue in item["issues"])
    total = len(items)
    return {
        "type": report_type,
        "total": total,
        "ready": sum(1 for item in items if item["status"] == "ready"),
        "needs_review": sum(1 for item in items if item["status"] == "needs_review"),
        "weak": sum(1 for item in items if item["status"] == "weak"),
        "average_score": round(sum(item["quality_score"] for item in items) / total, 1) if total else 0.0,
        "items": items,
        "summary_issues": dict(sorted(summary.items())),
    }


def _score(issues: list[str]) -> int:
    score = 100
    for issue in set(issues):
        score -= _PENALTIES.get(issue, 10)
    return max(0, score)


def _has_missing_required_fields(record: TestCase | ChecklistItem, template: DocumentationTemplate | None) -> bool:
    if template is None:
        return False
    for column in required_columns(template):
        value = template_record_value(record, column.key)
        if column.type == "list" and not value:
            return True
        if isinstance(value, list):
            if not [item for item in value if _norm(str(item))]:
                return True
        elif not _norm(str(value)):
            return True
    return False


def _should_check_column(template: DocumentationTemplate | None, key: str) -> bool:
    if template is None:
        return True
    return any(column.key == key and (column.enabled or column.required) for column in template.columns)


def _status(score: int) -> str:
    if score >= 85:
        return "ready"
    if score >= 70:
        return "needs_review"
    return "weak"


def _append_quality_note(note: str, item: dict[str, Any]) -> str:
    cleaned = _QUALITY_LINE_RE.sub("", note or "").strip()
    issues = item.get("issues") or []
    if item["status"] == "ready":
        quality = f"Quality: ready; score: {item['quality_score']}"
    else:
        quality = f"Quality: {item['status']}; score: {item['quality_score']}; issues: {', '.join(issues)}"
    return f"{cleaned}\n{quality}".strip() if cleaned else quality


def _is_vague_title(title: str) -> bool:
    if len(title.split()) < 3:
        return True
    return title in _GENERIC_TITLE_PATTERNS or any(title.startswith(pattern) for pattern in _GENERIC_TITLE_PATTERNS)


def _is_vague_check(check: str) -> bool:
    if len(check.split()) < 4:
        return True
    return any(phrase in check for phrase in _BAD_CHECK_PHRASES)


def _is_vague_expected(expected: str) -> bool:
    if not expected:
        return True
    if any(phrase in expected for phrase in _BAD_EXPECTED_PHRASES):
        return True
    if "ошибка отображается" in expected and not any(word in expected for word in ("причин", "пол", "страниц", "форм", "значен")):
        return True
    if "успешно" in expected and not any(
        word in expected
        for word in ("перенаправ", "отображ", "сохран", "создан", "статус", "страниц", "сообщен", "актив")
    ):
        return True
    return expected in {"операция выполнена успешно", "успешно", "ошибка отображается"}


def _has_insufficient_steps(steps: list[str]) -> bool:
    if len(steps) < 2:
        return True
    if any(len(step.split()) < 2 for step in steps):
        return True
    joined = " ".join(steps)
    if "проверить все" in joined or "проверить всё" in joined:
        return True
    return sum(joined.count(marker) for marker in (" и ", "а также", "затем проверить")) >= 4


def _has_multiple_checks(text: str) -> bool:
    if "поиск" in text and "фильтрац" in text and "сортиров" in text:
        return True
    return any(left in text and right in text for left, right in _MULTIPLE_CHECK_PAIRS)


def _missing_test_data(text: str) -> bool:
    if not any(term in text for term in _INPUT_TERMS):
        return False
    if _EMAIL_RE.search(text) or _URL_RE.search(text) or _NUMBER_RE.search(text):
        return False
    if any(token in text for token in ("testexample.com", "test@example", "+7", "null", "empty", "пуст")):
        return False
    if "невалид" in text and ("email" in text or "почт" in text):
        return True
    quoted_values = re.findall(r"[\"'«][^\"'»]{2,}[\"'»]", text)
    if quoted_values:
        return False
    return "невалид" in text or "валид" in text or "ввести" in text or "заполнить" in text


def _mixes_positive_negative(text: str) -> bool:
    has_positive = any(marker in text for marker in _POSITIVE_FLOW_MARKERS)
    has_negative = any(marker in text for marker in _NEGATIVE_FLOW_MARKERS)
    if not has_positive or not has_negative:
        return False
    return any(separator in text for separator in (" и ", " а также ", " затем ", "после этого"))


def _missing_boundary_value(text: str) -> bool:
    if not any(marker in text for marker in _BOUNDARY_FLOW_MARKERS):
        return False
    return not (_NUMBER_RE.search(text) or any(token in text for token in ("min", "max", "null", "empty", "пуст")))


def _non_observable_expected(expected: str) -> bool:
    if not expected or _is_vague_expected(expected):
        return False
    return not any(marker in expected for marker in _OBSERVABLE_EXPECTED_MARKERS)


def _possible_invented_requirement(text: str, source_refs: list[str], note: str) -> bool:
    if not any(term in text for term in _INVENTION_TERMS):
        return False
    if source_refs and any(marker in _norm(note) for marker in ("assumption", "gap", "site-discovery", "site discovery")):
        return False
    return not source_refs or not any(marker in _norm(note) for marker in ("assumption", "gap", "site-discovery", "site discovery"))


def _automation_weakness(text: str, steps: list[str], expected: str) -> bool:
    if any(phrase in text for phrase in _WEAK_AUTOMATION_PHRASES):
        return True
    return _has_insufficient_steps(steps) or _is_vague_expected(expected)


def _norm(value: str) -> str:
    return _SPACE_RE.sub(" ", (value or "").replace("ё", "е").lower()).strip()
