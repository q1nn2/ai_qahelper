from __future__ import annotations

import re
from typing import Any

from ai_qahelper.models import ChecklistItem, TestAnalysisReport, TestCase, UnifiedRequirementModel

CoverageItem = TestCase | ChecklistItem

_REQ_RE = re.compile(r"\bREQ[-_ ]?0*(\d+)\b", re.IGNORECASE)
_COND_RE = re.compile(r"\bCOND[-_ ]?0*(\d+)\b", re.IGNORECASE)


def build_coverage_report(
    model: UnifiedRequirementModel,
    analysis: TestAnalysisReport | None,
    items: list[CoverageItem],
    *,
    dedup_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a requirements coverage report from generated documentation links."""

    requirement_rows = _requirement_rows(model)
    condition_rows = _condition_rows(analysis)
    item_refs = [_item_ref_data(item) for item in items]

    condition_reports: list[dict[str, Any]] = []
    covered_conditions_by_req: dict[str, set[str]] = {}
    for condition in condition_rows:
        covered_by = [
            item_id
            for item_id, refs_text in item_refs
            if _matches_condition(refs_text, condition["condition_id"])
        ]
        status = "covered" if covered_by else "uncovered"
        if covered_by and condition["requirement_ref"]:
            covered_conditions_by_req.setdefault(_canonical_req_id(condition["requirement_ref"]), set()).add(
                condition["condition_id"]
            )
        condition_reports.append(
            {
                "condition_id": condition["condition_id"],
                "description": condition["description"],
                "status": status,
                "covered_by": covered_by,
                "requirement_ref": condition["requirement_ref"],
            }
        )

    requirement_reports: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    for requirement in requirement_rows:
        req_id = requirement["requirement_id"]
        linked_conditions = [
            c["condition_id"]
            for c in condition_rows
            if _canonical_req_id(c["requirement_ref"]) == req_id or c["requirement_ref"] == requirement["source"]
        ]
        covered_by = [
            item_id
            for item_id, refs_text in item_refs
            if _matches_requirement(refs_text, req_id, requirement["source"])
        ]
        covered_by.extend(
            item_id
            for item_id, refs_text in item_refs
            if any(_matches_condition(refs_text, condition_id) for condition_id in linked_conditions)
        )
        covered_by = list(dict.fromkeys(covered_by))
        covered_conditions = covered_conditions_by_req.get(req_id, set())
        missing_checks = [condition_id for condition_id in linked_conditions if condition_id not in covered_conditions]

        if not covered_by:
            status = "uncovered"
        elif missing_checks:
            status = "partial"
        else:
            status = "covered"

        note = ""
        if status != "covered":
            note = "Требование требует дополнительного покрытия или уточнения."
            gaps.append(
                {
                    "source": requirement["source"],
                    "reason": f"Coverage status: {status}",
                    "recommendation": "Уточнить требование или добавить недостающие проверки.",
                }
            )
        requirement_reports.append(
            {
                "requirement_id": req_id,
                "source": requirement["source"],
                "status": status,
                "covered_by": covered_by,
                "missing_checks": missing_checks,
                "note": note,
            }
        )

    for risk in (analysis.risks_and_gaps if analysis else []):
        gaps.append(
            {
                "source": "test-analysis",
                "reason": risk,
                "recommendation": "Проверить с владельцем требований и не подменять недостающие правила догадками.",
            }
        )

    summary = {
        "requirements_total": len(requirement_reports),
        "requirements_covered": sum(1 for row in requirement_reports if row["status"] == "covered"),
        "requirements_partial": sum(1 for row in requirement_reports if row["status"] == "partial"),
        "requirements_uncovered": sum(1 for row in requirement_reports if row["status"] in {"uncovered", "gap"}),
        "test_conditions_total": len(condition_reports),
        "test_conditions_covered": sum(1 for row in condition_reports if row["status"] == "covered"),
        "test_cases_total": len(items),
        "duplicates_removed": int((dedup_report or {}).get("removed") or 0),
    }
    return {
        "summary": summary,
        "requirements": requirement_reports,
        "test_conditions": condition_reports,
        "gaps": gaps,
    }


def coverage_needs_more_cases(report: dict[str, Any]) -> bool:
    summary = report.get("summary") or {}
    return bool(
        summary.get("requirements_partial")
        or summary.get("requirements_uncovered")
        or summary.get("test_conditions_total", 0) > summary.get("test_conditions_covered", 0)
    )


def _requirement_rows(model: UnifiedRequirementModel) -> list[dict[str, str]]:
    return [
        {
            "requirement_id": f"REQ-{idx:03d}",
            "source": req.source,
            "content": req.content,
        }
        for idx, req in enumerate(model.requirements, start=1)
    ]


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


def _item_ref_data(item: CoverageItem) -> tuple[str, str]:
    item_id = getattr(item, "case_id", None) or getattr(item, "item_id", "")
    refs = " ".join(getattr(item, "source_refs", []) or [])
    text = " ".join(
        str(value)
        for value in [
            refs,
            getattr(item, "note", ""),
            getattr(item, "title", ""),
            getattr(item, "check", ""),
        ]
        if value
    )
    return str(item_id), text


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
