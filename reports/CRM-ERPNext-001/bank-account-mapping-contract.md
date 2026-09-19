# Handoff: контракт банковского account mapping

**Статус:** проектирование без реализации.
**Граница:** только accounting-контур; `modules/finance` и продуктовый код не меняются.

## 1. Назначение и существующий контекст

Mapping отвечает на вопрос: какой действующий счёт и аналитики применить к банковской строке с точными ключами

`provider + external_account + organization + currency + operation_date`.

Источник ключей уже есть в `finance.BankTransaction`: `source_provider`, `account_code`, `currency`, `occurred_on`. У самой финансовой строки нет организации. Её единственным решением владельца остаётся существующий `accounting.SourceBinding`:

- его уникальность `source_type + source_id` не допускает две организации для одной банковской строки;
- для `finance_bank_transaction` разрешено только `ownership="own"`;
- создание уже требует роли chief, блокировки строки и проверяет закрытые периоды.

Mapping **не** дублирует это владение. `organization_id` в mapping — область действия учётной настройки, не право собственности на строку. Разрешение требует одновременно: exact `SourceBinding` с той же организацией и единственную действующую mapping-версию. Отсутствие любого из двух условий — 422/409, без fallback.

## 2. Минимальная модель

Новая таблица `accounting.bank_account_mapping`:

| Поле | Правило |
|---|---|
| `id` | стабильный идентификатор версии mapping. |
| `organization_id` | FK на `accounting.organization`; scope настройки, не замена `SourceBinding`. |
| `provider` | точное значение `BankTransaction.source_provider`, non-empty, bounded. |
| `external_account` | точное значение `BankTransaction.account_code`, non-empty, bounded; не маска и не display label. |
| `currency` | ISO-4217 uppercase, ровно три буквы; равно валюте source. |
| `valid_from`, `valid_to` | полуоткрытый интервал `[valid_from, valid_to)`; `valid_to` nullable означает текущую версию. Все поля неизменяемы, кроме контролируемого однократного сокращения `valid_to` через close API с audit. |
| `version` | положительный номер версии в цепочке того же внешнего счёта. |
| `ledger_account_id` | FK на конкретную версию `accounting.account`. При create и resolve сервис проверяет, что это latest effective версия того же кода на дату операции, она принадлежит организации, `cash=true`, `category="asset"`, `quantity_tracking=false`; `currency_tracking=true` требуется только когда mapping currency не BYN. |
| `dimensions` | JSON object точных идентификаторов аналитик. Сервис требует точное совпадение ключей с `Account.required_dimensions`, непустые ограниченные строковые значения; неизвестная/пропущенная аналитика отклоняется. |
| `evidence`, `actor`, `created_at` | неизменяемая причина решения, автор и время. |

Не вводятся отдельные BankAccount/Owner таблицы: существующий `BankTransaction` — факт выписки, `SourceBinding` — владелец факта, mapping — версионная учётная настройка.

## 3. Ограничения и историчность

1. `CHECK(valid_to IS NULL OR valid_to > valid_from)`, `CHECK(version > 0)`, формат currency/provider/account.
2. PostgreSQL `EXCLUDE USING gist` по `provider`, `external_account`, `currency` и `daterange(valid_from, coalesce(valid_to, 'infinity'), '[)') WITH &&`. Важно: `organization_id` **не** входит в этот ключ. Поэтому один внешний счёт в одной валюте не может одновременно принадлежать двум организациям даже через две mapping-строки.
3. `UNIQUE(organization_id, provider, external_account, currency, version)` и уникальность даты начала версии в той же цепочке.
4. Создание новой версии и закрытие прежней происходят в одной транзакции с блокировкой цепочки. Смена создаёт новую строку и может сократить только `valid_to` предшественника до новой `valid_from`; это фиксируется в audit с before/after snapshot. Запрещены закрытие использованной даты, закрытого периода и любое иное редактирование исторической версии.
5. Resolve выбирает latest effective `Account` с тем же code на `operation_date`. Если его ID не равен pinned `ledger_account_id`, mapping больше не действителен: 409 и новая mapping-версия, а не использование старого account/dimensions snapshot.
6. Подтверждённый бухгалтерский receipt хранит `mapping_id`, `version` и digest снимка. Исторический расчёт поэтому не переопределяется более новой настройкой или допустимым close.

`btree_gist` — единственная новая DB-зависимость для exclusion constraint. Проверка принадлежности `ledger_account_id` и точных analytics межтабличная, поэтому выполняется сервисом под lock и покрывается PostgreSQL-тестами; не подменяется JSON-эвристикой.

