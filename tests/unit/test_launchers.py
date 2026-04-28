from __future__ import annotations

from pathlib import Path


def test_windows_launcher_allows_adding_api_key_in_browser() -> None:
    source = Path("run_chat_windows.bat").read_text(encoding="utf-8")

    assert "chcp 65001 >nul" in source
    assert "set PYTHONUTF8=1" in source
    assert "set PYTHONIOENCODING=utf-8" in source
    assert "нажмите Enter, чтобы добавить ключ позже через браузер" in source
    assert "OPENAI_API_KEY не введён. Приложение откроется" in source
    assert "OPENAI_API_KEY не задан." not in source


def test_windows_launcher_supports_dependency_marker_and_reinstall() -> None:
    source = Path("run_chat_windows.bat").read_text(encoding="utf-8")

    assert "--reinstall" in source
    assert ".venv\\.ai_qahelper_installed" in source
    assert "python -m pip install -e . --timeout 60 --retries 10" in source


def test_unix_launcher_allows_adding_api_key_in_browser() -> None:
    source = Path("run_chat.sh").read_text(encoding="utf-8")

    assert "нажмите Enter, чтобы добавить ключ позже через браузер" in source
    assert "OPENAI_API_KEY не введён. Приложение откроется" in source
    assert "OPENAI_API_KEY не задан." not in source
    assert "exit 1" not in source[source.index('if is_placeholder_api_key "$OPENAI_API_KEY"; then') :]


def test_unix_launcher_supports_dependency_marker_and_reinstall() -> None:
    source = Path("run_chat.sh").read_text(encoding="utf-8")

    assert "--reinstall" in source
    assert ".venv/.ai_qahelper_installed" in source
    assert "python -m pip install -e . --timeout 60 --retries 10" in source
