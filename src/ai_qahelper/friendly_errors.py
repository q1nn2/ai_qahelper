from __future__ import annotations

from pathlib import Path


def format_user_error(exc: Exception) -> str:
    """Convert technical exceptions into actionable user-facing messages."""

    text = str(exc)
    lowered = text.lower()
    exc_name = type(exc).__name__.lower()

    if _has_any(lowered, "openai_api_key", "api key", "missingapikeyerror"):
        return _message(
            happened="Не найден OPENAI_API_KEY.",
            why="Ключ не задан в переменных окружения и не найден в локальном `.env`.",
            action="Добавьте ключ в `.env` или задайте переменную окружения.",
            example="`OPENAI_API_KEY=sk-...`",
        )

    if _has_any(lowered, "загрузи требования", "не загружены требования", "requirement file not found", "requirements"):
        if isinstance(exc, FileNotFoundError) or "file not found" in lowered:
            return _message(
                happened="Не удалось прочитать файл требований.",
                why="Файл не найден, путь указан неверно или файл недоступен для чтения.",
                action="Загрузите файл заново через боковую панель или проверьте путь к файлу.",
                example="Загрузите `.docx`, `.pdf` или `.xlsx` файл в поле `Файлы требований`.",
            )
        return _message(
            happened="Не загружены требования.",
            why="Агенту нужен файл требований, ссылка на требования или уже созданная QA-сессия.",
            action="Загрузите `.docx`, `.pdf`, `.xlsx` файл или вставьте ссылку на требования.",
            example="Загрузите `requirements.docx` и напишите: `Сделай smoke test cases`.",
        )

    if _has_any(lowered, "target url", "target_url", "тестируемый сайт"):
        return _message(
            happened="Не указан Target URL.",
            why="Для новой сессии или Site Discovery агенту нужна ссылка на тестируемый сайт.",
            action="Вставьте ссылку на тестируемый сайт в боковой панели.",
            example="`https://example.com`",
        )

    if _has_any(lowered, "playwright", "browser", "pytest", "autotests are not generated"):
        return _message(
            happened="Не удалось запустить Playwright или автотесты.",
            why="Зависимости автотестов не установлены, браузеры Playwright не скачаны или автотесты ещё не сгенерированы.",
            action="Установите зависимости автотестов и браузеры Playwright, затем повторите запуск.",
            example="`pip install -e .[autotest]` и `playwright install`.",
        )

    if _has_any(lowered, "google sheets", "gspread", "spreadsheet", "service account", "worksheet"):
        return _message(
            happened="Не удалось выгрузить в Google Sheets.",
            why="Ссылки на таблицы неверные, нет доступа у service account или не задан `GOOGLE_SERVICE_ACCOUNT_JSON`.",
            action="Проверьте ссылки на таблицы и доступ service account.",
            example="Добавьте в `.env`: `GOOGLE_SERVICE_ACCOUNT_JSON=C:\\path\\to\\service-account.json`.",
        )

    if _has_any(lowered, "ai-tester.config", "yaml", "config") or isinstance(exc, (FileNotFoundError, OSError)):
        path_hint = _extract_path_hint(text)
        return _message(
            happened="Не удалось прочитать файл или конфиг.",
            why="Файл отсутствует, недоступен или содержит некорректный YAML/JSON.",
            action="Проверьте, что файл существует и доступен для чтения.",
            example=path_hint or "Скопируйте `ai-tester.config.example.yaml` в `ai-tester.config.yaml`.",
        )

    if _has_any(lowered, "figma"):
        return _message(
            happened="Не удалось прочитать Figma данные.",
            why="Не задан `FIGMA_API_TOKEN`, ссылка недоступна или у токена нет прав на файл.",
            action="Проверьте Figma token и доступ к файлу.",
            example="Добавьте в `.env`: `FIGMA_API_TOKEN=...`.",
        )

    if _has_any(exc_name, "apierror", "apiconnectionerror", "ratelimiterror") or _has_any(
        lowered,
        "openai",
        "rate limit",
        "connection",
        "timeout",
    ):
        return _message(
            happened="Не удалось получить ответ от LLM.",
            why="API временно недоступен, превышен лимит, неверная модель или проблема с сетью.",
            action="Проверьте ключ, модель, интернет-соединение и повторите запрос.",
            example="Проверьте `llm.model` в `ai-tester.config.yaml` и `OPENAI_API_KEY` в `.env`.",
        )

    return _message(
        happened="Не удалось выполнить действие.",
        why="Во время выполнения возникла непредвиденная техническая ошибка.",
        action="Проверьте входные данные и попробуйте ещё раз.",
        example=text or "Если ошибка повторяется, откройте техническую информацию и приложите её к issue.",
    )


def format_technical_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _message(*, happened: str, why: str, action: str, example: str) -> str:
    return "\n\n".join(
        [
            f"Что произошло: {happened}",
            f"Почему это могло случиться: {why}",
            f"Что сделать: {action}",
            f"Пример исправления: {example}",
        ]
    )


def _has_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _extract_path_hint(text: str) -> str:
    for chunk in text.replace("(", " ").replace(")", " ").split():
        candidate = chunk.strip(".,;:'\"`")
        if any(candidate.endswith(suffix) for suffix in (".yaml", ".yml", ".json", ".docx", ".pdf", ".xlsx", ".xls")):
            return f"Проверьте файл `{Path(candidate).name}`."
    return ""
