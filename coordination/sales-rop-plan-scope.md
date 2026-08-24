# Scope: sales-rop-plan

## LOOP CONTRACT
- include: modules/sales/ (только routes.py/models.py если нужен бэк), frontend/src/app/crm/rop/, frontend/src/components/crm/rop-plan-fact.tsx, tests/test_rop_plan.py
- exclude: modules/finance/, modules/hr/, modules/procurement/, modules/wms/, core/, migrations/ (no new migrations)
- max_iterations: 7
- max_files_changed: 8
- stop_conditions:
  - pytest tests/test_rop_plan.py = 0 failed
  - tsc --noEmit = OK
  - import main = OK

## Ограничения
- НЕ создавать новые миграции (данные из seed или в-памяти заглушка)
- AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev
- НЕ пушить
