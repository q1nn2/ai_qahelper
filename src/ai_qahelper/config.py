from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from ai_qahelper.models import AppConfig


def _format_config_validation_error(exc: ValidationError) -> str:
    lines: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()))
        msg = err.get("msg", "")
        lower_loc = loc.lower()
        if "api_key" in lower_loc or "password" in lower_loc or "secret" in lower_loc or "token" in lower_loc:
            lines.append(f"  {loc}: {msg} (значение не показывается)")
        else:
            lines.append(f"  {loc}: {msg}")
    return "Неверный конфиг ai-tester.config.yaml:\n" + "\n".join(lines)


def load_project_env(path: str | Path = ".env") -> bool:
    """Load local .env without overriding real environment variables."""

    return load_dotenv(Path(path), override=False)


def is_placeholder_api_key(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered in {"your_key_here", "sk-..."}:
        return True
    if any(marker in lowered for marker in ("changeme", "placeholder", "example")):
        return True
    return len(text) < 20


def get_openai_api_key() -> str | None:
    load_project_env()
    value = os.environ.get("OPENAI_API_KEY")
    if is_placeholder_api_key(value):
        return None
    return value.strip() if value else None


def set_runtime_openai_api_key(value: str) -> None:
    os.environ["OPENAI_API_KEY"] = value.strip()


def save_openai_api_key_to_env(value: str, path: str | Path = ".env") -> None:
    env_path = Path(path)
    key_line = f"OPENAI_API_KEY={value.strip()}\n"
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True) if env_path.exists() else []

    replaced = False
    updated_lines: list[str] = []
    for line in lines:
        if line.lstrip().startswith("OPENAI_API_KEY="):
            if not replaced:
                updated_lines.append(key_line)
                replaced = True
            continue
        updated_lines.append(line)

    if not replaced:
        if updated_lines and not updated_lines[-1].endswith(("\n", "\r")):
            updated_lines[-1] = f"{updated_lines[-1]}\n"
        updated_lines.append(key_line)

    env_path.write_text("".join(updated_lines), encoding="utf-8")


def load_config(path: str | Path = "ai-tester.config.yaml") -> AppConfig:
    load_project_env()
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Файл конфигурации не найден: {config_path}. "
            "Скопируйте ai-tester.config.example.yaml → ai-tester.config.yaml и заполните."
        )
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Не удалось прочитать конфиг: {config_path}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Некорректный YAML в {config_path.name}: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"Корень конфига должен быть объектом (mapping), получено: {type(raw).__name__}")
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(_format_config_validation_error(exc)) from exc
