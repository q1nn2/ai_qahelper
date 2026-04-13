from __future__ import annotations

import re

from ai_qahelper.models import AutoExecutionResult, TestCase, UnifiedRequirementModel


def _test_case_text_corpus(test_cases: list[TestCase]) -> str:
    parts: list[str] = []
    for tc in test_cases:
        parts.extend(
            [
                tc.title,
                tc.preconditions,
                tc.expected_result,
                tc.note,
                " ".join(tc.source_refs),
                " ".join(tc.steps),
            ]
        )
    return " ".join(parts).lower()


def _req_keyword_covers_requirement(req_content: str, corpus: str) -> bool:
    keys = _keywords((req_content or "")[:4000])
    if not keys:
        return False
    hits = sum(1 for k in keys if k in corpus)
    need = max(1, min(len(keys), (len(keys) + 2) // 3))
    return hits >= need


def check_requirement_coverage(model: UnifiedRequirementModel, test_cases: list[TestCase]) -> dict:
    """
    Два эвристических уровня (не семантическая трассировка).
    strict_source: путь/URL требования встречается в source_refs кейса.
    keyword_overlap: токены из текста требования встречаются в текстах кейсов.
    """
    req_count = len(model.requirements)
    corpus = _test_case_text_corpus(test_cases)

    strict_covered = 0
    kw_covered = 0
    for req in model.requirements:
        if any(req.source in tc.source_refs for tc in test_cases):
            strict_covered += 1
        if _req_keyword_covers_requirement(req.content, corpus):
            kw_covered += 1

    strict_ratio = (strict_covered / req_count) if req_count else 1.0
    kw_ratio = (kw_covered / req_count) if req_count else 1.0

    return {
        "coverage_mode": "heuristic_v1",
        "note": (
            "Эвристика, не полное семантическое покрытие: strict_source — совпадение source в source_refs; "
            "keyword_overlap — пересечение ключевых слов текста требования с полями кейсов."
        ),
        "requirements_total": req_count,
        "strict_source": {
            "requirements_covered": strict_covered,
            "coverage_ratio": strict_ratio,
        },
        "keyword_overlap": {
            "requirements_covered": kw_covered,
            "coverage_ratio": kw_ratio,
        },
        "requirements_covered": strict_covered,
        "coverage_ratio": strict_ratio,
    }


def check_pass_rate(auto_results: list[AutoExecutionResult]) -> dict:
    total = len([r for r in auto_results if r.status != "skipped"])
    passed = len([r for r in auto_results if r.status == "passed"])
    return {"auto_total": total, "auto_passed": passed, "pass_rate": (passed / total) if total else 0.0}


def _extract_requirement_clauses(model: UnifiedRequirementModel) -> list[dict]:
    clauses: list[dict] = []
    for req in model.requirements:
        for raw_line in req.content.splitlines():
            line = raw_line.strip(" -*\t")
            if len(line) < 8:
                continue
            clauses.append({"source": req.source, "text": line})
    return clauses


def _design_corpus(model: UnifiedRequirementModel) -> str:
    if not model.design:
        return ""
    chunks: list[str] = []
    stack = list(model.design.nodes)
    while stack:
        node = stack.pop()
        chunks.append(node.name or "")
        if node.text:
            chunks.append(node.text)
        stack.extend(node.children)
    return " ".join(chunks).lower()


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Zа-яА-Я0-9]{4,}", text.lower())
    stop = {"with", "that", "this", "have", "from", "must", "should", "для", "если", "когда", "будет"}
    return [w for w in words if w not in stop][:10]


def check_consistency(model: UnifiedRequirementModel) -> dict:
    clauses = _extract_requirement_clauses(model)
    corpus = _design_corpus(model)
    findings: list[dict] = []
    if not corpus:
        return {
            "summary": {"missing": 0, "contradiction": 0, "ambiguity": len(clauses)},
            "findings": [
                {
                    "type": "ambiguity",
                    "source": c["source"],
                    "requirement": c["text"],
                    "reason": "Figma corpus is empty, cannot verify requirement against design",
                }
                for c in clauses
            ],
        }

    positive_tokens = {"must", "required", "visible", "enabled", "обязательно", "включен", "показан"}
    negative_tokens = {"optional", "hidden", "disabled", "необязательно", "скрыт", "выключен"}
    ambiguity_markers = {"tbd", "todo", "to do", "нужно уточнить", "уточнить"}

    for clause in clauses:
        text = clause["text"]
        normalized = text.lower()
        keys = _keywords(normalized)
        hit_count = sum(1 for key in keys if key in corpus)
        if hit_count == 0 and keys:
            findings.append(
                {
                    "type": "missing",
                    "source": clause["source"],
                    "requirement": text,
                    "reason": "No matching keywords found in Figma texts",
                }
            )

        has_positive = any(token in normalized for token in positive_tokens)
        has_negative_in_design = any(token in corpus for token in negative_tokens)
        has_negative = any(token in normalized for token in negative_tokens)
        has_positive_in_design = any(token in corpus for token in positive_tokens)
        if (has_positive and has_negative_in_design) or (has_negative and has_positive_in_design):
            findings.append(
                {
                    "type": "contradiction",
                    "source": clause["source"],
                    "requirement": text,
                    "reason": "Opposite state tokens detected between requirement and design corpus",
                }
            )

        if len(keys) < 2 or any(marker in normalized for marker in ambiguity_markers):
            findings.append(
                {
                    "type": "ambiguity",
                    "source": clause["source"],
                    "requirement": text,
                    "reason": "Requirement is too vague for deterministic validation",
                }
            )

    missing = len([f for f in findings if f["type"] == "missing"])
    contradiction = len([f for f in findings if f["type"] == "contradiction"])
    ambiguity = len([f for f in findings if f["type"] == "ambiguity"])
    return {"summary": {"missing": missing, "contradiction": contradiction, "ambiguity": ambiguity}, "findings": findings}
