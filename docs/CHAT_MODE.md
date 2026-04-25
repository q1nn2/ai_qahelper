# Chat Mode

Chat mode запускает Streamlit UI, где можно писать QA-задачи обычным языком, загружать требования и продолжать работу с уже созданной сессией.

## Запуск

```bash
ai-qahelper chat
```

Или отдельной командой:

```bash
ai-qahelper-chat
```

Если console scripts не попали в `PATH`, используйте:

```bash
python -m ai_qahelper.cli chat
```

## Sidebar

В боковой панели задаётся контекст запуска:

- файлы требований: `.md`, `.txt`, `.pdf`, `.docx`, `.xlsx`, `.xls`;
- `Target URL` для стенда или сайта;
- `Figma file key`, если нужен макет через API;
- `Session ID`, чтобы продолжить существующую сессию;
- `max_cases`;
- `output`: `testcases` или `checklist`;
- настройки Site Discovery: `max_pages`, `max_depth`, `same_domain_only`, `use_playwright`, `timeout_seconds`, screenshots;
- Google Sheets URLs для синхронизации отчётов.

## Natural Language Planner

Агент понимает обычные фразы и строит план действий: ingest требований, site discovery, генерация test cases/checklists, bug drafts, подготовка или запуск автотестов, синхронизация с Google Sheets.

Если LLM planner недоступен или вернул некорректный JSON, chat-agent переключается на базовое распознавание команд по ключевым словам и показывает предупреждение.

Опасные действия требуют confirmation: запуск автотестов и операции, которые могут менять внешние Google Sheets.

## Примеры

Есть требования:

```text
Вот requirements.docx. Сделай профессиональные тест-кейсы без дублей.
```

Нет требований, есть сайт:

```text
Требований нет. Вот сайт https://example.com. Пройди до 5 страниц и сделай smoke + negative тест-кейсы.
```

Сложная команда:

```text
Посмотри требования, найди риски, сначала сделай smoke, потом negative cases, затем подготовь черновики багов.
```

Продолжение по session id:

```text
Продолжи сессию 20260426-example-com-ci-smoke и сделай checklist.
```
