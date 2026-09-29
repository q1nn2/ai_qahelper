from __future__ import annotations

from ai_qahelper.friendly_errors import format_technical_error, format_user_error
from ai_qahelper.llm_client import MissingApiKeyError


def test_format_user_error_for_missing_api_key() -> None:
    message = format_user_error(MissingApiKeyError("Missing API key: OPENAI_API_KEY"))

    assert "Не найден OPENAI_API_KEY" in message
    assert "Что произошло" in message
    assert "Что сделать" in message
    assert "OPENAI_API_KEY=sk-..." in message


def test_format_user_error_for_no_requirements() -> None:
    message = format_user_error(ValueError("Загрузи требования или вставь текст требований."))

    assert "Не загружены требования" in message
    assert ".docx" in message
    assert ".pdf" in message
    assert ".xlsx" in message


def test_format_user_error_for_missing_target_url() -> None:
    message = format_user_error(ValueError("Укажи target URL для новой сессии."))

    assert "Не указан Target URL" in message
    assert "боковой панели" in message


def test_format_user_error_for_playwright() -> None:
    message = format_user_error(RuntimeError("playwright browser executable does not exist"))

    assert "Не удалось запустить Playwright" in message
    assert "pip install -e .[autotest]" in message
    assert "playwright install" in message


def test_format_user_error_for_google_sheets() -> None:
    message = format_user_error(RuntimeError("Google Sheets gspread API error"))

    assert "Не удалось выгрузить в Google Sheets" in message
    assert "service account" in message


def test_format_user_error_keeps_generic_technical_context() -> None:
    exc = RuntimeError("unexpected boom")

    assert "Не удалось выполнить действие" in format_user_error(exc)
    assert format_technical_error(exc) == "RuntimeError: unexpected boom"
