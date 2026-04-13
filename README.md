# ai_qahelper

Локальный **CLI-инструмент для QA**: принимает требования (текст, PDF, URL) и при необходимости макеты (Figma или описание в `.md`), затем генерирует **тестовую документацию** и базовые артефакты для дальнейшего **ручного** или **автоматизированного** прогона.

Это не «универсальный AI, который всё тестирует сам», а **помощник для подготовки качественной тест-документации и стартовых QA-артефактов** — ровно тот объём, который уже поддерживается кодом: ingest → unified model → отчёты и кейсы → опционально manual / Playwright-шаблоны.

**Подходит для:** manual QA, QA automation, AI-assisted test design, команд, которым нужно ускорить подготовку тестов перед спринтом или релизом.

## Возможности

- Сбор требований из `.md`, `.txt`, `.pdf` и URL
- Опционально: Figma (file key + `FIGMA_API_TOKEN`) или отдельный `.md` с описанием экранов (в т.ч. из Cursor / Figma MCP)
- Единая модель требований (`unified-model.json`)
- Эвристический **consistency**-отчёт и LLM **test analysis**
- Генерация **test cases** в CSV / XLSX / JSON
- По запросу: черновики bug reports, шаблоны ручного прогона, базовые **Playwright/pytest** тесты

## Быстрый старт

```bash
git clone https://github.com/q1nn2/ai_qahelper.git
cd ai_qahelper
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux / macOS
pip install -e .
copy ai-tester.config.example.yaml ai-tester.config.yaml   # Windows
# cp ai-tester.config.example.yaml ai-tester.config.yaml   # Unix
```

Скопируйте [`.env.example`](.env.example) в `.env` или задайте переменные окружения:

```bash
set OPENAI_API_KEY=your_key_here          # Windows cmd
# export OPENAI_API_KEY=your_key_here     # Unix
```

Минимальный запуск (готовый пример требований в репозитории):

```bash
python -m ai_qahelper.cli agent-run ^
  --requirement examples/minimal/requirements.md ^
  --target-url https://example.com ^
  --max-cases 5
```

В Unix замените `^` на `\` в конце строк или пишите в одну строку.

**Результаты** появляются в `runs/<session_id>/` (путь задаётся в `ai-tester.config.yaml`, ключ `sessions_dir`).

Свои требования можно класть в `examples/input/` или указывать любой путь в `--requirement`.

## Минимальный пример требований

Файл [`examples/minimal/requirements.md`](examples/minimal/requirements.md) уже лежит в репозитории — его можно не менять для первого прогона.

## Что будет на выходе

В папке сессии (`runs/<session_id>/`), среди прочего:

| Файл | Назначение |
|------|------------|
| `unified-model.json` | Сводная модель требований и целевого URL |
| `test-analysis.json` | Тест-анализ и условия (если шаг не отключён) |
| `consistency-report.json` | Эвристика: пропуски, противоречия, неоднозначности |
| `test-cases.csv` / `.xlsx` / `.json` | Тест-кейсы под шаблон исполнителя |

Иллюстративные копии (без вызова LLM) лежат в [`examples/sample-output/`](examples/sample-output/).

## Figma

С ключом файла из URL макета (`figma.com/design/<KEY>/...`):

```bash
python -m ai_qahelper.cli agent-run ^
  --requirement examples/minimal/requirements.md ^
  --figma-file-key YOUR_FILE_KEY ^
  --target-url https://example.com
```

Нужен **`FIGMA_API_TOKEN`** (см. `.env.example`).

Без API: опишите экраны в Markdown (например, [`examples/minimal/figma-notes.md`](examples/minimal/figma-notes.md)) и передайте вторым `--requirement`.

## Основные команды

| Команда | Назначение |
|---------|------------|
| `ingest` | Собирает unified model из файлов / URL и опционально Figma |
| `generate-docs` | LLM: test analysis, test cases, опционально bug drafts |
| `agent-run` | **ingest + generate-docs** одной командой |
| `run-manual` | Шаблоны для ручного прогона |
| `generate-autotests` | Базовые Playwright/pytest файлы |
| `run-autotests` | Запуск сгенерированных тестов |
| `draft-bugs` | Черновики багов по падениям pytest |
| `sync-reports` | Выгрузка в Google Sheets (при настроенном сервисном аккаунте) |

Запуск: `python -m ai_qahelper.cli <команда> ...` (или `ai-qahelper`, если скрипт в PATH).

## Структура репозитория

- `src/ai_qahelper/` — код CLI и пайплайна  
- `tests/unit`, `tests/integration` — тесты **инструмента** (pytest)  
- `examples/minimal` — демо-входы  
- `examples/sample-output` — пример артефактов  
- `examples/input` — удобное место для ваших требований (по желанию)  
- `runs/` — **реальные** результаты ваших запусков (в git не коммитятся, кроме `.gitkeep`)

## Ограничения

- Качество тест-кейсов зависит от полноты и ясности входных требований.
- Проверки consistency / coverage — **эвристические**, не семантическая трассировка требований.
- Сгенерированные Playwright/pytest тесты — **стартовые шаблоны**, а не готовый regression suite.
- Для LLM нужен **OpenAI API key** (или совместимый endpoint в конфиге).
- Для дерева Figma через API — **Figma token**.

## Roadmap

- [ ] Улучшить генерацию локаторов и assertions в Playwright  
- [ ] Расширить unit / integration tests  
- [ ] GitHub Actions CI (уже есть базовый workflow)  
- [ ] Docker / devcontainer  
- [ ] Экспорт под TestRail / Zephyr  
- [ ] Усилить traceability requirements → test cases  
- [ ] Интерактивный режим запуска (wizard)

## Разработка

```bash
pip install -e ".[dev]"
python -m ruff check src tests
python -m pytest tests -v
```

Интеграционный smoke с реальным LLM выполняется только при наличии `OPENAI_API_KEY` и `ai-tester.config.yaml` в корне.

## Лицензия

MIT — см. [LICENSE](LICENSE).
