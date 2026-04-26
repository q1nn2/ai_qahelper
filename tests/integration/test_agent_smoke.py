from __future__ import annotations

import os
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HAS_KEY = bool((os.getenv("OPENAI_API_KEY") or "").strip())
_HAS_CONFIG = (_ROOT / "ai-tester.config.yaml").is_file()

pytestmark = pytest.mark.skipif(
    not _HAS_KEY or not _HAS_CONFIG,
    reason="Нужны OPENAI_API_KEY и ai-tester.config.yaml в корне репозитория",
)


def test_agent_run_minimal_example_smoke() -> None:
    """Полный ingest + generate-docs (LLM). В CI по умолчанию пропускается."""
    from ai_qahelper.orchestrator import agent_run

    req = _ROOT / "examples" / "minimal" / "requirements.md"
    assert req.is_file()
    out = agent_run(
        [str(req)],
        [],
        None,
        target_url="https://example.com",
        max_cases=2,
        skip_test_analysis=True,
        session_label="ci-smoke",
    )
    assert out["session_id"]
    assert Path(out["test_cases_path"]).is_file()
