from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


def _coerce_string_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, dict):
        lines: list[str] = []
        for key, val in v.items():
            lines.append(str(key))
            if isinstance(val, (list, tuple)):
                lines.extend(str(x) for x in val)
            elif isinstance(val, dict):
                lines.append(json.dumps(val, ensure_ascii=False))
            else:
                lines.append(str(val))
        return [x for x in lines if x.strip()]
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    return [str(v).strip()] if str(v).strip() else []


# Поля TestCase, доступные для выгрузки в CSV/XLSX (заголовки задаются в test_cases_export).
TestCaseExportField = Literal[
    "case_id",
    "title",
    "preconditions",
    "steps",
    "expected_result",
    "environment",
    "status",
    "bug_report_id",
    "note",
    "source_refs",
]


class TestCaseExportColumn(BaseModel):
    field: TestCaseExportField
    header: str


class EnvironmentConfig(BaseModel):
    name: str
    base_url: HttpUrl
    api_base_url: HttpUrl | None = None


class LlmConfig(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    api_key_env: str = "OPENAI_API_KEY"
    api_key: str | None = None
    temperature: float = 0.2
    # Large PDFs need a smaller prompt; long JSON answers need a high output budget.
    max_output_tokens: int = 16384
    # 0 = не урезать текст одного источника требований в промпте; >0 — лимит символов на источник.
    max_requirement_chars_per_source: int = 0
    # 0 = отдавать в LLM все findings консистентности; >0 — только первые N.
    max_consistency_findings: int = 0
    max_test_cases: int = 30
    # 0 = не урезать JSON тест-анализа во втором промпте; >0 — лимит символов.
    max_analysis_json_chars: int = 0
    request_timeout_seconds: float = 600.0
    # Vision: описание страниц PDF с картинками (Chat Completions, модель с поддержкой изображений).
    vision_model: str = "gpt-4o-mini"
    pdf_vision_max_pages: int = 40
    pdf_vision_pages_per_request: int = 2
    pdf_vision_max_output_tokens: int = 4096
    # Vision: изображения, встроенные в Word DOCX с требованиями.
    docx_vision: bool = True
    docx_vision_max_images: int = 30
    docx_vision_images_per_request: int = 2
    docx_vision_max_output_tokens: int = 4096
    # Масштаб рендера страницы (2 ≈ ~144 DPI при 72 pt); больше — чётче, но тяжелее для API.
    pdf_vision_render_scale: float = 2.0
    # responses.create с text.format json_schema (Structured Outputs); при ошибке — fallback на разбор текста.
    use_structured_json_output: bool = True

    @model_validator(mode="after")
    def api_key_env_is_var_name(self) -> "LlmConfig":
        name = (self.api_key_env or "").strip()
        if name.startswith("sk-"):
            msg = (
                "llm.api_key_env must be a variable name (e.g. OPENAI_API_KEY), not the secret key. "
                "Put the key in llm.api_key or in .env as OPENAI_API_KEY=sk-..."
            )
            raise ValueError(msg)
        return self


class AppConfig(BaseModel):
    llm: LlmConfig
    # Рекомендуемая папка для ваших требований (путь в CLI можно указывать любой; поле для ясности в конфиге).
    docs_dir: str = "examples/input"
    sessions_dir: str = "runs"
    envs: list[EnvironmentConfig] = Field(default_factory=list)
    # Черновики багов через LLM (отдельный запрос). По умолчанию выключено — только тест-кейсы.
    generate_bug_templates: bool = False
    # Отдельный LLM-шаг: тест-анализ и техники тест-дизайна перед генерацией артефактов.
    generate_test_analysis: bool = True
    # Колонки выгрузки test-cases.csv / .xlsx; None = встроенный русскоязычный шаблон.
    test_cases_export: list[TestCaseExportColumn] | None = None
    # Рендер страниц PDF + vision-модель: дополняет текст распознаванием макетов/скриншотов (доп. запросы API).
    pdf_vision: bool = False


class RequirementItem(BaseModel):
    source: str
    content: str


class DesignNode(BaseModel):
    id: str
    name: str
    text: str | None = None
    node_type: str | None = None
    children: list["DesignNode"] = Field(default_factory=list)


class DesignModel(BaseModel):
    file_key: str
    file_name: str | None = None
    nodes: list[DesignNode] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class UnifiedRequirementModel(BaseModel):
    requirements: list[RequirementItem] = Field(default_factory=list)
    design: DesignModel | None = None
    target_url: HttpUrl


class AnalysisTechnique(BaseModel):
    """Применённая техника тест-дизайна (идентификаторы — латиница, тексты — по возможности на русском)."""

    id: str
    name: str
    rationale: str = ""


class AnalysisTestCondition(BaseModel):
    """Условие проверки, выведенное из требований и техники."""

    id: str
    description: str
    technique_id: str
    requirement_ref: str = ""


class TestAnalysisReport(BaseModel):
    """Результат тест-анализа перед генерацией документации."""

    scope: str = ""
    assumptions: str = ""
    sources_used: list[str] = Field(default_factory=list)
    risks_and_gaps: list[str] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)
    techniques: list[AnalysisTechnique] = Field(default_factory=list)
    test_conditions: list[AnalysisTestCondition] = Field(default_factory=list)

    @field_validator("sources_used", "risks_and_gaps", "inventory", mode="before")
    @classmethod
    def _normalize_str_lists(cls, v: Any) -> list[str]:
        """LLM иногда возвращает объект вместо массива строк — приводим к list[str]."""
        return _coerce_string_list(v)


