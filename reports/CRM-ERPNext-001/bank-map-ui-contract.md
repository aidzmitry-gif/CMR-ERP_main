# CRM-ACC-BANK-MAP-UI-001 — контракт UI

## Цель и границы

Сделать уже принятый registry `bank-account-mappings` доступным в существующей
вкладке импорта банковских строк: список, создание, controlled close и
prefill/lock effective cash mapping для BYN preview.

Разрешённая область:

- `frontend/src/components/erp/accounting-bank-import.tsx`;
- новый узкий `frontend/src/components/erp/accounting-bank-mapping.tsx` и его
  Vitest-файл;
- строго относящиеся тесты existing bank-import UI.

Не менять `accounting-view.tsx`, `finance-view.tsx`, backend, Finance,
FX-valuation или автоматическое сопоставление. Новый registry component
встраивается внутрь существующего `AccountingBankImport`, поэтому не создаёт
пересечение с Luna.

## API и поведение

1. Registry component делает `GET /api/accounting/organizations/{org}/bank-account-mappings`
   и показывает provider, external account, currency, period, ledger account
   и dimensions. Создание отправляет ровно текущий `POST` body: provider,
   external_account, currency, valid_from, ledger_account_id, dimensions,
   evidence. Close — текущий `POST .../{id}/close` с valid_to/evidence.
   Ошибки роли chief показываются явно; UI не имитирует авторизацию.
2. Когда бухгалтер выбирает bound BYN candidate, UI запрашивает registry с
   exact `provider`, `external_account`, `currency`, `at=occurred_on` из source
   snapshot. Допускается ровно один mapping. API возвращает
   `ledger_account_id`, а не code: его нужно сопоставить с exact `Account.id`
   effective для `source.occurred_on`, после чего `bank_account` и
   `bank_dimensions` предзаполняются и блокируются до отмены выбора/смены
   candidate. UI никогда не выбирает первый cash account как fallback.
3. Нет mapping, provider/account/date или account-list не позволяют однозначно
   resolved mapping — показать actionable ошибку и не дать preview. Existing
   backend remains final authority; UI не обходит SourceBinding и не меняет
   request shape (`bank_account`, `bank_dimensions` остаются в body).
4. После create/close обновить registry и сбросить stale bank form. После
   успешного preview existing confirm path остаётся прежним. При source/org
   change reset mapping/prepared/preview; поздний ответ lookup игнорируется.

## Совместимость и тесты

`AccountingBankImport` уже получает accounts с `id` в реальном
`AccountingView`; добавь `id` к его компонентному Account contract и обнови
existing tests/consumers, не подменяя ID account code. Registry create требует
реальный ID.
Snapshot type должен принять existing optional `source_provider`.

Приёмка Vitest:

- list/create/close строят точные endpoint/body и обновляют view;
- mapped candidate запрашивает exact date keys, prefill/lock cash account и
  dimensions, preview uses these exact values;
- no mapping/missing key shows clear error and never falls back to another cash
  account;
- existing bind/preview/confirm flow всё ещё проходит;
- targeted frontend test/typecheck и render/browser evidence, no full suite,
  commit/push/deploy до root acceptance.
