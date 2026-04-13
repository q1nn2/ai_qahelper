from __future__ import annotations

import json
from pathlib import Path

from ai_qahelper.models import TestAnalysisReport as AnalysisReport
from ai_qahelper.models import TestCase as RequirementTestCase

_ROOT = Path(__file__).resolve().parents[2]


def test_sample_output_test_cases_json_validates() -> None:
    p = _ROOT / "examples" / "sample-output" / "test-cases.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for item in data:
        RequirementTestCase.model_validate(item)


def test_sample_output_test_analysis_json_validates() -> None:
    p = _ROOT / "examples" / "sample-output" / "test-analysis.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    AnalysisReport.model_validate(data)
