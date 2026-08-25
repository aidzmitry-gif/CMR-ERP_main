# Scope: zak-cost-fe

## LOOP CONTRACT
- include: frontend/src/app/erp/procurement/cost-calc/, frontend/src/components/erp/procurement-cost-calc.tsx
- exclude: modules/, migrations/, scripts/seed.py, core/
- max_iterations: 5
- max_files_changed: 4
- stop_conditions:
  - tsc --noEmit = OK
  - import main = OK

## Ограничения
- Frontend only — NO новых эндпоинтов, NO миграций
- НЕ трогать submodule modules/procurement/
- НЕ пушить
