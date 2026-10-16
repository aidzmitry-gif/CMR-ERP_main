# CRM-ACC-BANK-MAP-CONSUMER-001 — контракт исполнения

## Граница

Подключить уже принятый `BankAccountMapping` к существующим BYN
`accounting.bank_import.prepare/confirm`. Это не новый двигатель проводок и не
изменение `modules/finance`, frontend, FX valuation или legacy auto-match.

Изменять только:

- `modules/accounting/bank_import.py`;
- `modules/accounting/bank_account_mapping.py`;
- при действительно необходимом контракте — строго относящиеся
  `modules/accounting/schemas.py` и `modules/accounting/routes.py`;
- целевые `tests/accounting/test_bank_import*.py` и
  `tests/accounting/test_bank_account_mapping.py` либо один новый
  `tests/accounting/test_bank_map_consumer.py`.

Не делать migration: fingerprint хранится в существующих JSON basis/snapshot.
Не менять `BankImportInput` так, чтобы старому replay потребовалось новое поле.

## Обязательная семантика

1. Для нового BYN preview сначала остаётся обязательным exact `SourceBinding`
   (`finance_bank_transaction`, та же организация, `ownership="own"`). Затем
   resolve ищет ровно один mapping по `source_provider`, `account_code`,
   `currency` и `occurred_on`. Пустые/legacy ключи, отсутствие binding или
   mapping, а также ambiguous/stale account — fail closed, без posting.
2. Resolve возвращает effective cash account и exact mapping snapshot
   (`mapping_id`, `version`, account, dimensions, digest). Ручные
   `bank_account`/`bank_dimensions` существующего BYN body не могут заменить
   registry: они должны совпадать с mapping либо preview возвращает явную
   ошибку. Не молча подменять введённые оператором значения.
3. `basis` и новый immutable `BankImportReceipt.snapshot` сохраняют mapping
   fingerprint. `command_digest` и shape старой business command не меняются.
4. В `confirm` replay уже существующего receipt остаётся до `prepare`: тот же
   request key, command/basis/digest возвращает старый receipt даже если у него
   нет mapping fingerprint. Новое подтверждение повторно читает binding,
   source и mapping под lock; расхождение fingerprint/basis после preview —
   stale preview, без entry/receipt/event.
5. `close` и `create(successor)` в `bank_account_mapping` обязаны одинаково
   блокировать сокращение интервала, которое исключило бы `operation_date`
   уже подтверждённого receipt с этим mapping fingerprint. Это правило не
   относится к старым receipts без mapping fingerprint.

## Совместимость UI

Текущий `frontend/src/components/erp/accounting-bank-import.tsx` уже посылает
`bank_account` и `bank_dimensions` и даёт бухгалтеру ручной выбор. Его не
менять в этом пакете. HTTP body сохраняется совместимым, но после включения
registry пользователь должен выбрать ровно effective mapping; отсутствие или
несовпадение должно быть видно как явная API ошибка, а не fallback на первый
cash account. Отдельный UI-пакет позднее должен читать mapping и prefill/lock
полей до preview.

## Приёмка

- mapped BYN: preview → confirm → replay создаёт один receipt и posting;
- no/foreign binding отклонён;
- mapping или effective Account меняется между preview/confirm → stale, без
  новой проводки;
- close и successor не могут отсечь used operation date;
- старый receipt повторяется прежним body/digest без mapping;
- только targeted tests, static check и `git diff --check`; no full suite,
  commit/push/deploy до root acceptance.