class ChecklistItem(BaseModel):
    item_id: str
    area: str = ""
    check: str
    expected_result: str
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    note: str = ""
    source_refs: list[str] = Field(default_factory=list)


class TestCase(BaseModel):
    case_id: str
    title: str
    preconditions: str
    steps: list[str]
    expected_result: str
    # Пустые по умолчанию: колонки «Окружение», «Статус», «ID баг-репорта» заполняет исполнитель позже.
    environment: str = ""
    status: Literal["draft", "ready", "blocked", "passed", "failed", ""] = ""
    bug_report_id: str = ""
    note: str = ""
    source_refs: list[str] = Field(default_factory=list)


class BugReport(BaseModel):
    bug_id: str
    title: str
    severity: Literal["minor", "major", "critical", "blocker"] = "major"
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    preconditions: str
    steps: list[str]
    actual_result: str
    expected_result: str
    attachments: list[str] = Field(default_factory=list)
    linked_test_case_id: str | None = None


class ManualExecutionResult(BaseModel):
    test_case_id: str
    status: Literal["passed", "failed", "blocked"]
    notes: str = ""
    evidence_files: list[str] = Field(default_factory=list)


class AutoExecutionResult(BaseModel):
    test_case_id: str
    status: Literal["passed", "failed", "skipped"]
    test_file: str
    error: str | None = None
    artifacts: list[str] = Field(default_factory=list)


class SessionState(BaseModel):
    session_id: str
    created_at: datetime
    target_url: HttpUrl
    requirements_files: list[str] = Field(default_factory=list)
    figma_file_key: str | None = None
    site_model_path: str | None = None
    exploratory_report_path: str | None = None
    exploratory_report_md_path: str | None = None
    unified_model_path: str | None = None
    consistency_report_path: str | None = None
    test_analysis_path: str | None = None
    input_coverage_report_path: str | None = None
    quality_report_path: str | None = None
    checklist_path: str | None = None
    test_cases_path: str | None = None
    dedup_report_path: str | None = None
    bug_reports_path: str | None = None
    generated_tests_dir: str | None = None
    manual_results_path: str | None = None
    auto_results_path: str | None = None
    junit_report_path: str | None = None
    html_report_path: str | None = None

    def session_dir(self) -> Path:
        return Path(self.unified_model_path).parent if self.unified_model_path else Path(".")
