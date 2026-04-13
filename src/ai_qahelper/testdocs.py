from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from ai_qahelper.llm_client import LlmClient
from ai_qahelper.models import BugReport, LlmConfig, TestCase, UnifiedRequirementModel


class TestCaseList(BaseModel):
    test_cases: list[TestCase] = Field(default_factory=list)


class BugReportList(BaseModel):
    bug_reports: list[BugReport] = Field(default_factory=list)


def _model_digest_for_prompt(model: UnifiedRequirementModel, max_chars_per_source: int) -> str:
    data = model.model_dump(mode="json")
    for req in data.get("requirements", []):
        content = req.get("content") or ""
        if len(content) > max_chars_per_source:
            req["content"] = (
                content[:max_chars_per_source]
                + "\n\n[TRUNCATED: source is longer; base cases on the text above and standard flows.]\n"
            )
    return json.dumps(data, ensure_ascii=False, indent=2)


def _consistency_digest_for_prompt(consistency_report: dict[str, Any] | None, max_findings: int) -> str:
    if not consistency_report:
        return "{}"
    findings = consistency_report.get("findings") or []
    slim: dict[str, Any] = {
        "summary": consistency_report.get("summary", {}),
        "findings": findings[:max_findings],
    }
    if len(findings) > max_findings:
        slim["truncated_findings_note"] = f"{len(findings) - max_findings} more findings omitted"
    return json.dumps(slim, ensure_ascii=False, indent=2)


def generate_test_cases(
    llm: LlmClient,
    model: UnifiedRequirementModel,
    consistency_report: dict[str, Any] | None = None,
    max_cases: int = 30,
    *,
    llm_cfg: LlmConfig,
) -> list[TestCase]:
    class Payload(BaseModel):
        test_cases: list[TestCase]

    system = (
        "You are a senior QA engineer. "
        "You MUST respond with a single JSON object only — no markdown fences, no text before or after. "
        "The JSON must have exactly one top-level key: \"test_cases\" (array of objects). "
        "Each object uses keys: case_id, title, preconditions, steps (array of strings), expected_result, "
        "environment, status, bug_report_id, note, source_refs (array of strings). "
        "Write titles, preconditions, steps, expected results, and notes in Russian when requirements are in Russian. "
        "Steps must be concrete and executable (field names, values, expected messages)."
    )
    user = (
        f"Generate up to {max_cases} distinct, high-value test cases covering validation, main flows, and edge cases.\n"
        "Set status to \"draft\" and bug_report_id to \"\" for every case.\n"
        "environment should be the target app base URL when relevant.\n"
        "source_refs must cite requirement source paths or section hints from the unified model.\n"
        f"Consistency (subset):\n{_consistency_digest_for_prompt(consistency_report, llm_cfg.max_consistency_findings)}\n"
        f"Unified model:\n{_model_digest_for_prompt(model, llm_cfg.max_requirement_chars_per_source)}"
    )
    payload = llm.complete_json(system, user, Payload, root_list_key="test_cases")
    return payload.test_cases


def generate_bug_report_templates(
    llm: LlmClient,
    test_cases: list[TestCase],
    max_items: int = 20,
) -> list[BugReport]:
    class Payload(BaseModel):
        bug_reports: list[BugReport]

    system = (
        "You are QA lead. Reply with a single JSON object only — no markdown. "
        "Top-level key must be \"bug_reports\" (array). "
        "Use Russian for titles and narrative fields when test cases are in Russian."
    )
    user = (
        f"Generate up to {max_items} plausible bug draft templates from these test cases. "
        "Do not invent impossible flows.\n"
        f"{json.dumps([c.model_dump() for c in test_cases], ensure_ascii=False)}"
    )
    payload = llm.complete_json(system, user, Payload, root_list_key="bug_reports")
    return payload.bug_reports


def fallback_test_cases(model: UnifiedRequirementModel) -> list[TestCase]:
    items: list[TestCase] = []
    base_steps = [
        f"Open URL {model.target_url}",
        "Verify page loads without errors",
        "Verify key UI elements are visible based on requirements",
    ]
    for i, req in enumerate(model.requirements[:10], start=1):
        figma_ref = f"figma:{model.design.file_key}" if model.design else None
        refs = [req.source]
        if figma_ref:
            refs.append(figma_ref)
        items.append(
            TestCase(
                case_id=f"TC-{i:03d}",
                title=f"Requirement coverage: {req.source}",
                preconditions="Application is available",
                steps=base_steps + [f"Validate requirement text fragment: {req.content[:120]}"],
                expected_result="Requirement behavior is implemented as expected",
                environment=str(model.target_url),
                status="draft",
                bug_report_id="",
                note="Fallback case generated without LLM response",
                source_refs=refs,
            )
        )
    return items
