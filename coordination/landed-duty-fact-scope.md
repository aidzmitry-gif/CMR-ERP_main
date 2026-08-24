# Scope: landed-duty-fact

## LOOP CONTRACT
- include:
  - modules/procurement/routes.py
  - tests/test_procurement_landed_cost.py
  - tests/test_procurement_landed_duty_fact.py   ← оракул координатора, см. ниже — НЕ РЕДАКТИРОВАТЬ
- exclude: все остальные modules/*, core/, config/, scripts/seed.py, любые файлы миграций
model: sonnet
- max_iterations: 8
- max_files_changed: 12
- stop_conditions:
  - pytest tests/test_procurement_landed_duty_fact.py::test_landed_plan_fact_reconcile = 0 failed
  - pytest tests/test_procurement_*.py = 0 failed
  - import main = OK
  - ruff check = чисто

## Ограничения
- `tests/test_procurement_landed_duty_fact.py` — ОРАКУЛ координатора (assert `test_landed_plan_fact_reconcile`
  не ослаблять, файл не редактировать вообще). Задача считается выполненной, когда этот тест проходит
  БЕЗ изменения теста — правь код (`modules/procurement/routes.py`), не тест.
- НЕ трогать чужие модули (finance/sales/wms/hr/…), НЕ трогать `core/`.
- НЕ трогать `_fixate_landed_cost` (факт при реальной приёмке) — там пошлина уже корректна
  (коммит `feat(zak): пошлина ТН ВЭД в факт landed на приёмке`, submodule ZAK-3). Не дублировать эту
  логику заново — чинить только `landed_preview()`.
- Миграция НЕ нужна (расчётный путь без новых полей/таблиц).
- Коммить в submodule (`modules/procurement/`) отдельно, потом bump gitlink в суперпроекте.
- НЕ пушить (пуш делает координатор).
- auth: AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev (иначе import main падает).
