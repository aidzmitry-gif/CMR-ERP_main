# Scope: prod-events

## LOOP CONTRACT
- include: modules/production/, migrations/versions/ (только если нужна новая), tests/test_prod_events.py
- exclude: modules/sales/, modules/finance/, modules/hr/, modules/procurement/, modules/wms/, core/
- max_iterations: 6
- max_files_changed: 8
- stop_conditions:
  - pytest tests/test_prod_events.py = 0 failed
  - import main = OK
  - ruff = чисто

## Ограничения
- НЕ трогать чужие модули
- Миграцию ТОЛЬКО через next_migration.py (если вообще нужна)
- Коммит в submodule modules/production/ → bump gitlink в суперпроекте
- НЕ пушить
- AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev
