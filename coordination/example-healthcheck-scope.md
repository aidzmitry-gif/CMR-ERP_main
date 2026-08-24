# example-healthcheck — scope

Пример scope-файла. Оркестратор генерирует такой под каждую подзадачу.

## Задача (уровень 2 по Boris: касаемые файлы + верификация)

Добавить `GET /healthz` → `{"status": "ok"}` в ядро. Прогнать `pytest tests/test_healthz.py -x`.

## LOOP CONTRACT

```yaml
scope:
  include:
    - core/runtime/app.py
    - tests/test_healthz.py
  exclude:
    - modules/**
    - config/**
    - migrations/**
permissions:
  repo: write-branch
  db: read-only
  llm: enabled
budget:
  max_iterations: 3
  max_runtime_minutes: 15
  max_files_changed: 3
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - acceptance_gate_red_after_3_iters
  - file_touched_outside_scope
  - product_behavior_ambiguous
report:
  destination: coordination/example-healthcheck-status.md
```

## Acceptance gate

- [ ] `tests/test_healthz.py` существует и был RED до фикса (TDD)
- [ ] `GET /healthz` возвращает 200 и `{"status":"ok"}`
- [ ] `pytest tests/test_healthz.py -x` → 0
- [ ] Тронут только `core/runtime/app.py` (+ тест)
- [ ] Six-layer в теле коммита
- [ ] Status-файл заканчивается баннером `STATE: COMPLETE`

## Anticipated failure modes
- Роутер ядра регистрируется не там, где ожидает тест (Class A — missing wiring)
- create_app требует БД на импорте → тест не поднимается (Class D — contract drift)
