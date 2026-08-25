# Scope: hr-okk

## LOOP CONTRACT
- include: modules/hr/, frontend/src/app/erp/hr/okk/, frontend/src/components/erp/hr-okk-view.tsx, migrations/versions/N_hr_okk_score.py, tests/test_hr_okk.py
- exclude: modules/sales/, modules/finance/, modules/procurement/, modules/wms/, modules/logistics/, core/, config/, scripts/seed.py
- max_iterations: 8
- max_files_changed: 12
- stop_conditions:
  - pytest tests/test_hr_okk.py = 0 failed
  - import main = OK
  - ruff check = чисто
  - tsc --noEmit = OK

## Ограничения
- НЕ трогать чужие модули (finance, sales, procurement)
- Миграцию брать ТОЛЬКО через `python scripts/next_migration.py hr-okk "..."` (атомарный аллокатор)
- Коммить в submodule modules/hr/ отдельно, потом bump gitlink в суперпроекте
- НЕ пушить
- auth: AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev (иначе import main падает)
