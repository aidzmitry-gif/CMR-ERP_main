# Полная банковская выписка: следующий участок реализации

Осмотр текущего кандидата 341ecb6, 19 сентября 2026 года.

## Подтверждённая граница

`core/services/bank.py` предоставляет `fetch_incoming`: только кредитовые операции.
`modules/finance/bank_ingest.py::sync_incoming` сохраняет зачисления и сопоставляет их с дебиторской задолженностью.
`finance.bank_transaction` хранит плательщика и положительную сумму, но не направление.
`modules/accounting/bank_import.py` проводит такие источники только как поступления BYN.
Ручной `BankDocument` уже поддерживает BYN-поступление и BYN-списание.

Знак суммы не заменяет направление: отрицательная строка текущего входящего источника считается ошибкой, а не подтверждением списания. Нельзя переключить её на оплату поставщику без нового контракта источника.

## Последовательность доработки

1. Добавить отдельный контракт полной выписки: идентификаторы банка, счёта и строки; явное направление receipt/payment; положительная сумма в валюте; валюта; дата операции; контрагент; назначение; происхождение исходного файла/ответа. Существующий fetch_incoming сохраняет семантику.
2. Сохранить направление и исходные реквизиты версионируемой миграцией. Старые строки не превращать автоматически в списания. Миграцию согласовать с текущим реестром номеров перед реализацией.
3. Отделить загрузку полной выписки от существующего сопоставления зачислений: расходная строка не должна создавать оплату дебиторской задолженности. Юрлицо и принадлежность счёта устанавливаются явно.
4. Для BYN переиспользовать BankDocument и текущие preview/confirm, пакет проводок, аналитику, блокировки периода и неизменяемую квитанцию. Направление включить в снимок и проверку неизменности источника; не изменять старые квитанции.
5. Для валюты сохранять исходную сумму, дату/источник/масштаб курса и BYN-оценку по утверждённой политике. Не заимствовать коммерческий резерв или управленческий пересчёт.
6. В существующем экране выписки показывать направление и контрагента; до подтверждения — точные счета, аналитику и расчёт. Ошибочная строка остаётся видимой с причиной.

## Приёмка

- Две строки с одинаковой суммой и противоположным направлением формируют соответствующие разные проводки.
- Повтор файла/ответа не дублирует строку, проводку или платёж; пространство идентификаторов учитывает источник и счёт.
- Расход не сопоставляется с дебиторским счётом как поступление.
- Другие юрлица, изменение источника после preview, закрытый период и конкурентное подтверждение отклоняются штатными правилами.
- Старые поступления и повторные запросы по старым квитанциям сохраняют результат.
- Валютный расчёт блокируется без обязательных настроек/курса; сохранённые исторические значения не меняются вслед за текущим курсом.
- Фактическая выписка сверена бухгалтером с банком и 1С. Синтетические проверки не заменяют эту сверку.

## Локальный этап 19 сентября 2026

Реализована регистрация отдельной строки BYN главным бухгалтером выбранного юрлица: явное направление, банк, счёт, исходный идентификатор операции и основание принадлежности. Повтор идентичного источника возвращает ту же строку; изменённые финансовые факты отклоняются. Строка сама не создаёт оплату или проводку: дальнейшее проведение использует существующие предварительный расчёт и подтверждение. Направление включено в снимок нового источника. Снимки старых поступлений сохраняют прежний формат.

Миграция 0135 после0134 добавляет происхождение и направление источника, уникальность банковского идентификатора в пределах банка/счёта и защиту неизменности. Новые строки исключены из старого сопоставления зачислений со счетами клиентов. Валюта кроме BYN и суммы, требующие округления, отклоняются.

Проверено локально на синтетических данных:

- Полная установка зарегистрированных миграций до0135 в PostgreSQL.
- API: поступление и списание, повтор источника без дубля, отказ при изменении суммы; правильные стороны проводок, конкурентное подтверждение с одной квитанцией, запрет изменения направления прямым SQL и запрет обработки списания старым механизмом зачислений.
- Обновление заполненной0134 до0135 сохраняет прежние поля237таблиц, две строки проводок и старую банковскую строку. Старые квитанции банковского импорта в этом наборе отдельно не представлены.
- Реальный браузер: ручной ввод списания → повторное сохранение без дубля → расчёт → подтверждение → карточка Кт51/Дт60 на125.50BYN. Два теста с авторизацией прошли за50.7с. Проверки TypeScript, ESLint и Ruff прошли.

Локальные протоколы находятся в `reports/bank-statement/` рабочего каталога; они не заменяют CI или приёмку бухгалтером. Автоматическое чтение файла/ответа банка, массовая очередь ошибок, валютная выписка и реальная сверка ещё не реализованы. В интерфейсе сейчас ручной ввод одной строки; это не завершённый импорт полной выписки и не готовность заменить1С. Изменения не развёрнуты на сервере.

## CSV adapter (normalized-csv-v1)

Added a file picker and preview/confirm flow in the existing bank import screen. Input is explicit UTF-8 comma-separated CSV with exactly these columns:

```csv
external_id,direction,operation_date,amount,currency,counterparty_name,counterparty_identifier,purpose
BANK-001,receipt,2026-09-01,100.00,BYN,Example customer,,Invoice payment
BANK-002,payment,2026-09-01,20.50,BYN,Example supplier,,Supplier payment
```

The chief accountant supplies the bank/provider identifier, owned bank account and ownership evidence for the selected organization. Up to1000 operations, BYN only; no automatic bank-specific format detection. The content SHA256 is retained as source provenance. Preview identifies bad records and valid-row totals without storing sources. Any validation error blocks the entire file. Confirmation binds the organization, exact content and import settings to the preview digest, reuses source identity checks and atomically saves all source rows. A conflict rolls back earlier rows in the same package. Replays return existing sources; ledger posting remains a separate reviewed action.

Six targeted parser/API tests passed, including atomic rollback, idempotence, explicit invalid rows and changed preview settings. TypeScript and focused ESLint passed. Real bank samples, bank-specific adapters, API ingestion and foreign-currency valuation remain outstanding.

Browser CSV scenario plus auth setup: 2 passed in30.8s on synthetic SQLite with real Next/FastAPI. Screenshot inspected: reports/bank-statement/bank-csv-import.png. PostgreSQL concurrency verification of draft0136 remains a separate pending packet.

## Reviewed cross-path protection (0136)

Migration0136 fences original bank identities shared by legacy incoming sync and full statements. Concurrent legacy/full insertion waits on the same advisory identity lock; the losing transaction is rejected after the winning source commits. Different full-statement accounts retain their scoped identities. Writes explicitly require READ COMMITTED. A receipt seals its ledger lines even before the creating transaction commits. Application guards provide actionable conflicts; finance sync rolls back on ingest/commit failure and returns409 for integrity conflicts instead of reporting a bank outage.

Luna's disposable PostgreSQL probe passed both race orders with observed advisory waits, different-account identities, unsupported-isolation rejection and same-transaction balanced-line append rejection with preservation of the original posting. Migration SHA256:70EAEC466C0503F517BD543D2F31F00831D697F2DB2BAAD11C3DD51C07039DBA. Registered upgrade reached0136; own probe DB removed after marker verification. Parent inspected report and probe assertions at reports/bank-statement/luna-0136-report.md and luna-0136-verify.py. A separately created old0134 receipt also replayed after registered upgrade with identical snapshot/receipt/ledger. Three API conflict/rollback tests passed. No production schema was changed.
