from __future__ import annotations

from pathlib import Path

import yaml

from ai_qahelper.config import (
    get_openai_api_key,
    is_placeholder_api_key,
    load_config,
    save_openai_api_key_to_env,
    set_runtime_openai_api_key,
)
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


def test_is_placeholder_api_key_detects_missing_and_placeholder_values() -> None:
    assert is_placeholder_api_key(None) is True
    assert is_placeholder_api_key("") is True
    assert is_placeholder_api_key("your_key_here") is True
    assert is_placeholder_api_key("sk-...") is True
    assert is_placeholder_api_key("placeholder") is True
    assert is_placeholder_api_key("realistic_long_key_value") is False


def test_save_openai_api_key_to_env_creates_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"

    save_openai_api_key_to_env("realistic_long_key_value", env_path)

    assert env_path.read_text(encoding="utf-8") == "OPENAI_API_KEY=realistic_long_key_value\n"


def test_save_openai_api_key_to_env_replaces_existing_key_without_duplication(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OTHER_VAR=keep\nOPENAI_API_KEY=old_value\nSECOND_VAR=also_keep\nOPENAI_API_KEY=duplicate\n",
        encoding="utf-8",
    )

    save_openai_api_key_to_env("realistic_long_key_value", env_path)

    text = env_path.read_text(encoding="utf-8")
    assert text.count("OPENAI_API_KEY=") == 1
    assert "OPENAI_API_KEY=realistic_long_key_value\n" in text
    assert "OTHER_VAR=keep\n" in text
    assert "SECOND_VAR=also_keep\n" in text


def test_get_openai_api_key_returns_runtime_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "realistic_long_key_value")

    assert get_openai_api_key() == "realistic_long_key_value"


def test_get_openai_api_key_ignores_placeholder(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-...")

    assert get_openai_api_key() is None


def test_set_runtime_openai_api_key_writes_to_environment(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    set_runtime_openai_api_key("realistic_long_key_value")

    assert get_openai_api_key() == "realistic_long_key_value"
