# Scope: wms-fe-inv

## LOOP CONTRACT
- include: frontend/src/app/erp/wms/, frontend/src/components/erp/wms-stock-view.tsx, frontend/src/components/erp/wms-movements-view.tsx, frontend/src/components/erp/wms-receipts-view.tsx
- exclude: modules/, migrations/, scripts/, core/
- max_iterations: 6
- max_files_changed: 8
- stop_conditions:
  - tsc --noEmit = OK
  - import main = OK

## Ограничения
- Frontend only — NO миграций, NO изменений backend
- НЕ трогать submodules
- НЕ пушить
