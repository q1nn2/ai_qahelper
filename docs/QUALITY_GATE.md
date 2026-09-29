# Quality Gate and Deduplication

AI QAHelper сначала просит LLM генерировать документацию по строгому QA-standard prompt, а затем локально проверяет результат. Локальные проверки не заменяют хорошую генерацию, а страхуют от мусора перед экспортом.

## Deduplication

Перед сохранением test cases запускается локальное удаление дублей без LLM и внешних API.

Правила:

- точные дубли по normalized title;
- дубли по `normalized title + normalized expected_result`;
- очень похожие кейсы по `normalized steps + normalized expected_result`.

После dedup:

- удалённые кейсы не экспортируются;
- `case_id` перенумеровываются последовательно: `TC-001`, `TC-002`, `TC-003`;
- уникальные `source_refs` удалённых дублей объединяются в оставшемся кейсе;
- в `note` может добавляться `Merged duplicate: <old_case_id>`;
- создаётся `dedup-report.json` или focused-вариант вроде `dedup-report-smoke.json`.

## Documentation Quality Gate

Quality Gate локальный, быстрый и бесплатный. Он не использует LLM и не отправляет слабые кейсы обратно на исправление.

Проверяются:

- vague title;
- vague expected result;
- insufficient steps;
- multiple checks;
- missing test data;
- missing source_refs;
- possible invented requirement;
- automation weakness.

Для checklist дополнительно проверяются конкретность `check`, наличие `expected_result`, `priority` и `source_refs`.

## Score и статусы

Каждый test case или checklist item получает score от 0 до 100.

- `ready`: score >= 85;
- `needs_review`: 70-84;
- `weak`: < 70.

Слабые элементы не удаляются автоматически. Quality status попадает в `note`, поэтому виден в колонке «Примечание» в XLSX/CSV:

```text
Quality: ready; score: 92
```

или:

```text
Quality: needs_review; score: 76; issues: vague_expected_result, missing_test_data
```

## Отчёты

Для test cases создаётся:

- `test-cases-quality-report.json`;
- `test-cases-quality-report-smoke.json`, `test-cases-quality-report-negative.json` и т.п. при focused generation.

Для checklist создаётся:

- `checklist-quality-report.json`;
- `checklist-quality-report-smoke.json` и т.п. при focused generation.

Пример:

```json
{
  "type": "test_cases",
  "total": 20,
  "ready": 15,
  "needs_review": 4,
  "weak": 1,
  "average_score": 87.5,
  "items": [
    {
      "case_id": "TC-001",
      "quality_score": 92,
      "status": "ready",
      "issues": []
    }
  ],
  "summary_issues": {
    "vague_expected_result": 2,
    "missing_source_refs": 1
  }
}
```
