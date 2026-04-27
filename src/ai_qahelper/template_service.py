from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ArtifactType = Literal["test_cases", "checklist", "bug_reports"]

_ARTIFACT_ALIASES = {
    "testcases": "test_cases",
    "test-cases": "test_cases",
    "test_cases": "test_cases",
    "checklist": "checklist",
    "bugreports": "bug_reports",
    "bug-reports": "bug_reports",
    "bug_reports": "bug_reports",
}


class TemplateColumn(BaseModel):
    key: str
    label: str
    required: bool
    enabled: bool
    type: str = "text"
    allowed_values: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def required_columns_are_enabled(self) -> "TemplateColumn":
        if self.required:
            self.enabled = True
        return self


class DocumentationTemplate(BaseModel):
    name: str
    artifact_type: ArtifactType
    columns: list[TemplateColumn]

    @model_validator(mode="after")
    def keep_required_columns_enabled(self) -> "DocumentationTemplate":
        self.columns = [column.model_copy(update={"enabled": True}) if column.required else column for column in self.columns]
        return self


def normalize_artifact_type(artifact_type: str) -> ArtifactType:
    normalized = _ARTIFACT_ALIASES.get((artifact_type or "").strip().lower().replace(" ", "_"))
    if normalized not in {"test_cases", "checklist", "bug_reports"}:
        raise ValueError(f"Unknown documentation artifact type: {artifact_type}")
    return normalized  # type: ignore[return-value]


def default_template(artifact_type: str) -> DocumentationTemplate:
    artifact = normalize_artifact_type(artifact_type)
    if artifact == "test_cases":
        return DocumentationTemplate(
            name="QAHelper базовый test cases",
            artifact_type="test_cases",
            columns=[
                _col("case_id", "ID", True),
                _col("title", "Название тест-кейса", True),
                _col("steps", "Описание шагов", True, type_="list"),
                _col("expected_result", "Ожидаемый результат", True),
                _col("preconditions", "Предусловия", False, enabled=True),
                _col("environment", "Окружение", False, enabled=True),
                _col(
                    "status",
                    "Статус",
                    False,
                    enabled=True,
                    allowed_values=["Draft", "Needs review", "Approved", "blocked", "passed", "failed"],
                ),
                _col("bug_report_id", "ID баг-репорта", False, enabled=True),
                _col("notes", "Примечание", False, enabled=True),
                _col("priority", "Приоритет", False, allowed_values=["low", "medium", "high", "critical"]),
                _col("module", "Модуль", False),
                _col("test_type", "Тип проверки", False),
                _col("requirement_id", "Requirement ID", False),
                _col("test_data", "Тестовые данные", False),
                _col("automation_candidate", "Кандидат на автоматизацию", False),
            ],
        )
    if artifact == "checklist":
        return DocumentationTemplate(
            name="QAHelper базовый checklist",
            artifact_type="checklist",
            columns=[
                _col("item_id", "ID", True),
                _col("check", "Проверка", True),
                _col("expected_result", "Ожидаемый результат", True),
                _col("module", "Модуль", False, enabled=True),
                _col("priority", "Приоритет", False, enabled=True, allowed_values=["low", "medium", "high", "critical"]),
                _col("status", "Статус", False, allowed_values=["Draft", "Needs review", "Approved"]),
                _col("requirement_id", "Requirement ID", False),
                _col("notes", "Примечание", False, enabled=True),
                _col("test_type", "Тип проверки", False),
            ],
        )
    return DocumentationTemplate(
        name="QAHelper базовый bug reports",
        artifact_type="bug_reports",
        columns=[
            _col("bug_id", "ID", True),
            _col("title", "Название БР", True),
            _col("steps", "Шаги воспроизведения", True, type_="list"),
            _col("expected_result", "Ожидаемый результат", True),
            _col("actual_result", "Фактический результат", True),
            _col("status", "Статус", False, enabled=True, allowed_values=["Draft", "Needs review", "Approved", "Open", "Closed"]),
            _col("priority", "Приоритет", False, enabled=True, allowed_values=["low", "medium", "high", "urgent"]),
            _col("severity", "Серьёзность", False, enabled=True, allowed_values=["minor", "major", "critical", "blocker"]),
            _col("preconditions", "Предусловия", False, enabled=True),
            _col("environment", "Окружение", False),
            _col("comment", "Комментарий", False),
            _col("attachment", "Вложение/скриншот", False),
        ],
    )


def enabled_columns(template: DocumentationTemplate) -> list[TemplateColumn]:
    return [column for column in template.columns if column.enabled or column.required]


def required_columns(template: DocumentationTemplate) -> list[TemplateColumn]:
    return [column for column in template.columns if column.required]


