# Scope: marketing-phase-e

## LOOP CONTRACT
- include: modules/marketing/, frontend/src/app/erp/marketing/, frontend/src/components/erp/marketing-campaign-board.tsx, tests/test_marketing_phase_e.py
- exclude: modules/sales/, modules/finance/, modules/procurement/, modules/wms/, modules/logistics/, modules/hr/, modules/production/, modules/service/, core/, config/, scripts/seed.py
model: sonnet
- max_iterations: 8
- max_files_changed: 14
- stop_conditions:
  - pytest tests/test_marketing_phase_e.py = 0 failed
  - import main = OK
  - ruff check = чисто
  - tsc --noEmit = OK

## Ограничения
- НЕ трогать modules/sales/ и любые другие чужие модули — ни чтение моделей, ни join по их схемам
- Данные о лидах получать ТОЛЬКО из Campaign.leads (уже накапливается через sales.lead.received → on_lead_received) или через публичный HTTP GET /sales/leads/{id} из фронтенда — но не из бэкенда marketing
- Миграция НЕ нужна (строить на существующих MAR-8 таблицах: campaign, site, seo_project, seo_snapshot, seo_task)
- Если вдруг потребуется миграция — брать номер ТОЛЬКО через `python scripts/next_migration.py marketing-phase-e "..."` (атомарный аллокатор)
- Коммитить в submodule modules/marketing/ отдельно, потом bump gitlink в суперпроекте
- НЕ пушить (пуш делает координатор)
- auth: AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev (иначе import main падает)
