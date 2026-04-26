# Outputs

Все результаты сохраняются в папке сессии:

```text
runs/<session_id>/
```

Путь к корню сессий задаётся в `ai-tester.config.yaml` через `sessions_dir`.

## Основные файлы

| Файл | Для чего |
|------|----------|
| `session.json` | Метаданные сессии и пути к артефактам |
| `unified-model.json` | Единая модель требований, дизайна и target URL |
| `input-coverage-report.json` | Что агент увидел во входных файлах |
| `consistency-report.json` | Эвристика пропусков, противоречий и неоднозначностей |
| `test-analysis.json` | LLM test analysis и test conditions, если включён |
| `test-cases.json` | Тест-кейсы в структурированном JSON |
| `test-cases.csv` | CSV для импорта или просмотра |
| `test-cases.xlsx` | Основной Excel-файл для тестировщика |
| `checklist.json` | Чек-лист в структурированном JSON |
| `checklist.csv` | CSV-версия чек-листа |
| `checklist.xlsx` | Excel-версия чек-листа |
| `dedup-report.json` | Какие test cases были удалены как дубли |
| `test-cases-quality-report.json` | Оценка качества test cases |
| `checklist-quality-report.json` | Оценка качества checklist |
| `bug-reports.json` | Черновики bug reports, если включены |
| `bug-reports.csv` / `bug-reports.xlsx` | Экспорт bug reports |
| `site-model.json` | Модель сайта при Site Discovery |
| `exploratory-report.json` | Структурированный exploratory report |
| `exploratory-report.md` | Читаемый exploratory report |
| `generated_tests_dir` | Папка со стартовыми Playwright/pytest тестами |
| `manual-results.csv` | Шаблон или результаты ручного прогона |
| `junit_report_path` / `html_report_path` | Отчёты автотестов |

## Форматы

`xlsx` — основной формат для человека: удобно открыть в Excel и передать исполнителю.

`csv` — удобен для импорта в внешние системы и Google Sheets.

`json` — удобен для агента, автоматизации и последующей обработки.

## Focused generation

Если используется focus (`smoke`, `negative`, `regression` и т.п.), файлы получают суффикс:

```text
test-cases-smoke.json
test-cases-quality-report-smoke.json
dedup-report-smoke.json
```
