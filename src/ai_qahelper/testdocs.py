from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from ai_qahelper.llm_client import LlmClient
from ai_qahelper.models import BugReport, TestCase, UnifiedRequirementModel


class TestCaseList(BaseModel):
    test_cases: list[TestCase] = Field(default_factory=list)


class BugReportList(BaseModel):
    bug_reports: list[BugReport] = Field(default_factory=list)


def _model_digest(model: UnifiedRequirementModel) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2)


def _consistency_digest(consistency_report: dict[str, Any] | None) -> str:
    if not consistency_report:
        return "{}"
    return json.dumps(consistency_report, ensure_ascii=False, indent=2)


def generate_test_cases(
    llm: LlmClient,
    model: UnifiedRequirementModel,
    consistency_report: dict[str, Any] | None = None,
    max_cases: int = 30,
) -> list[TestCase]:
    class Payload(BaseModel):
        test_cases: list[TestCase]

    system = (
        "You are a senior QA engineer. "
        "Generate test cases in strict JSON only. "
        "Use the required schema fields exactly and keep steps deterministic. "
        "Write titles, preconditions, step descriptions, expected results, and notes in Russian "
        "unless the source requirements are exclusively in another language (then match that language)."
    )
    user = (
        f"Generate up to {max_cases} cases.\n"
        "Return each test case with fields: case_id, title, preconditions, steps, expected_result, "
        "environment, status, bug_report_id, note, source_refs.\n"
        "Set status to 'draft' and bug_report_id to empty string for new test cases.\n"
        "Populate note with assumptions and traceability comments.\n"
        "Each case must have deterministic, executable steps.\n"
        "Use consistency findings to prioritize missing coverage and contradiction checks.\n"
        "Each case must include source_refs to requirement sources and figma references when available.\n"
        f"Consistency report:\n{_consistency_digest(consistency_report)}\n"
        f"Unified model:\n{_model_digest(model)}"
    )
    payload = llm.complete_json(system, user, Payload)
    return payload.test_cases


def generate_bug_report_templates(llm: LlmClient, test_cases: list[TestCase], max_items: int = 20) -> list[BugReport]:
    class Payload(BaseModel):
        bug_reports: list[BugReport]

    system = (
        "You are QA lead. Generate likely bug report drafts in strict JSON. "
        "Use Russian for titles and narrative fields when test cases are in Russian."
    )
    user = (
        f"Generate up to {max_items} bug draft templates from these test cases. "
        "Do not invent impossible flows.\n"
        f"{json.dumps([c.model_dump() for c in test_cases], ensure_ascii=False)}"
    )
    payload = llm.complete_json(system, user, Payload)
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
