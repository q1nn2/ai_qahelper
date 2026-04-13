# Демо-прогон (реальный вызов LLM)

Зафиксированный пример: `examples/minimal/requirements.md` → 3 тест-кейса, без шага test-analysis (`--skip-test-analysis`).

## Команда

```bash
python -m ai_qahelper.cli agent-run \
  --requirement examples/minimal/requirements.md \
  --target-url https://example.com \
  --max-cases 3 \
  --skip-test-analysis \
  -L demo-readme
```

Если в `ai-tester.config.yaml` задан список `envs`, `target-url` должен совпадать по host с одним из `base_url` (иначе будет ошибка проверки окружения). В записанном прогоне использовался разрешённый стенд из конфига.

## Вывод CLI (фрагмент)

См. [`cli-output.txt`](cli-output.txt).

## Артефакты сессии

- [`test-cases.sample.json`](test-cases.sample.json) — фрагмент сгенерированных кейсов (полный набор в `runs/<session_id>/` после вашего запуска).
- Скрин терминала: [`demo-agent-run.png`](demo-agent-run.png) (иллюстрация; текст совпадает с реальным прогоном ниже).

**Session ID записи:** `2026-04-13_16-16-40_demo-readme_8f4759`
