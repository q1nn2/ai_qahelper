from __future__ import annotations

from pathlib import Path

from ai_qahelper.models import (
    AnalysisTestCondition,
    RequirementItem,
    TestAnalysisReport,
    TestCase,
    UnifiedRequirementModel,
)
from ai_qahelper.qa_analysis import (
    build_requirements_classification,
    build_requirements_review,
    build_traceability_matrix,
    export_traceability_matrix_xlsx,
    render_requirements_review_markdown,
)


def _model() -> UnifiedRequirementModel:
    return UnifiedRequirementModel(
        requirements=[
            RequirementItem(
                source="req.md",
                content="Форма логина должна валидировать обязательное поле Email и показывать ошибку.",
            ),
            RequirementItem(
                source="req.md",
                content="Администратор может открыть страницу управления пользователями.",
            ),
        ],
        target_url="https://example.com",
    )


def test_requirements_classification_detects_validation_and_roles() -> None:
    classification = build_requirements_classification(_model())

    first, second = classification["items"]
    assert first["primary_category"] == "validation_rule"
    assert "ui_requirement" in first["categories"]
    assert "role_permission" in second["categories"]
    assert classification["summary"]["requirements_total"] == 2


def test_requirements_review_creates_gap_questions() -> None:
    model = _model()
    classification = build_requirements_classification(model)

    review = build_requirements_review(model, classification)
    markdown = render_requirements_review_markdown(review)

    assert review["summary"]["findings_total"] >= 1
    assert any(item["type"] == "missing_boundary_rule" for item in review["findings"])
    assert "Question:" in markdown


def test_traceability_matrix_links_requirements_conditions_and_cases(tmp_path: Path) -> None:
    model = _model()
    classification = build_requirements_classification(model)
    review = build_requirements_review(model, classification)
    analysis = TestAnalysisReport(
        test_conditions=[
            AnalysisTestCondition(
                id="COND-001",
                description="Пустой Email показывает ошибку",
                technique_id="validation",
                requirement_ref="REQ-001",
            ),
            AnalysisTestCondition(
                id="COND-002",
                description="Администратор открывает управление пользователями",
                technique_id="role",
                requirement_ref="REQ-002",
            ),
        ]
    )
    cases = [
        TestCase(
            case_id="TC-001",
            title="Ошибка при пустом Email",
            preconditions="Открыта форма логина",
            steps=["Оставить Email пустым", "Нажать кнопку входа"],
            expected_result="Отображается сообщение об обязательном Email",
            source_refs=["REQ-001", "COND-001"],
        )
    ]

    matrix = build_traceability_matrix(model, analysis, cases, classification, review)
    xlsx_path = export_traceability_matrix_xlsx(tmp_path / "traceability-matrix.xlsx", matrix)

    assert matrix["summary"]["requirements_total"] == 2
    assert matrix["summary"]["conditions_covered"] == 1
    assert matrix["requirements"][0]["covered_by"] == "TC-001"
    assert matrix["requirements"][1]["status"] in {"missing", "partial", "unclear"}
    assert xlsx_path.is_file()
