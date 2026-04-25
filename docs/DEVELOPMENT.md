# Development

## Установка dev-зависимостей

```bash
pip install -e ".[dev]"
```

Для Playwright/pytest автотестов:

```bash
pip install -e ".[autotest]"
```

## Проверки

```bash
python -m pytest tests -v
python -m ruff check src tests
```

Интеграционный smoke с реальным LLM выполняется только при наличии `OPENAI_API_KEY` и `ai-tester.config.yaml` в корне репозитория.

## Структура проекта

- `src/ai_qahelper/` — основной код CLI, chat mode и сервисов;
- `src/ai_qahelper/inputs.py` — чтение входных требований;
- `src/ai_qahelper/docs_service.py` — генерация документации и сохранение артефактов;
- `src/ai_qahelper/testdocs.py` — prompts и вызовы LLM для test cases/checklists;
- `src/ai_qahelper/deduplication.py` — локальный dedup test cases;
- `src/ai_qahelper/documentation_quality.py` — локальный Documentation Quality Gate;
- `src/ai_qahelper/site_discovery.py` — Site Discovery Mode;
- `src/ai_qahelper/reporting.py` — CSV/XLSX/JSON export;
- `tests/unit/` — unit tests;
- `tests/integration/` — integration smoke tests;
- `examples/minimal/` — минимальные входы;
- `examples/sample-output/` — пример артефактов;
- `examples/input/` — удобная папка для пользовательских требований;
- `runs/` — реальные результаты запусков.

## Что не коммитить

Не коммитьте:

- `.env`;
- `ai-tester.config.yaml`;
- `runs/*`, кроме `runs/.gitkeep`;
- service account JSON;
- реальные API keys, tokens, credentials;
- локальные кэши Python/pytest/ruff.

## Быстрый цикл разработки

```bash
python -m ruff check src tests
python -m pytest tests -v
```

Если менялись docs-only файлы, запуск тестов обычно не обязателен, но полезно проверить Markdown-ссылки вручную.