def user_template_path(artifact_type: str) -> Path:
    return Path("templates") / "user_templates" / f"{normalize_artifact_type(artifact_type)}_template.json"


def session_template_path(session_id: str) -> Path:
    return _session_dir(session_id) / "template_settings.json"


def load_active_template(artifact_type: str, session_id: str | None = None) -> DocumentationTemplate:
    artifact = normalize_artifact_type(artifact_type)
    if session_id:
        session_templates = _load_session_templates(session_id)
        if artifact in session_templates:
            return _merge_with_default(session_templates[artifact], artifact)
    path = user_template_path(artifact)
    if path.is_file():
        return _merge_with_default(DocumentationTemplate.model_validate_json(path.read_text(encoding="utf-8")), artifact)
    return default_template(artifact)


def save_user_template(template: DocumentationTemplate) -> Path:
    normalized = _merge_with_default(template, template.artifact_type)
    path = user_template_path(normalized.artifact_type)
    _save_template(path, normalized)
    return path


def save_session_template(session_id: str, template: DocumentationTemplate) -> Path:
    artifact = normalize_artifact_type(template.artifact_type)
    templates = _load_session_templates(session_id)
    templates[artifact] = _merge_with_default(template, artifact)
    path = session_template_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: value.model_dump(mode="json") for key, value in templates.items()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def reset_user_template(artifact_type: str) -> Path:
    template = default_template(artifact_type)
    return save_user_template(template)


def build_template_prompt_hint(template: DocumentationTemplate) -> str:
    cols = enabled_columns(template)
    mapping = "; ".join(f"{column.key} → «{column.label}»" for column in cols)
    required = ", ".join(column.key for column in required_columns(template))
    return (
        "Используй активный шаблон документации. "
        f"Artifact type: {template.artifact_type}. "
        f"Enabled columns in exact order: {mapping}. "
        f"Required columns: {required}. "
        "Do not add fields outside enabled columns. Keep this column order. "
        "Required fields must be filled. If source data is insufficient, mark status = Needs review when status is enabled "
        "or write the gap into notes when notes is enabled. Do not create duplicates. "
        "One item = one verifiable goal. expected_result must be observable and testable."
    )


def template_record_value(record: Any, key: str) -> Any:
    if isinstance(record, BaseModel):
        data = record.model_dump(mode="json")
    elif isinstance(record, dict):
        data = record
    else:
        data = getattr(record, "__dict__", {})
    aliases = _field_aliases(key)
    for alias in aliases:
        if alias in data:
            return data[alias]
    return ""


def _col(
    key: str,
    label: str,
    required: bool,
    *,
    enabled: bool | None = None,
    type_: str = "text",
    allowed_values: list[str] | None = None,
) -> TemplateColumn:
    return TemplateColumn(
        key=key,
        label=label,
        required=required,
        enabled=required if enabled is None else enabled,
        type=type_,
        allowed_values=allowed_values or [],
    )


def _merge_with_default(template: DocumentationTemplate, artifact_type: str) -> DocumentationTemplate:
    default = default_template(artifact_type)
    by_key = {column.key: column for column in template.columns}
    merged = []
    for default_column in default.columns:
        override = by_key.get(default_column.key)
        if override is None:
            merged.append(default_column)
            continue
        merged.append(
            default_column.model_copy(
                update={
                    "label": override.label or default_column.label,
                    "enabled": True if default_column.required else override.enabled,
                    "allowed_values": override.allowed_values or default_column.allowed_values,
                    "type": override.type or default_column.type,
                }
            )
        )
    return DocumentationTemplate(name=template.name or default.name, artifact_type=default.artifact_type, columns=merged)


def _load_session_templates(session_id: str) -> dict[ArtifactType, DocumentationTemplate]:
    path = session_template_path(session_id)
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    templates: dict[ArtifactType, DocumentationTemplate] = {}
    for key, value in raw.items():
        artifact = normalize_artifact_type(key)
        if isinstance(value, dict):
            templates[artifact] = DocumentationTemplate.model_validate(value)
    return templates


def _save_template(path: Path, template: DocumentationTemplate) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.model_dump_json(indent=2), encoding="utf-8")


def _session_dir(session_id: str) -> Path:
    try:
        from ai_qahelper.session_service import session_path

        return session_path(session_id)
    except Exception:  # noqa: BLE001 - template UI should not fail if config is unavailable during tests/startup
        return Path("runs") / session_id


def _field_aliases(key: str) -> list[str]:
    aliases = {
        "notes": ["notes", "note"],
        "note": ["note", "notes"],
        "attachment": ["attachment", "attachments"],
        "attachments": ["attachments", "attachment"],
        "requirement_id": ["requirement_id", "source_refs"],
        "module": ["module", "area"],
    }
    return aliases.get(key, [key])
