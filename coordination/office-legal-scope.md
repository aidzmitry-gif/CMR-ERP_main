# Scope: office-legal

## LOOP CONTRACT
- include: modules/office/, frontend/src/app/erp/office/contracts/, frontend/src/components/erp/office-legal-view.tsx, migrations/versions/ (только новая если нужна), tests/test_office_legal.py
- exclude: modules/sales/, modules/finance/, modules/hr/, modules/production/, core/
- max_iterations: 8
- max_files_changed: 12
- stop_conditions:
  - pytest tests/test_office_legal.py = 0 failed
  - import main = OK
  - tsc --noEmit = OK

## Ограничения
- Миграцию ТОЛЬКО через next_migration.py
- Коммит в submodule modules/office/ → bump gitlink
- НЕ пушить
- AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev
