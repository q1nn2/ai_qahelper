from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from ai_qahelper.models import ChecklistItem, TestAnalysisReport, TestCase, UnifiedRequirementModel

DocumentationItem = TestCase | ChecklistItem

_REQ_RE = re.compile(r"\bREQ[-_ ]?0*(\d+)\b", re.IGNORECASE)
_COND_RE = re.compile(r"\bCOND[-_ ]?0*(\d+)\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-zA-Zа-яА-Я0-9]{4,}")

_CATEGORY_MARKERS: dict[str, tuple[str, ...]] = {
    "validation_rule": (
        "валидац",
        "invalid",
        "valid",
        "required",
        "обязател",
        "ошибк",
        "формат",
        "пуст",
        "email",
        "парол",
        "телефон",
        "лимит",
        "миним",
        "максим",
    ),
    "role_permission": ("роль", "права", "permission", "admin", "админ", "доступ", "авториз", "логин"),
    "business_rule": ("правило", "business", "должен", "может", "нельзя", "разреш", "запрещ", "статус"),
    "ui_requirement": ("кнопк", "экран", "форма", "поле", "отображ", "видим", "интерфейс", "ui", "страниц"),
    "integration": ("api", "интеграц", "webhook", "сервис", "база", "endpoint", "http", "синхрон"),
    "error_state": ("ошибка", "error", "failed", "недоступ", "исключ", "timeout", "отказ"),
    "non_functional": ("performance", "security", "доступност", "нагруз", "скорост", "безопас", "a11y"),
    "out_of_scope": ("out of scope", "не входит", "не рассматри", "исключено"),
    "unclear": ("tbd", "todo", "уточнить", "примерно", "и т.д", "etc", "непонят", "позже"),
}
_DEFAULT_CATEGORY = "functional"

_AMBIGUITY_MARKERS = (
    "корректно",
    "правильно",
    "удобно",
    "быстро",
    "обычно",
    "и т.д",
    "etc",
    "при необходимости",
    "если нужно",
    "уточнить",
    "tbd",
    "todo",
)
_INPUT_MARKERS = ("поле", "форма", "ввести", "ввод", "email", "пароль", "телефон", "значение")
_NEGATIVE_MARKERS = ("ошибка", "невалид", "пуст", "нельзя", "запрещ", "invalid", "error")
_BOUNDARY_MARKERS = ("мин", "макс", "лимит", "длина", "больше", "меньше", "boundary", "границ")


def build_requirements_classification(model: UnifiedRequirementModel) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    category_counter: Counter[str] = Counter()
    for idx, requirement in enumerate(model.requirements, start=1):
        text = requirement.content or ""
        categories = _classify_text(text)
        category_counter.update(categories)
        items.append(
            {
                "requirement_id": f"REQ-{idx:03d}",
                "source": requirement.source,
                "categories": categories,
                "primary_category": categories[0],
                "confidence": _classification_confidence(text, categories),
                "signals": _classification_signals(text),
                "preview": _preview(text),
            }
        )
    return {
        "type": "requirements_classification",
        "summary": {
            "requirements_total": len(items),
            "categories": dict(sorted(category_counter.items())),
        },
        "items": items,
    }


