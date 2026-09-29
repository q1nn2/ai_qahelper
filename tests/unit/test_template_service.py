from __future__ import annotations

from pathlib import Path

import yaml

from ai_qahelper.template_service import (
    DocumentationTemplate,
    TemplateColumn,
    build_template_prompt_hint,
    default_template,
    enabled_columns,
    load_active_template,
    save_session_template,
    save_user_template,
)


def _configure_tmp_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = {
        "llm": {"model": "gpt-4.1-mini", "api_key_env": "OPENAI_API_KEY"},
        "docs_dir": "examples/input",
        "sessions_dir": "runs",
        "envs": [],
    }
    Path("ai-tester.config.yaml").write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
    (tmp_path / "runs" / "s1").mkdir(parents=True)


def test_default_test_case_template_contains_required_fields() -> None:
    template = default_template("test_cases")
    required = {column.key for column in template.columns if column.required}

    assert {"case_id", "title", "steps", "expected_result"}.issubset(required)


def test_required_columns_cannot_be_disabled() -> None:
    template = DocumentationTemplate(
        name="custom",
        artifact_type="test_cases",
        columns=[
            TemplateColumn(key="case_id", label="ID", required=True, enabled=False),
            TemplateColumn(key="title", label="Title", required=True, enabled=False),
            TemplateColumn(key="steps", label="Steps", required=True, enabled=False),
            TemplateColumn(key="expected_result", label="Expected", required=True, enabled=False),
        ],
    )

    assert all(column.enabled for column in template.columns)


def test_user_template_saves_and_loads(tmp_path: Path, monkeypatch) -> None:
    _configure_tmp_project(tmp_path, monkeypatch)
    template = default_template("test_cases")
    template.columns = [
        column.model_copy(update={"enabled": column.required or column.key == "priority"})
        for column in template.columns
    ]

    save_user_template(template)
    loaded = load_active_template("test_cases")

    assert "priority" in {column.key for column in enabled_columns(loaded)}
    assert "preconditions" not in {column.key for column in enabled_columns(loaded)}


def test_session_template_has_priority_over_user_template(tmp_path: Path, monkeypatch) -> None:
    _configure_tmp_project(tmp_path, monkeypatch)
    user_template = default_template("test_cases")
    user_template.columns = [
        column.model_copy(update={"enabled": column.required or column.key == "priority"})
        for column in user_template.columns
    ]
    session_template = default_template("test_cases")
    session_template.columns = [
        column.model_copy(update={"enabled": column.required or column.key == "module"})
        for column in session_template.columns
    ]

    save_user_template(user_template)
    save_session_template("s1", session_template)
    loaded = load_active_template("test_cases", "s1")

    enabled = {column.key for column in enabled_columns(loaded)}
    assert "module" in enabled
    assert "priority" not in enabled


def test_prompt_builder_includes_only_enabled_columns() -> None:
    template = default_template("test_cases")
    template.columns = [
        column.model_copy(update={"enabled": column.required or column.key == "priority"})
        for column in template.columns
    ]

    hint = build_template_prompt_hint(template)

    assert "priority" in hint
    assert "preconditions" not in hint
