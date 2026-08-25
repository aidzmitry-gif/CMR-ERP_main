# Scope: hr-payroll-ui

## LOOP CONTRACT
- include: modules/hr/, frontend/src/app/erp/hr/payroll/, frontend/src/components/erp/hr-payroll-view.tsx, tests/test_hr_payroll.py, tests/test_hr_payroll_list.py
- exclude: modules/sales/, modules/finance/, modules/procurement/, modules/wms/, modules/logistics/, modules/marketing/, modules/service/, modules/production/, core/, config/, scripts/seed.py
model: sonnet
- max_iterations: 8
- max_files_changed: 14
- stop_conditions:
  - pytest tests/test_hr_payroll.py tests/test_hr_payroll_list.py = 0 failed
  - import main = OK
  - ruff check = чисто
  - tsc --noEmit = OK

## Ограничения
- НЕ трогать чужие модули (sales, finance, procurement и др.)
- МИГРАЦИЯ НЕ НУЖНА — backend /hr/payroll уже существует, новый эндпоинт /hr/payroll/summary работает на уровне Python (groupby), без новых таблиц
- Коммить в submodule modules/hr/ отдельно, потом bump gitlink в суперпроекте
- НЕ пушить (пуш делает координатор)
- auth: AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev (иначе import main падает)
- Существующий код hr-payroll-view.tsx НЕ удалять — добавлять поверх (режим «Детально» сохраняется)
