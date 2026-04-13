from __future__ import annotations

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


def load_config(path: str | Path = "ai-tester.config.yaml") -> AppConfig:
    load_dotenv()
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
