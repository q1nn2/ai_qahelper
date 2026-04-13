# ai_qahelper

Локальный CLI-агент для генерации тест-кейсов по шаблону (колонки: ID, Название тест-кейса, Предусловия, Описание шагов, Ожидаемый результат, Окружение, Статус, ID баг-репорта, Примечание). Источники данных: текстовые требования (файл `.md`/`.txt`, PDF, URL), опционально макеты Figma через [Figma REST API](https://www.figma.com/developers/api), генерация через [OpenAI API](https://platform.openai.com/).

Репозиторий: [https://github.com/q1nn2/ai_qahelper](https://github.com/q1nn2/ai_qahelper)

## Установка

```bash
cd ai_qahelper
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

Опционально (автотесты Playwright + pytest):

```bash
pip install -e ".[autotest]"
playwright install chromium
```

## Конфигурация

1. Скопируйте пример и отредактируйте:

   ```bash
   copy ai-tester.config.example.yaml ai-tester.config.yaml
   ```

2. В `ai-tester.config.yaml` задайте модель и список разрешённых окружений (`envs`). Если `envs` пустой, проверка `target_url` отключена.

3. Переменные окружения:

   | Переменная | Назначение |
   |------------|------------|
   | `OPENAI_API_KEY` | Ключ OpenAI (обязательно для генерации) |
   | `FIGMA_API_TOKEN` | Токен Figma (опционально, для `--figma-file-key`) |
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | Путь к JSON сервисного аккаунта (опционально, для `sync-reports` в Google Sheets) |

## Команды

Из корня проекта, где лежит `ai-tester.config.yaml`:

```bash
ai-qahelper ingest --requirement tests/ai-docs/requirements.md --target-url https://example.com
ai-qahelper generate-docs <session_id>
```

Один шаг (ingest + generate-docs):

```bash
ai-qahelper agent-run --requirement tests/ai-docs/requirements.md --target-url https://example.com
```

С URL требований и Figma (ключ файла из URL макета `figma.com/file/<KEY>/...`):

```bash
ai-qahelper agent-run --requirement-url https://example.com/spec.html --figma-file-key AbCdEfGhIjKlMnOp --target-url https://example.com
```

Результаты сессии по умолчанию в `tests/ai-sessions/<session_id>/`:

- `test-cases.csv`, `test-cases.xlsx` — тест-кейсы
- `test-cases.json`, `unified-model.json`, `consistency-report.json`

## Работа в Cursor и Figma MCP

Вызвать MCP Figma из отдельного Python-процесса нельзя — MCP доступен в IDE. Рекомендуемый поток:

1. Подключите сервер Figma MCP в настройках Cursor.
2. В чате получите описание экранов, подписей, состояний и ограничений UI.
3. Сохраните это в файл, например `tests/ai-docs/figma-from-mcp.md`, и передайте в CLI:

   ```bash
   ai-qahelper agent-run --requirement tests/ai-docs/requirements.md --requirement tests/ai-docs/figma-from-mcp.md --target-url https://your-app.example
   ```

Так контекст макетов попадает в единую модель вместе с требованиями. При необходимости дополнительно укажите `--figma-file-key` и `FIGMA_API_TOKEN` для автоматической выгрузки дерева файла через API.

## Примечания

- Модель и endpoint задаются в `ai-tester.config.yaml` (`llm`). Клиент использует OpenAI SDK и метод `responses.create`; убедитесь, что выбранная модель доступна вашему ключу.
- Большие PDF и глубокое дерево Figma увеличивают размер промпта — при лимитах токенов укоротите входные документы или разбейте на части.

## Лицензия

MIT — см. [LICENSE](LICENSE).
