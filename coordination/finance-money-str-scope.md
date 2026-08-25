# Scope: finance-money-str

## LOOP CONTRACT
- include: modules/finance/schemas.py, modules/finance/routes.py, modules/finance/summary.py, modules/finance/aging.py, modules/finance/cashflow.py, modules/finance/margin.py, modules/finance/cost_center.py, modules/finance/reconcile.py, frontend/src/components/erp/finance-view.tsx, tests/test_finance.py, tests/test_finance_pnl.py, tests/test_finance_cashflow.py, tests/test_finance_balance.py
- exclude: modules/sales/, modules/procurement/, modules/wms/, modules/logistics/, modules/hr/, modules/marketing/, modules/service/, modules/production/, core/, config/, scripts/seed.py
model: opus
- max_iterations: 8
- max_files_changed: 14
- stop_conditions:
  - pytest tests/test_finance.py tests/test_finance_pnl.py tests/test_finance_cashflow.py tests/test_finance_balance.py = 0 failed
  - import main = OK
  - ruff check = чисто
  - tsc --noEmit = OK

## Ограничения
- НЕ трогать чужие модули (sales, procurement, hr, и т.д.)
- Миграцию НЕ делать — колонки уже Numeric(14,2); если обнаружишь Float в моделях — ТОЛЬКО зафиксировать в статус-файле (SCHEMA-RISK), не мигрировать
- Коммить в submodule modules/finance/ (fin-7.git) отдельно, потом bump gitlink в суперпроекте
- НЕ пушить (пуш делает координатор)
- auth: AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev (иначе import main падает)
- После КАЖДОГО изменённого money-поля писать строку `CHANGED: <файл> <поле> :: before=float, after=str` в coordination/finance-money-str-status.md — это деньги собственника, координатор проводит ⚠️ REVIEW