## 4. API handoff

Все маршруты располагаются под `/accounting/organizations/{org_id}`.

| Метод | Контракт и доступ |
|---|---|
| `GET /bank-account-mappings?provider=&external_account=&currency=&at=&include_closed=false` | `member`: только mappings этой организации; `at` выбирает единственную действующую версию, `include_closed=true` показывает цепочку. Возвращает ID, version, период, ledger account и exact dimensions, без секретов provider. |
| `POST /bank-account-mappings` | `chief`: создаёт первую версию либо новую с будущей `valid_from`. Body: provider, external_account, currency, valid_from, ledger_account_id, dimensions, evidence. Если новая дата пересекает активную цепочку — 409; если она продолжает собственную цепочку, закрытие predecessor выполняется атомарно. |
| `POST /bank-account-mappings/{id}/close` | `chief`: Body `{valid_to, evidence}`. Это единственный разрешённый UPDATE: сокращает `valid_to` только текущей версии, пишет before/after audit и не допускает затронуть used/closed date. Строку не удаляет. |
| `GET /bank-account-mappings/{id}` | `member`: читает конкретную историческую версию в своей организации. |

Нет `PUT`/`DELETE`: исправление оформляется новой версией или явно контролируемым закрытием. Каждая write-операция делает `service.lock_organization`, блокирует mapping chain и пишет audit event с previous/current snapshot.

## 5. Связь с preview и stale-защита

1. Preview ищет mapping по source `source_provider/account_code/currency/occurred_on` и организации из `SourceBinding`; возвращает `mapping_id`, `mapping_version`, `mapping_digest` и `source_digest`.
2. Confirm повторно берёт source, binding и mapping chain `FOR UPDATE`; вычисляет mapping и latest effective account version на operation date заново и сверяет все четыре значения preview.
3. Любая смена/закрытие mapping, новая версия ledger account, смена source digest, другая организация или отсутствие единственной версии возвращают 409 `stale preview`; проводок и allocation не создаётся.
4. Receipt сохраняет values snapshot; последующее закрытие mapping не меняет исторический receipt.

## 6. Миграция и точные будущие файлы

1. Провести read-only audit: нормализованность `source_provider`, `account_code`, currency, наличие `SourceBinding` и потенциальные пересечения. Не backfill-ить mapping по догадке.
2. Отдельной migration без заранее закреплённого номера: включить `btree_gist`, создать таблицу/constraints/indexes. Пустая таблица не меняет BYN import.
3. Сначала создать mappings вручную с evidence; затем включить их только в будущий FX preview. Current BYN routes остаются прежними.

| Файл | Будущая ответственность |
|---|---|
| `modules/accounting/models.py` | `BankAccountMapping` и декларативные базовые ограничения. |
| `modules/accounting/schemas.py` | create/close/read contracts и строгая валидация полей. |
| `modules/accounting/routes.py` | routes, `member`/`chief`, audit и org lock. |
| `modules/accounting/service.py` или новый `modules/accounting/bank_account_mapping.py` | resolve, chain locking, account/dimensions validation, mapping digest. |
| `modules/accounting/fx_bank_settlement_preview.py` | read-only resolve и возврат mapping fingerprint; без write-side. |
| `migrations/versions/<new_revision>_bank_account_mapping.py` | extension, schema, exclusion constraints; номер выбирается при реализации. |
| `tests/accounting/test_bank_account_mapping.py` | ownership, ranges, historical resolution, access, audit, account/dimensions validation. |
| `tests/accounting/test_fx_bank_settlement_preview.py` | stale preview after mapping change and binding mismatch. |

## 7. Приёмка

- Один source binding нельзя привязать ко второй организации; один provider/account/currency не имеет двух перекрывающихся mapping owners.
- Ровно одна mapping разрешается для даты операции; gaps, overlap, currency/provider/account mismatch и невалидный account/dimensions отвергаются.
- Новая версия не меняет историческую; единственный UPDATE `valid_to` не повреждает used/closed interval, оставляет audit и receipt snapshot.
- Новая effective версия `Account` делает старый mapping stale до создания новой mapping-версии; BYN cash mapping не требует `currency_tracking`, но любой cash mapping требует asset/non-quantity account.
- Только chief создаёт/закрывает; member читает только собственную организацию; audit содержит evidence и snapshots.
- Mapping change после preview делает confirm stale, а receipt удерживает прежний mapping snapshot.
