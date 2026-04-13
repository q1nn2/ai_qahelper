from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


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


class AppConfig(BaseModel):
    llm: LlmConfig
    docs_dir: str = "tests/ai-docs"
    sessions_dir: str = "tests/ai-sessions"
    envs: list[EnvironmentConfig] = Field(default_factory=list)


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


class TestCase(BaseModel):
    case_id: str
    title: str
    preconditions: str
    steps: list[str]
    expected_result: str
    environment: str = "not specified"
    status: Literal["draft", "ready", "blocked", "passed", "failed"] = "draft"
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
    unified_model_path: str | None = None
    consistency_report_path: str | None = None
    test_cases_path: str | None = None
    bug_reports_path: str | None = None
    generated_tests_dir: str | None = None
    manual_results_path: str | None = None
    auto_results_path: str | None = None
    junit_report_path: str | None = None
    html_report_path: str | None = None

    def session_dir(self) -> Path:
        return Path(self.unified_model_path).parent if self.unified_model_path else Path(".")
