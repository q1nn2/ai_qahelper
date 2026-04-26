# Input Formats

AI QAHelper принимает требования из файлов, URL и Figma. Все локальные файлы передаются через CLI `--requirement` или загружаются в chat mode.

## Поддерживаемые входы

- `.md`
- `.txt`
- `.pdf`
- `.docx`
- `.xlsx`
- `.xls` best effort
- URL
- Figma file key

## Markdown и текст

`.md` и `.txt` читаются как UTF-8 текст. Это самый простой и дешёвый формат для требований.

## PDF

PDF читается как текст. Если включён `pdf_vision`, страницы рендерятся в изображения и дополнительно описываются vision-моделью. Это полезно для сканов, схем, таблиц и макетов внутри PDF.

Если vision выключен или недоступен, агент использует извлечённый текст и добавляет warning при проблемах с визуальной частью.

## Word `.docx`

Из DOCX извлекаются:

- paragraphs;
- headings;
- lists;
- tables;
- текст из ячеек таблиц;
- изображения.

Изображения извлекаются из `word/media` и сохраняются в папку сессии. Затем они анализируются vision-моделью как визуальные требования: UI-элементы, поля, кнопки, состояния, ошибки, таблицы, схемы переходов и видимые бизнес-правила.

Если `docx_vision` выключен, изображений больше лимита или vision-анализ упал, агент не пропускает это молча: warning попадает в content требований и в `input-coverage-report.json`. Warning также явно указывает риск неполного покрытия требований.

Порядок картинок сохраняется best effort по структуре `word/media`.

## Excel `.xlsx`

Из XLSX читаются:

- названия листов;
- строки;
- ячейки;
- непустые значения;
- таблицы в Markdown-like формате.

Лимиты по умолчанию:

- 10 листов;
- 500 строк на лист;
- 50 колонок на лист.

Если файл обрезан по лимитам, warning попадает в content требований и `input-coverage-report.json`.

## Excel `.xls`

`.xls` поддерживается best effort через pandas. Для старого формата обычно нужен `xlrd`. Если чтение недоступно, сохраните файл как `.xlsx`.

## URL

URL читается как HTML/text через HTTP-запрос. Для анализа фактического сайта без требований используйте Site Discovery Mode.

## Figma

Figma file key можно передать отдельно. Для API нужен `FIGMA_API_TOKEN`. Без API можно описать экраны в Markdown и передать как обычный requirement file.

## Input Coverage Report

При ingest создаётся `input-coverage-report.json`. Он показывает, что агент реально увидел во входных файлах.

Пример для DOCX:

```json
{
  "source": "requirements.docx",
  "type": "docx",
  "paragraphs_found": 25,
  "tables_found": 3,
  "images_found": 8,
  "images_analyzed": 8,
  "images_skipped": 0,
  "warnings": []
}
```

Пример warning:

```json
{
  "source": "requirements.docx",
  "type": "docx",
  "images_found": 5,
  "images_analyzed": 0,
  "images_skipped": 5,
  "warnings": [
    "DOCX contains 5 images, but docx_vision is disabled. Visual requirements were not analyzed. Risk: incomplete requirements coverage because visual requirements were not analyzed."
  ]
}
```
