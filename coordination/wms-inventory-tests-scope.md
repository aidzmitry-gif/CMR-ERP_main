# wms-inventory-tests — scope

## Задача

Покрыть тестами жизненный цикл инвентаризации WMS (`populate` → строки → факт → `complete`)
одним новым файлом `tests/test_wms_inventory.py`. Продуктовый код НЕ трогать: найденный дефект
идёт в отчёт и `xfail`, а не в правку. Проверка — `pytest tests/test_wms_inventory.py -x`
плюс полный `pytest -q` без регрессий.

## LOOP CONTRACT

```yaml
model: sonnet          # тир: написание тестов по готовому эталону — не T1-зона
effort: medium         # цепочка состояний, но без архитектурных решений
scope:
  include:
    - tests/test_wms_inventory.py
  read_only:
    - modules/wms/routes.py
    - modules/wms/models.py
    - modules/wms/schemas.py
    - tests/test_wms_round5.py
    - tests/conftest.py
  exclude:
    - modules/**          # 1592-строчный routes.py правят другие полосы — конфликт гарантирован
    - migrations/**       # голова миграций оспорена (untracked 0106), новый номер брать НЕЛЬЗЯ
    - config/**
    - core/**
    - frontend/**
    - coordination/**     # кроме своего status-файла
permissions:
  repo: write-branch
  db: read-only
  llm: enabled
budget:
  max_usd: 25
  max_iterations: 6
  max_runtime_minutes: 60
  max_files_changed: 2
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - acceptance_gate_red_after_3_iters
  - file_touched_outside_scope
  - product_behavior_ambiguous
report:
  destination: coordination/wms-inventory-tests-status.md
```

## Acceptance gate

- [ ] `tests/test_wms_inventory.py` существует, каждый тест был RED до зелени (TDD)
- [ ] Покрыт сквозной путь: создать → `populate` → факт ≠ учёта → `complete` → остаток
      изменился РОВНО на расхождение
- [ ] Покрыты: ручная строка по новому SKU; повторный `populate`; `complete` закрытого
      пересчёта; `PATCH` несуществующей строки; `GET` несуществующего `count_id`
- [ ] `pytest tests/test_wms_inventory.py -x` → 0
- [ ] `pytest tests/test_wms*.py -q` зелёный (соседи по модулю не сломаны).
      ⚠️ Полный `pytest -q` воркеру НЕ задавать: он идёт дольше 10 минут, а команда сверх
      этого принудительно уходит в фон — воркер остаётся без результата и умирает,
      не закоммитив. Полный прогон делает оркестратор перед `integrate`.
- [ ] `ruff check .` чист
- [ ] Тронут только `tests/test_wms_inventory.py` (+ свой status-файл)
- [ ] Six-layer в теле коммита
- [ ] Status-файл заканчивается баннером `STATE: COMPLETE`

## Anticipated failure modes

- **Class D — contract drift:** ответы роутов не совпадают с ожиданиями, взятыми «по смыслу».
  Лечение: читать `modules/wms/routes.py` и `schemas.py`, а не догадываться.
- **Class A — missing wiring:** тест не поднимается без фикстур из `tests/conftest.py`
  (сессия SQLite, ASGI-клиент, маркер `api`). Лечение: копировать обвязку из
  `tests/test_wms_round5.py`, а не собирать свою.
- **Class B — данные:** `populate` берёт остатки, которых в чистой БД нет → строк ноль и тест
  «зелёный ни о чём». Лечение: сначала создать движение прихода, потом проверять, что
  строк СТАЛО больше нуля.
- **Ловушка скоупа:** тест краснеет из-за дефекта продукта, и рука тянется поправить
  `routes.py`. Это выход за скоуп — `xfail` + `КООРД: NEEDS-ARB`.
