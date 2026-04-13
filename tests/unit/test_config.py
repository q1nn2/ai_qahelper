from __future__ import annotations

from pathlib import Path

import yaml

from ai_qahelper.config import load_config
from ai_qahelper.models import AppConfig


def test_app_config_defaults_match_dx_layout() -> None:
    cfg = AppConfig.model_validate({"llm": {"model": "gpt-4.1-mini"}})
    assert cfg.docs_dir == "examples/input"
    assert cfg.sessions_dir == "runs"


def test_load_config_minimal_yaml(tmp_path: Path) -> None:
    p = tmp_path / "ai-tester.config.yaml"
    p.write_text(
        yaml.dump(
            {
                "llm": {"model": "gpt-4.1-mini", "api_key_env": "OPENAI_API_KEY"},
                "docs_dir": "examples/input",
                "sessions_dir": "runs",
                "envs": [],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.sessions_dir == "runs"
    assert cfg.llm.model == "gpt-4.1-mini"
