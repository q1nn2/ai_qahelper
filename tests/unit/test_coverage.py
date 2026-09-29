from __future__ import annotations

from ai_qahelper.coverage import build_coverage_report, coverage_needs_more_cases
from ai_qahelper.models import (
    AnalysisTestCondition,
    RequirementItem,
    TestAnalysisReport,
    TestCase,
    UnifiedRequirementModel,
)


def test_coverage_report_marks_requirements_and_conditions() -> None:
    model = UnifiedRequirementModel(
        requirements=[RequirementItem(source="req.md", content="Login")],
        target_url="https://example.com",
    )
    analysis = TestAnalysisReport(
        test_conditions=[
            AnalysisTestCondition(
                id="COND-001",
                description="Valid login",
                technique_id="TECH-01",
                requirement_ref="REQ-001",
            )
        ]
    )
    cases = [
        TestCase(
            case_id="TC-001",
            title="Успешный логин",
            steps=["Ввести валидные данные"],
            expected_result="Открыт кабинет",
            source_refs=["REQ-001", "COND-001"],
        )
    ]

    report = build_coverage_report(model, analysis, cases, dedup_report={"removed": 2})

    assert report["summary"]["requirements_total"] == 1
    assert report["summary"]["requirements_covered"] == 1
    assert report["summary"]["test_conditions_covered"] == 1
    assert report["summary"]["duplicates_removed"] == 2
    assert coverage_needs_more_cases(report) is False


def test_coverage_report_flags_uncovered_conditions() -> None:
    model = UnifiedRequirementModel(
        requirements=[RequirementItem(source="req.md", content="Login")],
        target_url="https://example.com",
    )
    analysis = TestAnalysisReport(
        test_conditions=[
            AnalysisTestCondition(id="COND-001", description="Valid login", technique_id="TECH-01", requirement_ref="REQ-001")
        ]
    )

    report = build_coverage_report(model, analysis, [], dedup_report=None)

    assert report["summary"]["requirements_uncovered"] == 1
    assert report["test_conditions"][0]["status"] == "uncovered"
    assert coverage_needs_more_cases(report) is True
