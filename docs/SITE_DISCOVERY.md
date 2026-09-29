# Site Discovery Mode

Site Discovery Mode нужен, когда требований нет, но есть сайт или стенд. Агент исследует фактически видимый UI и создаёт exploratory model, по которой затем можно генерировать test cases/checklists.

## Как запустить

В chat mode:

```text
Требований нет. Вот сайт https://example.com. Пройди до 5 страниц и сделай smoke + negative тест-кейсы.
```

## Что делает агент

Discovery работает в read-only mode:

- обходит внутренние ссылки;
- соблюдает `same_domain_only`;
- ограничивает обход через `max_pages` и `max_depth`;
- учитывает базовые правила `robots.txt` для `User-agent: *`;
- использует `sitemap.xml` как источник кандидатов, если sitemap найден;
- сортирует ссылки по QA-важности: login, register, catalog, cart, checkout, payment, profile, search, contacts, feedback, support;
- собирает видимый текст, заголовки, формы, поля, кнопки, ссылки и alt-тексты;
- при Playwright собирает screenshots, console errors и network failures;
- проверяет базовые accessibility risks: alt у изображений, labels у inputs.

## Настройки

В Streamlit sidebar доступны:

- `max_pages`;
- `max_depth`;
- `same_domain_only`;
- `use_playwright`;
- `timeout_seconds`;
- создание screenshots.

Если Playwright недоступен, используется fallback на `httpx` + HTML parsing.

## Артефакты

В папке сессии создаются:

- `site-model.json` — страницы, формы, поля, кнопки, ссылки, ошибки console/network и summary;
- `exploratory-report.json` — inventory, risks, gaps, accessibility basics, suggested test areas;
- `exploratory-report.md` — читаемый exploratory report;
- `unified-model.json` — synthetic model для обычной генерации документов.

## Ограничения

Site Discovery:

- не логинится;
- не отправляет формы;
- не нажимает destructive/submit actions;
- не меняет данные;
- не знает бизнес-правила продукта;
- анализирует только видимый UI в пределах заданных лимитов.

В ответе агент явно предупреждает, что тест-кейсы созданы по фактическому поведению сайта, а не по требованиям продукта.