def build_requirements_review(
    model: UnifiedRequirementModel,
    classification: dict[str, Any],
    consistency_report: dict[str, Any] | None = None,
    analysis: TestAnalysisReport | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    classification_by_req = {item["requirement_id"]: item for item in classification.get("items", [])}
    for idx, requirement in enumerate(model.requirements, start=1):
        req_id = f"REQ-{idx:03d}"
        text = requirement.content or ""
        categories = set(classification_by_req.get(req_id, {}).get("categories") or [])
        findings.extend(_requirement_findings(req_id, requirement.source, text, categories))

    for finding in (consistency_report or {}).get("findings", []):
        findings.append(
            {
                "id": f"RQ-{len(findings) + 1:03d}",
                "source_ref": finding.get("source") or "consistency-report",
                "type": finding.get("type") or "consistency",
                "severity": _severity_for_finding_type(finding.get("type") or ""),
                "description": finding.get("reason") or finding.get("requirement") or "Consistency finding",
                "risk": "Тесты могут покрыть не то поведение или пропустить важный сценарий.",
                "question_to_analyst": "Подтвердите актуальное правило и ожидаемое поведение.",
                "suggested_test_idea": "Добавить проверку после уточнения требования.",
            }
        )

    if analysis:
        for risk in analysis.risks_and_gaps:
            findings.append(
                {
                    "id": f"RQ-{len(findings) + 1:03d}",
                    "source_ref": "test-analysis",
                    "type": "analysis_risk",
                    "severity": "medium",
                    "description": risk,
                    "risk": "Риск из test analysis должен быть явно отражён в тест-дизайне.",
                    "question_to_analyst": "Нужно ли добавить правило или ограничение в требования?",
                    "suggested_test_idea": "Покрыть риск отдельным негативным или regression тестом.",
                }
            )

    for idx, finding in enumerate(findings, start=1):
        finding["id"] = finding.get("id") or f"RQ-{idx:03d}"

    return {
        "type": "requirements_review",
        "summary": {
            "findings_total": len(findings),
            "by_type": dict(sorted(Counter(item["type"] for item in findings).items())),
            "by_severity": dict(sorted(Counter(item["severity"] for item in findings).items())),
        },
        "findings": findings,
    }


def render_requirements_review_markdown(review: dict[str, Any]) -> str:
    lines = ["# Requirements Review", ""]
    summary = review.get("summary") or {}
    lines.append(f"- Findings total: {summary.get('findings_total', 0)}")
    for key, value in (summary.get("by_type") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    for finding in review.get("findings", []):
        lines.extend(
            [
                f"## {finding['id']} — {finding['type']}",
                f"- Source: {finding['source_ref']}",
                f"- Severity: {finding['severity']}",
                f"- Description: {finding['description']}",
                f"- Risk: {finding['risk']}",
                f"- Question: {finding['question_to_analyst']}",
                f"- Suggested test idea: {finding['suggested_test_idea']}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def build_traceability_matrix(
    model: UnifiedRequirementModel,
    analysis: TestAnalysisReport | None,
    items: list[DocumentationItem],
    classification: dict[str, Any],
    requirements_review: dict[str, Any],
) -> dict[str, Any]:
    item_refs = [_item_ref_data(item) for item in items]
    conditions = _condition_rows(analysis)
    conditions_by_req: dict[str, list[dict[str, str]]] = {}
    for condition in conditions:
        conditions_by_req.setdefault(condition["requirement_ref"], []).append(condition)

    review_by_source = _review_findings_by_source(requirements_review)
    classification_by_req = {item["requirement_id"]: item for item in classification.get("items", [])}
    rows: list[dict[str, Any]] = []
    condition_rows: list[dict[str, Any]] = []

    for idx, requirement in enumerate(model.requirements, start=1):
        req_id = f"REQ-{idx:03d}"
        req_conditions = conditions_by_req.get(req_id, [])
        covered_by = [
            item_id
            for item_id, refs_text in item_refs
            if _matches_requirement(refs_text, req_id, requirement.source)
        ]
        missing_conditions: list[str] = []
        for condition in req_conditions:
            condition_covered_by = [
                item_id
                for item_id, refs_text in item_refs
                if _matches_condition(refs_text, condition["condition_id"])
            ]
            if condition_covered_by:
                covered_by.extend(condition_covered_by)
            else:
                missing_conditions.append(condition["condition_id"])
            condition_rows.append(
                {
                    "requirement_id": req_id,
                    "condition_id": condition["condition_id"],
                    "description": condition["description"],
                    "status": "covered" if condition_covered_by else "missing",
                    "covered_by": ", ".join(dict.fromkeys(condition_covered_by)),
                }
            )
        covered_by = list(dict.fromkeys(covered_by))
        review_findings = review_by_source.get(req_id, []) + review_by_source.get(requirement.source, [])
        status = _traceability_status(covered_by, missing_conditions, review_findings)
        rows.append(
            {
                "requirement_id": req_id,
                "source": requirement.source,
                "requirement_type": classification_by_req.get(req_id, {}).get("primary_category", _DEFAULT_CATEGORY),
                "status": status,
                "gap_reason": _traceability_gap_reason(status, missing_conditions, review_findings),
                "condition_ids": ", ".join(condition["condition_id"] for condition in req_conditions),
                "covered_by": ", ".join(covered_by),
                "missing_conditions": ", ".join(missing_conditions),
                "review_findings": ", ".join(finding["id"] for finding in review_findings),
                "preview": _preview(requirement.content),
            }
        )

    summary = {
        "requirements_total": len(rows),
        "covered": sum(1 for row in rows if row["status"] == "covered"),
        "partial": sum(1 for row in rows if row["status"] == "partial"),
        "missing": sum(1 for row in rows if row["status"] == "missing"),
        "unclear": sum(1 for row in rows if row["status"] == "unclear"),
        "conditions_total": len(condition_rows),
        "conditions_covered": sum(1 for row in condition_rows if row["status"] == "covered"),
    }
    return {
        "type": "traceability_matrix",
        "summary": summary,
        "requirements": rows,
        "test_conditions": condition_rows,
    }


def export_traceability_matrix_xlsx(path: Path, matrix: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(matrix.get("requirements", [])).to_excel(writer, sheet_name="requirements", index=False)
        pd.DataFrame(matrix.get("test_conditions", [])).to_excel(writer, sheet_name="conditions", index=False)
        pd.DataFrame([matrix.get("summary", {})]).to_excel(writer, sheet_name="summary", index=False)
    return path


def _classify_text(text: str) -> list[str]:
    normalized = _normalize(text)
    categories: list[str] = []
    for category, markers in _CATEGORY_MARKERS.items():
        if any(marker in normalized for marker in markers):
            categories.append(category)
    if not categories:
        categories.append(_DEFAULT_CATEGORY)
    elif _DEFAULT_CATEGORY not in categories and not {"out_of_scope", "unclear"} & set(categories):
        categories.append(_DEFAULT_CATEGORY)
    return categories


def _classification_confidence(text: str, categories: list[str]) -> str:
    signals = len(_classification_signals(text))
    if categories == [_DEFAULT_CATEGORY] and signals == 0:
        return "low"
    if signals >= 3:
        return "high"
    return "medium"


def _classification_signals(text: str) -> list[str]:
    normalized = _normalize(text)
    signals: list[str] = []
    for category, markers in _CATEGORY_MARKERS.items():
        matched = [marker for marker in markers if marker in normalized]
        if matched:
            signals.append(f"{category}: {', '.join(matched[:3])}")
    return signals


def _requirement_findings(req_id: str, source: str, text: str, categories: set[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    normalized = _normalize(text)
    if not _WORD_RE.findall(text) or len(_WORD_RE.findall(text)) < 4:
        findings.append(_finding(req_id, source, "unverifiable_requirement", "high", "Требование слишком короткое для детерминированной проверки."))
    if any(marker in normalized for marker in _AMBIGUITY_MARKERS) or "unclear" in categories:
        findings.append(_finding(req_id, source, "ambiguity", "medium", "Формулировка содержит неоднозначные или временные маркеры."))
    if any(marker in normalized for marker in _INPUT_MARKERS) and not any(marker in normalized for marker in _NEGATIVE_MARKERS):
        findings.append(_finding(req_id, source, "missing_validation_rule", "medium", "Есть ввод данных, но не описано поведение при невалидных или пустых значениях."))
    if any(marker in normalized for marker in _INPUT_MARKERS) and not any(marker in normalized for marker in _BOUNDARY_MARKERS):
        findings.append(_finding(req_id, source, "missing_boundary_rule", "low", "Есть ввод данных, но не указаны граничные значения или лимиты."))
    if "role_permission" in categories and "error_state" not in categories and not any(marker in normalized for marker in _NEGATIVE_MARKERS):
        findings.append(_finding(req_id, source, "missing_permission_negative", "medium", "Есть роли или доступы, но не описан отказ для запрещённого действия."))
    return findings


def _finding(req_id: str, source: str, finding_type: str, severity: str, description: str) -> dict[str, Any]:
    return {
        "id": "",
        "source_ref": req_id,
        "source": source,
        "type": finding_type,
        "severity": severity,
        "description": description,
        "risk": "Без уточнения тесты могут стать неполными или слишком общими.",
        "question_to_analyst": _question_for_type(finding_type),
        "suggested_test_idea": _test_idea_for_type(finding_type),
    }


def _question_for_type(finding_type: str) -> str:
    return {
        "missing_validation_rule": "Какие сообщения и состояния ожидаются для пустых, неверных и недопустимых значений?",
        "missing_boundary_rule": "Какие минимальные, максимальные и граничные значения допустимы?",
        "missing_permission_negative": "Что должен увидеть пользователь без нужных прав?",
        "ambiguity": "Какое точное и проверяемое поведение ожидается?",
    }.get(finding_type, "Какое конкретное проверяемое поведение должно быть зафиксировано?")


def _test_idea_for_type(finding_type: str) -> str:
    return {
        "missing_validation_rule": "Добавить negative tests для пустых, неверных и запрещённых значений.",
        "missing_boundary_rule": "Добавить boundary value tests для минимального, максимального и выходящего за предел значения.",
        "missing_permission_negative": "Добавить negative test для пользователя без нужной роли.",
        "ambiguity": "Добавить тест после уточнения ожидаемого результата.",
    }.get(finding_type, "Добавить тест после уточнения требования.")


def _severity_for_finding_type(finding_type: str) -> str:
    if finding_type in {"contradiction", "missing", "unverifiable_requirement"}:
        return "high"
    if finding_type in {"ambiguity", "missing_validation_rule", "missing_permission_negative"}:
        return "medium"
    return "low"


def _condition_rows(analysis: TestAnalysisReport | None) -> list[dict[str, str]]:
    if not analysis:
        return []
    return [
        {
            "condition_id": _canonical_cond_id(condition.id),
            "description": condition.description,
            "requirement_ref": _canonical_req_id(condition.requirement_ref) or condition.requirement_ref,
        }
        for condition in analysis.test_conditions
    ]


def _item_ref_data(item: DocumentationItem) -> tuple[str, str]:
    item_id = getattr(item, "case_id", None) or getattr(item, "item_id", "")
    text = " ".join(
        str(value)
        for value in [
            " ".join(getattr(item, "source_refs", []) or []),
            getattr(item, "note", ""),
            getattr(item, "title", ""),
            getattr(item, "check", ""),
            getattr(item, "expected_result", ""),
            " ".join(getattr(item, "steps", []) or []),
        ]
        if value
    )
    return str(item_id), text


def _review_findings_by_source(review: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for idx, finding in enumerate(review.get("findings", []), start=1):
        if not finding.get("id"):
            finding["id"] = f"RQ-{idx:03d}"
        result.setdefault(finding.get("source_ref") or "", []).append(finding)
        if finding.get("source"):
            result.setdefault(finding["source"], []).append(finding)
    return result


def _traceability_status(covered_by: list[str], missing_conditions: list[str], review_findings: list[dict[str, Any]]) -> str:
    if any(finding["type"] in {"ambiguity", "unverifiable_requirement"} for finding in review_findings):
        return "unclear"
    if not covered_by:
        return "missing"
    if missing_conditions or any(finding["severity"] in {"high", "medium"} for finding in review_findings):
        return "partial"
    return "covered"


def _traceability_gap_reason(status: str, missing_conditions: list[str], review_findings: list[dict[str, Any]]) -> str:
    if status == "covered":
        return ""
    reasons: list[str] = []
    if missing_conditions:
        reasons.append(f"missing_conditions: {', '.join(missing_conditions)}")
    reasons.extend(finding["type"] for finding in review_findings[:3])
    if not reasons and status == "missing":
        reasons.append("no_linked_tests")
    return "; ".join(dict.fromkeys(reasons))


def _matches_requirement(refs_text: str, requirement_id: str, source: str) -> bool:
    canonical_refs = {_canonical_req_id(match.group(0)) for match in _REQ_RE.finditer(refs_text)}
    return requirement_id in canonical_refs or (source and source in refs_text)


def _matches_condition(refs_text: str, condition_id: str) -> bool:
    canonical_refs = {_canonical_cond_id(match.group(0)) for match in _COND_RE.finditer(refs_text)}
    return condition_id in canonical_refs


def _canonical_req_id(value: str) -> str:
    match = _REQ_RE.search(value or "")
    return f"REQ-{int(match.group(1)):03d}" if match else ""


def _canonical_cond_id(value: str) -> str:
    match = _COND_RE.search(value or "")
    return f"COND-{int(match.group(1)):03d}" if match else (value or "").strip()


def _preview(text: str, limit: int = 220) -> str:
    value = " ".join((text or "").split())
    return value if len(value) <= limit else f"{value[: limit - 1]}..."


def _normalize(text: str) -> str:
    return (text or "").replace("ё", "е").lower()
