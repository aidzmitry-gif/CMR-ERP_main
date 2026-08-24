# Scope: service-intake

## LOOP CONTRACT
- include: modules/service/, migrations/versions/ (только новый файл N_service_intake_requests.py), frontend/src/app/erp/service/requests/, frontend/src/lib/funnel-configs.ts, tests/test_service_intake.py
- exclude: modules/sales/, modules/finance/, modules/procurement/, modules/hr/, modules/wms/, modules/logistics/, modules/marketing/, modules/production/, core/, config/, scripts/seed.py
model: sonnet
- max_iterations: 8
- max_files_changed: 14
- stop_conditions:
  - pytest tests/test_service_intake.py = 0 failed
  - import main = OK
  - ruff check = чисто
  - tsc --noEmit = OK

## Ограничения
- НЕ трогать чужие модули (sales, finance, procurement, hr, …)
- config/modules.py НЕ трогать — `service` уже в ENABLED_MODULES
- Миграцию брать ТОЛЬКО через `python scripts/next_migration.py service-intake "service intake requests"` (атомарный аллокатор даст реальный номер)
- Коммитить в submodule modules/service/ отдельно, потом bump gitlink в суперпроекте
- НЕ пушить (пуш делает координатор)
- auth: AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev (иначе import main падает)
