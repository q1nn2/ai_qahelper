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


def deduplicate_test_cases(test_cases: list[TestCase]) -> tuple[list[TestCase], dict[str, Any]]:
    kept: list[TestCase] = []
    report_items: list[dict[str, Any]] = []

    for candidate in test_cases:
        duplicate = _find_duplicate(candidate, kept)
        if duplicate is None:
            kept.append(candidate)
            continue

        kept_case, reason, similarity = duplicate
        _merge_duplicate(kept_case, candidate)
        report_items.append(
            {
                "removed_case_id": candidate.case_id,
                "kept_case_id": kept_case.case_id,
                "reason": reason,
                "similarity": round(similarity, 4),
            }
        )

    renumbered = [
        case.model_copy(update={"case_id": f"TC-{idx:03d}"})
        for idx, case in enumerate(kept, start=1)
    ]
    report = {
        "before": len(test_cases),
        "after": len(renumbered),
        "removed": len(report_items),
        "items": report_items,
    }
    return renumbered, report


def _find_duplicate(candidate: TestCase, kept: list[TestCase]) -> tuple[TestCase, str, float] | None:
    cand_title = _normalize(candidate.title)
    cand_expected = _normalize(candidate.expected_result)
    cand_steps_expected = _steps_expected_key(candidate)

    for item in kept:
        item_title = _normalize(item.title)
        item_expected = _normalize(item.expected_result)
        if cand_title and cand_title == item_title and cand_expected and cand_expected == item_expected:
            return item, "same_title_expected", 1.0
        if cand_title and cand_title == item_title:
            return item, "same_title", 1.0

        similarity = SequenceMatcher(None, cand_steps_expected, _steps_expected_key(item)).ratio()
        if cand_steps_expected and similarity >= SIMILARITY_THRESHOLD:
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


def _normalize(value: str) -> str:
    text = (value or "").replace("ё", "е").replace("Ё", "е").lower().strip()
    text = _STEP_ENUM_RE.sub("", text)
    text = text.translate(_PUNCT_TRANSLATION)
    return _SPACE_RE.sub(" ", text).strip()
