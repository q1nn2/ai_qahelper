# AI QAHelper

## Что это

AI QAHelper — локальный AI QA ассистент, который помогает тестировщику готовить тестовую документацию по требованиям или по фактическому сайту без требований.

Он умеет читать требования из файлов и URL, анализировать сайт без требований, генерировать test cases и checklists, удалять дубли, проверять качество документации и экспортировать результаты в XLSX/CSV/JSON.

Это не замена тестировщика и не полностью автономный AI, а помощник для ускорения QA analysis и test design. Результаты требуют QA review.

## Основные возможности

- Natural language chat.
- Agent Memory для продолжения текущей QA-сессии.
- Requirements ingestion: `.md`, `.txt`, `.pdf`, `.docx`, `.xlsx`, `.xls`, URL.
- DOCX: текст, таблицы и изображения через vision.
- Site Discovery Mode для сайта без требований.
- Генерация test cases и checklists.
- Локальная deduplication без LLM.
- Documentation Quality Gate без LLM.
- XLSX/CSV/JSON exports.
- Optional Playwright/pytest starter tests.
- Optional Google Sheets sync.

## Быстрый старт

Windows:

```bash
git clone https://github.com/q1nn2/ai_qahelper.git
cd ai_qahelper
python -m venv .venv
.venv\Scripts\activate
pip install -e .
copy ai-tester.config.example.yaml ai-tester.config.yaml
set OPENAI_API_KEY=your_key_here
ai-qahelper chat
```

Unix:

```bash
git clone https://github.com/q1nn2/ai_qahelper.git
cd ai_qahelper
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp ai-tester.config.example.yaml ai-tester.config.yaml
export OPENAI_API_KEY=your_key_here
ai-qahelper chat
```

Если `ai-qahelper` не найден в `PATH`, используйте:

```bash
python -m ai_qahelper.cli chat
```

## Примеры запросов в чате

```text
Вот requirements.docx. Сделай профессиональные тест-кейсы без дублей.
```

```text
Вот requirements.xlsx. Сделай чек-лист и smoke test cases.
```

```text
Требований нет. Вот сайт https://example.com. Пройди по сайту и сделай smoke + negative тест-кейсы.
```

```text
Посмотри требования, найди риски, сначала сделай smoke, потом negative cases.
```

```text
Сделай тест-кейсы и покажи quality report.
```

## Как общаться с AI QAHelper обычным языком

Chat mode работает как QA-agent: он помнит текущую сессию, последние requirements, target URL, последний созданный артефакт и предлагает следующие шаги после выполнения команды. Если данных не хватает, агент задаст уточняющий вопрос вместо падения с ошибкой.

Пример диалога:

```text
Пользователь: Вот требования, сделай smoke test cases.
AI QAHelper: Построю план, создам сессию, сгенерирую smoke test cases и покажу созданные файлы.

Пользователь: Теперь сделай negative cases.
AI QAHelper: Продолжу текущую session_id и добавлю negative test cases.

Пользователь: Создай баг-репорты.
AI QAHelper: Подготовлю черновики баг-репортов по текущей сессии.

Пользователь: Покажи quality report.
AI QAHelper: Покажу путь к report и краткую JSON-сводку.

Пользователь: Подготовь автотесты, но не запускай.
AI QAHelper: Создам Playwright/pytest starter tests без запуска.
```

После успешного действия интерфейс показывает блок "Что можно сделать дальше": negative cases, чек-лист, bug reports, autotests, export или quality report. Для созданных JSON/Markdown/CSV/XLSX файлов отображаются путь и кнопка скачивания, а для Markdown/JSON ещё и короткий preview.

## Что будет на выходе

Все файлы сохраняются в `runs/<session_id>/`.

| Файл | Для чего |
|------|----------|
| `test-cases.xlsx` | Основной Excel-файл с тест-кейсами |
| `checklist.xlsx` | Основной Excel-файл с чек-листом |
| `input-coverage-report.json` | Что агент увидел во входных файлах |
| `dedup-report.json` | Какие дубли были удалены |
| `test-cases-quality-report.json` | Оценка качества тест-кейсов |
| `checklist-quality-report.json` | Оценка качества чек-листа |
| `site-model.json` | Модель сайта при Site Discovery |
| `exploratory-report.md` | Читаемый exploratory report |

## Документация

- [Chat mode](docs/CHAT_MODE.md)
- [Input formats](docs/INPUT_FORMATS.md)
- [Site Discovery](docs/SITE_DISCOVERY.md)
- [Quality Gate and Dedup](docs/QUALITY_GATE.md)
- [Outputs](docs/OUTPUTS.md)
- [Configuration](docs/CONFIG.md)
- [Development](docs/DEVELOPMENT.md)

## Ограничения

- LLM может ошибаться, результаты требуют QA review.
- `.xls` требует `xlrd`; лучше использовать `.xlsx`.
- Порядок картинок в `.docx` определяется best effort.
- Большие Excel-файлы обрезаются по лимитам с warning.
- Site Discovery работает в read-only mode и не проверяет бизнес-логику.
- Vision по PDF/DOCX зависит от модели и настроек.

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests -v
python -m ruff check src tests
```

Подробности: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Лицензия

MIT — см. [LICENSE](LICENSE).
