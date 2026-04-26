# Configuration

Основной конфиг проекта — `ai-tester.config.yaml`. Его создают из примера:

```bash
copy ai-tester.config.example.yaml ai-tester.config.yaml
```

Unix:

```bash
cp ai-tester.config.example.yaml ai-tester.config.yaml
```

`ai-tester.config.yaml` не нужно коммитить: он может содержать локальные настройки и секреты.

## API keys

OpenAI-compatible ключ можно задать через `.env` в корне проекта:

```env
OPENAI_API_KEY=sk-...
```

`python-dotenv` загружает `.env` без перезаписи уже заданных системных переменных, поэтому порядок такой:

1. системная/пользовательская переменная окружения;
2. значение из `.env`;
3. `llm.api_key` в локальном `ai-tester.config.yaml`, если вы явно его добавили.

Также ключ можно задать через переменную окружения:

```bash
set OPENAI_API_KEY=your_key_here
```

Unix:

```bash
export OPENAI_API_KEY=your_key_here
```

В конфиге поле `llm.api_key_env` должно быть именем переменной, например `OPENAI_API_KEY`, а не самим секретом.

Если ключа нет, chat mode покажет ошибку `Не найден OPENAI_API_KEY` и пример исправления.

## Основные параметры

- `llm.model` — модель для текстовой генерации.
- `llm.base_url` — OpenAI-compatible endpoint.
- `llm.max_test_cases` — количество test cases по умолчанию.
- `llm.max_output_tokens` — лимит ответа модели.
- `llm.max_requirement_chars_per_source` — лимит текста одного источника в prompt.
- `generate_test_analysis` — отдельный LLM-шаг тест-анализа перед генерацией.
- `generate_bug_templates` — генерация черновиков bug reports.
- `sessions_dir` — папка с результатами запусков.
- `envs` — allowlist окружений: host из `target_url` должен совпадать с одним из `base_url`.

## Vision

PDF:

- `pdf_vision` — включить описание визуальных страниц PDF;
- `llm.pdf_vision_max_pages`;
- `llm.pdf_vision_pages_per_request`;
- `llm.pdf_vision_max_output_tokens`;
- `llm.pdf_vision_render_scale`.

DOCX:

- `llm.docx_vision` — анализировать изображения из Word;
- `llm.docx_vision_max_images`;
- `llm.docx_vision_images_per_request`;
- `llm.docx_vision_max_output_tokens`.

Если vision выключен или упал, агент добавит warning и риск неполного покрытия в `input-coverage-report.json`.

## Google Sheets

Для синхронизации с Google Sheets нужен service account JSON. Путь задаётся переменной окружения:

```bash
set GOOGLE_SERVICE_ACCOUNT_JSON=C:\path\to\service-account.json
```

Unix:

```bash
export GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/service-account.json
```

## Figma

Для чтения Figma через API нужен:

```bash
set FIGMA_API_TOKEN=your_token_here
```

Unix:

```bash
export FIGMA_API_TOKEN=your_token_here
```

## Troubleshooting

В chat mode пользователь видит понятное сообщение об ошибке, а техническая деталь остаётся в expander `Техническая информация`.

- `Не найден OPENAI_API_KEY`: добавьте ключ в `.env` или переменную окружения. Пример: `OPENAI_API_KEY=sk-...`.
- `Не загружены требования`: загрузите `.docx`, `.pdf`, `.xlsx` файл или вставьте ссылку на требования.
- `Не указан Target URL`: вставьте ссылку на тестируемый сайт в боковой панели.
- `Не удалось прочитать файл`: проверьте путь, расширение и доступ к файлу; если файл открыт в Excel/Word, закройте его и загрузите заново.
- `Не удалось запустить Playwright`: установите зависимости `pip install -e .[autotest]` и браузеры `playwright install`.
- `Не удалось выгрузить в Google Sheets`: проверьте ссылки на таблицы, доступ service account и `GOOGLE_SERVICE_ACCOUNT_JSON`.

## Рекомендуемые профили

Cheap:

```yaml
llm:
  max_test_cases: 5
generate_test_analysis: false
pdf_vision: false
```

В этом режиме также можно поставить `llm.docx_vision: false`.

Normal:

```yaml
llm:
  max_test_cases: 10
  docx_vision: true
generate_test_analysis: true
pdf_vision: true
```

Deep:

```yaml
llm:
  max_test_cases: 30
  docx_vision: true
  docx_vision_max_images: 30
generate_test_analysis: true
pdf_vision: true
```

Отдельного `budget_mode` в коде нет: это просто рекомендуемые настройки.
