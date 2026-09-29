from __future__ import annotations

import re
import string
from difflib import SequenceMatcher
from typing import Any

from ai_qahelper.models import TestCase

SIMILARITY_THRESHOLD = 0.92

_STEP_ENUM_RE = re.compile(r"(?m)^\s*(?:шаг\s*)?\d+[\.)\-:]?\s*", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_PUNCT_TRANSLATION = str.maketrans("", "", string.punctuation + "«»“”„—–…")
_QUOTED_RE = re.compile(r"[\"'«“]([^\"'»”]{1,80})[\"'»”]")
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", re.IGNORECASE)
_COND_RE = re.compile(r"\bCOND[-_ ]?0*\d+\b", re.IGNORECASE)
_NEGATIVE_MARKERS = ("пуст", "невалид", "ошиб", "отклон", "запрещ", "недопуст", "просроч", "слишком")
_BOUNDARY_MARKERS = ("границ", "миним", "максим", "меньше", "больше", "длина", "лимит")


def deduplicate_test_cases(test_cases: list[TestCase]) -> tuple[list[TestCase], dict[str, Any]]:
    kept: list[TestCase] = []
    report_items: list[dict[str, Any]] = []
    duplicate_groups: dict[str, dict[str, Any]] = {}

    for candidate in test_cases:
        duplicate = _find_duplicate(candidate, kept)
        if duplicate is None:
            kept.append(candidate)
            continue

        kept_case, reason, similarity = duplicate
        _merge_duplicate(kept_case, candidate)
        item = {
            "removed_case_id": candidate.case_id,
            "kept_case_id": kept_case.case_id,
            "reason": reason,
            "similarity": round(similarity, 4),
        }
        report_items.append(item)
        group = duplicate_groups.setdefault(
            kept_case.case_id,
            {"duplicate_group_id": f"DUP-{len(duplicate_groups) + 1:03d}", "reason": reason, "kept_case_id": kept_case.case_id, "removed_case_ids": []},
        )
        group["removed_case_ids"].append(candidate.case_id)

    renumbered = [
        case.model_copy(update={"case_id": f"TC-{idx:03d}"})
        for idx, case in enumerate(kept, start=1)
    ]
    report = {
        "before": len(test_cases),
        "after": len(renumbered),
        "removed": len(report_items),
        "items": report_items,
        "duplicate_groups": list(duplicate_groups.values()),
    }
    return renumbered, report


def _find_duplicate(candidate: TestCase, kept: list[TestCase]) -> tuple[TestCase, str, float] | None:
    cand_title = _normalize(candidate.title)
    cand_expected = _normalize(candidate.expected_result)
    cand_steps_expected = _steps_expected_key(candidate)
    cand_signature = _case_variation_signature(candidate)

    for item in kept:
        item_title = _normalize(item.title)
        item_expected = _normalize(item.expected_result)
        item_signature = _case_variation_signature(item)
        if cand_title and cand_title == item_title and cand_expected and cand_expected == item_expected:
            if _same_variation(cand_signature, item_signature):
                return item, "same_title_expected", 1.0
            continue
        if cand_title and cand_title == item_title:
            continue

        similarity = SequenceMatcher(None, cand_steps_expected, _steps_expected_key(item)).ratio()
        if cand_steps_expected and similarity >= SIMILARITY_THRESHOLD and _same_variation(cand_signature, item_signature):
            return item, "similar_steps_expected", similarity

    return None


def _merge_duplicate(kept_case: TestCase, removed_case: TestCase) -> None:
    refs = list(kept_case.source_refs)
    for ref in removed_case.source_refs:
        if ref and ref not in refs:
            refs.append(ref)

    note = kept_case.note
    if removed_case.note:
        merge_note = f"Merged duplicate: {removed_case.case_id}"
        note = f"{note}\n{merge_note}".strip() if note else merge_note

    kept_case.source_refs = refs
    kept_case.note = note


def _steps_expected_key(test_case: TestCase) -> str:
    return _normalize(" ".join(test_case.steps) + " " + test_case.expected_result)


def _case_variation_signature(test_case: TestCase) -> dict[str, set[str]]:
    text = " ".join(
        [
            test_case.title,
            test_case.preconditions,
            " ".join(test_case.steps),
            test_case.expected_result,
            test_case.note,
            " ".join(test_case.source_refs),
        ]
    )
    normalized = _normalize(text)
    return {
        "conditions": {_normalize(match.group(0)) for match in _COND_RE.finditer(text)},
        "test_data": _extract_test_data(text),
        "negative_reasons": {marker for marker in _NEGATIVE_MARKERS if marker in normalized},
        "boundary_reasons": {marker for marker in _BOUNDARY_MARKERS if marker in normalized},
    }


def _same_variation(left: dict[str, set[str]], right: dict[str, set[str]]) -> bool:
    for key in ("conditions", "test_data", "negative_reasons", "boundary_reasons"):
        left_values = left[key]
        right_values = right[key]
        if left_values and right_values and left_values != right_values:
            return False
    return True


def _extract_test_data(text: str) -> set[str]:
    values = {_normalize(match.group(1)) for match in _QUOTED_RE.finditer(text)}
    values.update(_normalize(match.group(0)) for match in _EMAIL_RE.finditer(text))
    values.update(_normalize(match.group(0)) for match in _NUMBER_RE.finditer(text))
    return {value for value in values if value}


def _normalize(value: str) -> str:
    text = (value or "").replace("ё", "е").replace("Ё", "е").lower().strip()
    text = _STEP_ENUM_RE.sub("", text)
    text = text.translate(_PUNCT_TRANSLATION)
    return _SPACE_RE.sub(" ", text).strip()
