from __future__ import annotations

from pathlib import Path

from ai_qahelper import models as aq_models
from ai_qahelper.reporting import (
    export_test_cases_local,
    flatten_cell_for_csv,
    format_steps_for_export,
)
from ai_qahelper.template_service import default_template


def test_format_steps_for_export_numbers_and_strips_enum() -> None:
    s = format_steps_for_export(["  1. First ", "2. Second", "plain"])
    assert "1. First" in s
    assert "2. Second" in s
    assert "3. plain" in s
    assert s.count("\n") == 2


def test_flatten_cell_for_csv() -> None:
    assert flatten_cell_for_csv("a\nb\nc") == "a | b | c"
    assert flatten_cell_for_csv("") == ""


def test_export_csv_single_physical_row_per_case(tmp_path: Path) -> None:
    tc = aq_models.TestCase(
        case_id="TC-001",
        title="T",
        preconditions="P",
        steps=["One", "Two"],
        expected_result="E",
        note="N",
    )
    csv_path, _ = export_test_cases_local(tmp_path, [tc])
    lines = csv_path.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("sep=,")
    assert len(lines) == 3


def test_export_uses_template_labels_and_skips_disabled_columns(tmp_path: Path) -> None:
    tc = aq_models.TestCase(
        case_id="TC-001",
        title="T",
        preconditions="P",
        steps=["One", "Two"],
        expected_result="E",
        note="N",
    )
    template = default_template("test_cases")
    template.columns = [
        column.model_copy(update={"enabled": column.required or column.key == "priority"})
        for column in template.columns
    ]

    csv_path, _ = export_test_cases_local(tmp_path, [tc], template=template)
    text = csv_path.read_text(encoding="utf-8-sig")

    assert "Название тест-кейса" in text
    assert "Приоритет" in text
    assert "Предусловия" not in text
