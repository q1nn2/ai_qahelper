# AI QAHelper

## Самый простой запуск

Windows PowerShell:

```bash
git clone https://github.com/q1nn2/ai_qahelper.git
cd ai_qahelper
.\run_chat_windows.bat
```

Windows cmd:

```bat
git clone https://github.com/q1nn2/ai_qahelper.git
cd ai_qahelper
run_chat_windows.bat
```

macOS/Linux:

```bash
git clone https://github.com/q1nn2/ai_qahelper.git
cd ai_qahelper
chmod +x run_chat.sh
./run_chat.sh
```

Launcher сам создаст `.venv`, установит зависимости, создаст `ai-tester.config.yaml`, предложит ввести `OPENAI_API_KEY` и откроет chat mode в браузере.

Если нажать Enter и не вводить ключ в терминале, приложение всё равно откроется. UI покажет блок настройки AI и позволит вставить ключ прямо в браузере.

Если нужно принудительно переустановить зависимости:

```powershell
.\run_chat_windows.bat --reinstall
```

macOS/Linux:

```bash
./run_chat.sh --reinstall
```

## Как добавить OPENAI_API_KEY

Рекомендуемый способ для новичка — через браузер:

1. Запустите `.\run_chat_windows.bat` в PowerShell, `run_chat_windows.bat` в cmd или `./run_chat.sh` на macOS/Linux.
2. Откройте UI.
3. Вставьте ключ в поле `OPENAI_API_KEY`.
4. Включите `Сохранить ключ в локальный .env`, если не хотите вводить ключ при каждом запуске.
5. Нажмите `Сохранить ключ`.

Через `.env` в корне проекта:

```env
OPENAI_API_KEY=sk-...
```

Через переменную окружения:

Windows:

```bash
set OPENAI_API_KEY=sk-...
```

macOS/Linux:

```bash
export OPENAI_API_KEY=sk-...
```

Замените `sk-...` на реальный ключ. Файл `.env` не коммитится, ключ не показывается в UI после сохранения и не пишется в логи.

## Что это

AI QAHelper — локальный AI QA ассистент, который помогает тестировщику готовить тестовую документацию по требованиям или по фактическому сайту без требований.

Он умеет читать требования из файлов и URL, анализировать сайт без требований, coverage-first генерировать test cases и checklists, удалять дубли, проверять покрытие/качество документации и экспортировать результаты в XLSX/CSV/JSON.

Это не замена тестировщика и не полностью автономный AI, а помощник для ускорения QA analysis и test design. Результаты требуют QA review.

## Основные возможности

- Natural language chat.
- Workflow UI: `Project Setup`, карточки coverage-first генерации, отдельный `Coverage` dashboard.
- Agent Memory для продолжения текущей QA-сессии.
- Requirements ingestion: `.md`, `.txt`, `.pdf`, `.docx`, `.xlsx`, `.xls`, URL.
- DOCX: текст, таблицы и изображения через vision.
- Site Discovery Mode для сайта без требований.
- Coverage-first генерация test cases и checklists: пользователь не задаёт количество проверок, агент сам определяет нужный объём по требованиям и test conditions.
- Локальная deduplication без LLM.
- `coverage-report.json` с покрытием требований, test conditions и gaps/risks.
- Documentation Quality Gate без LLM.
- XLSX/CSV/JSON exports.
- Optional Playwright/pytest starter tests.
- Optional Google Sheets sync.

## Стоимость и LLM-вызовы

Многостраничный UI разделяет локальную работу с артефактами и AI-действия. Вкладки `Dashboard`, `Test Cases`, `Checklist`, `Quality`, `Review`, `Export` и `Settings` открываются локально: просмотр JSON, фильтрация, редактирование таблиц, сохранение `*.edited.json`, утверждение `*.final.json`, экспорт XLSX и локальная проверка качества не вызывают LLM и не расходуют токены.

LLM вызывается только после явного действия пользователя: кнопок с пометкой `через AI` или отправки сообщения во вкладке `Generate`. Локальная проверка качества бесплатная; `Глубокий AI-анализ качества`, поиск серых зон и AI-улучшения используют LLM и могут увеличить стоимость.

## Настраиваемые шаблоны документации

QAHelper использует базовый шаблон колонок для test cases, checklist и bug reports, но его можно настроить без ручного YAML. Во вкладке `Settings` → `Templates` выберите тип документации и отметьте нужные колонки галочками. Обязательные колонки всегда включены и не отключаются: для test cases это `ID`, `Название тест-кейса`, `Описание шагов`, `Ожидаемый результат`; для checklist — `ID`, `Проверка`, `Ожидаемый результат`; для bug reports — `ID`, `Название БР`, `Шаги воспроизведения`, `Ожидаемый результат`, `Фактический результат`.

Шаблон сохраняется в `templates/user_templates/<artifact_type>_template.json`, а для активной сессии может быть сохранён в `runs/<session_id>/template_settings.json`. Приоритет такой: шаблон сессии, пользовательский шаблон, затем базовый QAHelper template. Выбранный шаблон влияет на prompt генерации, порядок и названия колонок в XLSX/CSV export, отображение таблиц в UI и Quality Gate: обязательные поля активного шаблона проверяются строго, а отключённые optional-поля не блокируют качество.

## Быстрый старт

Ручной запуск для тех, кто хочет управлять окружением сам.

Windows:

```bash
git clone https://github.com/q1nn2/ai_qahelper.git
cd ai_qahelper
python -m venv .venv
.venv\Scripts\activate
pip install -e .
copy ai-tester.config.example.yaml ai-tester.config.yaml
set OPENAI_API_KEY=sk-...
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
export OPENAI_API_KEY=sk-...
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

После успешного действия интерфейс показывает блок "Что можно сделать дальше": negative cases, чек-лист, bug reports, autotests, export или quality report. Coverage metrics доступны на вкладках `Dashboard` и `Coverage`. Для созданных JSON/Markdown/CSV/XLSX файлов отображаются путь и кнопка скачивания, а для Markdown/JSON ещё и короткий preview.

## Что будет на выходе

Все файлы сохраняются в `runs/<session_id>/`.

| Файл | Для чего |
|------|----------|
| `test-cases.xlsx` | Основной Excel-файл с тест-кейсами |
| `checklist.xlsx` | Основной Excel-файл с чек-листом |
| `input-coverage-report.json` | Что агент увидел во входных файлах |
| `coverage-report.json` | Покрытие требований/test conditions итоговой документацией и gaps |
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
