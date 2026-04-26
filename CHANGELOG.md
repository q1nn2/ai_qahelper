# Changelog

## [0.1.0] — 2026-04-13

Первый помеченный релиз.

### Возможности

- CLI: `ingest`, `generate-docs`, `agent-run`, manual / autotest вспомогательные команды, `sync-reports`
- Входы: `.md`, `.txt`, `.pdf`, URL; опционально Figma API или доп. `.md` с описанием макета
- Выходы: `unified-model.json`, `consistency-report.json`, `test-analysis.json` (опционально), `test-cases` CSV/XLSX/JSON
- Экспорт CSV с подсказкой `sep=,` для Excel и однострочными ячейками; XLSX с переносами строк в ячейках
- Промпты LLM с акцентом на атомарные тест-кейсы
- Примеры: `examples/minimal`, `examples/sample-output`, зафиксированный демо-прогон в `examples/demo-run`
- CI: GitHub Actions (ruff + pytest)

[0.1.0]: https://github.com/q1nn2/ai_qahelper/releases/tag/v0.1.0
