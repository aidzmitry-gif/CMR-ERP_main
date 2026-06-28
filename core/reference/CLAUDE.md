# Справочники (reference / master data) — домен ядра

> Доменный документ блока «Справочники». Код физически распределён по ядру (см. «Где что
> лежит») — это **инфраструктура shared kernel, а НЕ отдельный модуль и НЕ submodule**
> (вердикт зафиксирован, см. ниже). Эта папка — якорь документации домена, без переноса кода.

## Что это

«Справочники» = **реестр-витрина (registry pattern)** поверх данных, которыми владеют ядро
и модули. НЕ второе хранилище: данные остаются у владельца, реестр хранит только метаданные
(для UI-вкладки, RBAC и каталога AI). Концепция целиком — `coordination/db-and-reference-data-concept.md` (v3).

## Где что лежит (карта домена)

| Файл | Роль |
|---|---|
| `core/runtime/contract.py` | dataclass'ы `Reference`, `ReferenceColumn` — метаданные справочника |
| `core/runtime/core.py` | `Core.register_reference` (атрибуция текущему модулю), `Core.register_owned_reference(owner, …)` (публичный путь вне loader'а), реестр `core.references`, `RegisteredReference` |
| `core/runtime/reference_registry.py` | системные справочники ядра (`SYSTEM_REFERENCES`) + `register_system_references(core)`, вызывается в `app.create_app` |
| `core/domain/reference.py` | ORM в схеме `public`: `ref_unit/currency/currency_rate/country/bank/vat_rate`; `ref_sku_version` (SCD2-история мастер-характеристик SKU, мягкий ключ `sku_code`) |
| `core/domain/models.py` | `Sku.attributes` (JSONB — переменные характеристики номенклатуры) |
| `core/services/sku_history.py` | `record_sku_version` — запись датированной версии (снимок мастер-полей `Sku`); единый путь записи истории, зовётся из PATCH `/system/sku/{code}` |
| `core/services/sku_master.py` | **read-фасад мастер-входов landed cost по SKU** (`landed_inputs`/`_batch`): эфф. пошлина ТН ВЭД + НДС на дату + вес/объём/страна + провенанс по полю; читают закупки/маржа — НЕ строить второй |
| `core/services/reference_quality.py` | data-quality аудит (пропуски/дубли/битые ссылки/сироты + `score`), чистые SELECT |
| `core/services/reference_query.py` | AI structural-query: lookup + `aggregate` (count/group_by, whitelist) + `resolve` (SKU + эффективные ссылки) |
| `core/runtime/system_routes.py` | `GET /system/references` + `…/ai-catalog` + `…/quality[/{ref}]` (под `refs.view`), `POST …/query` |
| `core/runtime/reference_routes.py` | generic-CRUD + `POST /{ref}/bulk` (dry_run-upsert) + модерация чувствительных версий (`SENSITIVE_REFS` → Approval) |
| `migrations/versions/0037_reference_data.py` | таблицы reference-data + `sku.attributes` (JSONB+GIN на Postgres) |
| `tests/test_reference_registry.py` | контракт реестра + системные роуты |

## Возможности витрины (2026-06-28)

- **Маржа-вход по SKU (круг 3, ось A — деньги)** — `core.services.sku_master.landed_inputs`
  (+ `GET /system/sku/{code}/landed-inputs`, под `sales.deal.read`): эфф. пошлина ТН ВЭД + НДС
  на дату + вес/объём/страна, провенанс по полю (own/group/tnved). Те же числа, что у закупки в
  landed cost. Закупки/маржа читают этот фасад — **не строить второй**. Фронт — блок на карточке
  SKU. PATCH `/system/sku/{code}` (под `system.write`) пишет SCD2-версию (`record_sku_version`).
  Гейт качества `margin_blind` (SKU без эфф. ТН ВЭД → нельзя посчитать себестоимость) — на
  data-quality дашборде. `reference.*.changed` несёт `ref_key`+`value_hint` (подписка downstream
  на смену ставки). `GET /system/mdm/import-preview` — dry-run счётчики моста 1С→MDM (без записи).

- **Data-quality** — `GET /system/references/quality[/{ref}]` (право `refs.view`): по каждому
  справочнику `score` + проблемы (пропуски/дубли/битые ссылки/сироты), дрилдаун с sample-ключами.
  Фронт — `/erp/spravochniki/quality`. Контрагентов лишь читаем (merge — зона Синк).
- **Bulk-upsert** — `POST /system/refs/{ref}/bulk` для простых справочников (НЕ контрагенты):
  `dry_run` → план, идемпотентно, per-row аудит. Фронт — таб «Справочники-классификаторы» в импорте.
- **Модерация** — правка ставок (`ref_vat_rate`/`ref_tnved`) создаёт Approval вместо записи
  (human-in-the-loop через `core.services.approvals`). Фронт — `/erp/spravochniki/admin`.
- **AI-агрегаты/resolve** — `reference.query` с `aggregate=count|group_by` (whitelist) и
  `resolve=True` (SKU + эффективные ТН ВЭД/НДС/ед/страна одним ответом). Только чтение.
- **Эффективная датировка** — `Account`/`Region` имеют `effective_from/effective_to` (мягкий
  период действия в дополнение к `is_active`).

## Владение данными

- **Reference data** (единицы, валюты+курсы, страны, банки, НДС) и **master data**
  (контрагенты, контакты, номенклатура, сотрудники) — в схеме `public` (shared kernel),
  владеет ядро. Регистрируются через `register_owned_reference("core", …)`.
- **Модульные классификаторы** (стадии воронки, причины отказа, BOM, ЦФО, SLA…) — в схеме
  своего модуля, модуль регистрирует их сам через `core.register_reference(…)` внутри `register()`.

## Правила домена (подводные камни)

- **Историчность = ручной SCD Type 2.** Versioned-справочники (курс, НДС, прайс) хранят
  датированные версии; интервал **полуоткрытый** `[start_date, end_date)`, текущая версия —
  `end_date IS NULL`. Чтение на дату: `start_date <= :d AND (end_date IS NULL OR end_date > :d)`.
  Нативные temporal Postgres — PG18/19; стек на PG16 → ведём вручную.
- **ORM-типы — generic** (`JSON`/`Numeric`/`Date`), чтобы dev на SQLite поднимался через
  `create_all`. JSONB/GIN — только в Postgres-миграции (источник истины схемы — Alembic).
- **MDM (дедуп/merge/golden record/survivorship)** — сервисный слой в `core/services`, НЕ модуль.
  Гибрид rule-based (УНП/код) + ML/fuzzy; человек-в-контуре на спорных merge.
- **1С — временный входной адаптер** через `integrations`; ERP — система-источник с первого дня.
  Natural key свой (УНП + коды ERP), id 1С — вторичный alias. Отказ от 1С = выключить адаптер.
- **AI** берёт точные значения структурно (SQL/MCP поверх каталога `ai-catalog`), pgvector —
  вторично (нечёткий поиск/дедуп имён), не для точных полей.

## Упаковка: почему в ядре, а не submodule

Совет idea-verifier (единогласно, факты проверены по репо): **остаётся в `core/` (вариант B)**.
Submodule даёт нулевую изоляционную выгоду (синхронный bootstrap вне loader'а, единственный
потребитель — ядро, миграции в общем Alembic) и circular-dependency репозиториев + боль 9
submodules. Пересмотр на submodule — только при одновременном появлении внешнего владельца кода
БЕЗ доступа к ядру **и** расщеплении Alembic. Подробно — §6.1 концепции.
