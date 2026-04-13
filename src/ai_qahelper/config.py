from __future__ import annotations

from pathlib import Path

import yaml

from ai_qahelper.models import AppConfig


def load_config(path: str | Path = "ai-tester.config.yaml") -> AppConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(raw)
