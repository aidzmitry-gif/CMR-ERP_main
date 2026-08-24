# Handoff в закупки: landed cost по номенклатуре для маржи продаж

> Готовый scope для закупочной сессии (submodule ZAK-3). Источник: многоагентный разбор
> 2026-06-24 (8 агентов, 3 линзы верификации — границы/потребитель/дубли). Фиксы линз вшиты.
> Потребитель — методика [[pricing-methodology]] (`quote_line`, §5). Самодостаточно: закупочному
> чату другой контекст не нужен. **Вставлять в закупочный чат целиком.**

## 1. Что и зачем

Продажам нужна **себестоимость единицы номенклатуры, доведённая до склада в Минске (BYN)** —
чтобы `quote_line` посчитал floor/target/маржу по строке. Закупки публикуют её через **read-only
фасад ядра** `core.services.landed_cost` (как `core.services.stock`). Sales зовёт шлюз, хранит
**снапшот** значения у себя; никакого импорта модулей и cross-schema FK.

**Текущая реальность закупок:** `PurchaseRequest` — тонкая воронка: товар хранится **строкой**
(`item String(255)`), стоимость одним полем `amount` без разбивки/валюты/курса, привязки к
номенклатуре нет. Весь landed cost спроектирован только в `modules/procurement/docs/landed-cost.md` —
**кода нет**. Поэтому строим почти всё с нуля.

## 2. Механизм доступа — фасад ядра (не событие как первичный)

- **Pull-шлюз** `core.services.landed_cost.last_landed_cost(session, sku_code)` — основной путь.
  Образец 1:1 — `core/services/stock.py` (`StockGateway` Protocol, session-first) + поле `=None` в
  `core/services/__init__.py` + наполнение владельцем в `register()`
  (`modules/integrations/module.py`: `core.services.stock = StockService()`). Потребление —
  `core/services/stock.py` зовётся из `modules/sales/routes.py` через `if core.services.stock is not None`.
- Почему **не** «только событие»: `quote_line` нужен синхронный pull «дай cost по этой номенклатуре
  сейчас». Чистое событие заставило бы sales держать полную проекцию себестоимости всех SKU (дубль
  источника истины) — хуже, чем soft-ref-снапшот.
- **Событие — позже (Горизонт 2)**, только для push-инвалидации при `estimated→actual`. См. §8.

## 3. РЕШЕНО: ключ номенклатуры — `sku_code` (строка), НЕ `sku_id`

Линза дублей поймала конфликт: `core.services.stock` резолвит по **`sku_code`** (как 1С — источник
истины номенклатуры по коду), и цепочка резерва sales оперирует `sku_code`. Если landed cost завести
по `sku_id`, два соседних шлюза одного домена будут на разных ключах → sales придётся маппить
`sku_code↔sku_id`, чего в коде нет. **Поэтому landed cost ключуется по `sku_code:str`** — единообразно
со stock-шлюзом. (Методика [[pricing-methodology]] §4 поправлена под это.)

## 4. Минимальный срез (лестница лени — чтобы `last_landed_cost` начал возвращать число)

### 4.1 Данные — одна таблица (схема `procurement.*`, без cross-schema FK)
`procurement.landed_cost` (модель `LandedCost`, `__table_args__={"schema":"procurement"}`):

| Поле | Тип | Смысл |
|---|---|---|
| `id` | Integer PK | |
| `sku_code` | String(64), **indexed** | номенклатура (soft-ref на 1С-код, **без FK**) |
| `purchase_request_id` | Integer | soft-ref на `procurement.purchase_request.id` (внутри своей схемы FK допустим) |
| `shipment_id` | String(64) | PO/рейс (`number` или `f"purchase:{id}"`) — провенанс |
| `unit_landed_cost_byn` | Numeric(14,4) | себест-ть единицы **в BYN, не округлять** (маржа считается до округления) |
| `stage` | String(16) default `"estimated"` | `estimated`/`actual` (в мин.срезе всегда `estimated`) |
| `fx_rate` | Numeric(18,6) null | курс НБ РБ, **применённый к cost** (null в мин.срезе) |
| `fx_date` | Date null | дата этого курса (по ней sales считает «устарела ли») |
| `fx_rate_basis` | String(8) null | **что значит fx_date**: `po`/`gtd`/`payment` (убирает двусмысленность курса) |
| `fixed_at` | DateTime server_default now() | дата фиксации cost (провенанс/снапшот) |
| `created_at` | DateTime server_default now() | |

**Уникальность:** `UNIQUE (sku_code, purchase_request_id)` — чтобы повторный PATCH в `qc` не плодил
дубли (см. 4.5). Индекс `(sku_code, fixed_at)` — выборка «последний по номенклатуре».
`# ponytail: limit 1 по fixed_at desc; last-флаг, если вырастет.`

### 4.2 Шлюз ядра — `core/services/landed_cost.py` (Protocol, только чтение)
```python
from __future__ import annotations
from typing import Protocol
from sqlalchemy.ext.asyncio import AsyncSession

class LandedCostGateway(Protocol):
    """Себестоимость единицы номенклатуры, BYN. Источник истины — procurement.
    Только чтение; soft-ref по sku_code (как stock), без FK."""
    async def last_landed_cost(self, session: AsyncSession, sku_code: str) -> dict | None: ...
    # батч — чтобы каталог/счёт/окно звонка не делали N запросов:
    async def last_landed_cost_batch(self, session: AsyncSession, sku_codes: list[str]) -> dict[str, dict | None]: ...
```
**Возврат `last_landed_cost`:** `None`, если по номенклатуре нет строки (нет закрытого PO) —
**НИКОГДА не 0** (0 покрасил бы маржу в зелёный и спрятал дыру → нарушение приоритета №1). Иначе dict:
```python
{
  "unit_landed_cost_byn": Decimal,  # BYN, ГАРАНТИРОВАНО (конверсию делает закупка, не sales); не округлять
  "shipment_id": str,
  "fixed_at": datetime,             # провенанс (НЕ для расчёта «устарела»)
  "stage": str,                     # "estimated"|"actual"
  "fx_rate": Decimal | None,        # курс, применённый к cost
  "fx_date": date | None,           # дата курса — ПО НЕЙ sales сравнивает с текущим НБ РБ
  "fx_rate_basis": str | None,      # "po"|"gtd"|"payment" — смысл fx_date
}
```
Мин.срез: достаточно `{unit_landed_cost_byn, shipment_id, fixed_at}`; `stage="estimated"`, fx_* = `None`.
**`last_landed_cost_batch` обязан вернуть ключ для КАЖДОГО входного `sku_code`** (значение `None`, если
строки нет) — иначе каталог-пикер упадёт на `result[code]`.

### 4.3 Наполнение владельцем
`modules/procurement/<new>.py`: `LandedCostService` реализует Protocol — `select LandedCost where
sku_code order_by fixed_at desc limit 1`, маппинг в dict, `None` если нет строки. Батч — group по `sku_code`,
заполнить все входные ключи.
`modules/procurement/module.py` `register()`: `core.services.landed_cost = LandedCostService()`.

### 4.4 Граница / фасад (хотспот — захватить в `coordination/ACTIVE-SESSIONS.md` на время правки)
`core/services/__init__.py`: импорт `LandedCostGateway` + поле `landed_cost: LandedCostGateway | None = None`
в dataclass `Services`. `build_services` **НЕ** создаёт (None, пока procurement не наполнит).
> Порядок `ENABLED_MODULES` **нерелевантен** и трогать его НЕ нужно: sales читает шлюз лениво в
> request-time хендлере (как stock), а не в `register()`/`on_startup`. (Сейчас `sales` вообще раньше
> `procurement` в конфиге — и stock при этом работает.)

### 4.5 Фиксация cost на стадии `qc` (точка приёма, `RECEIVED_STAGE="qc"`)
В `routes.py` `update_request`: при **фактическом** переходе в `qc`
(`if obj.stage != RECEIVED_STAGE and payload.stage == RECEIVED_STAGE`) — **upsert** строки `LandedCost`
по `(sku_code, purchase_request_id)` (не insert на каждый PATCH), затем существующий `emit
procurement.received`. Один commit.
> ⚠️ `core.event_bus.emit(session, type, payload)` — **СИНХРОННЫЙ, без `await`** (запись в outbox в ту же
> сессию; см. вызов `procurement.received` в `routes.py`). Async — только методы шлюза `landed_cost`. Не перепутать.

### 4.6 Семантика «нет данных»
- Нет строки по `sku_code` → `last_landed_cost` = `None` (→ sales рисует `grey` «себестоимость неизвестна»,
  сделка не блокируется).
- Шлюз не подключён (`core.services.landed_cost is None`) → sales делает graceful-скип (как stock, **не 503**):
  ведёт себя как при `cost=None`.

## 5. Миграция — координация номера (избежать второго head)

- Реальная голова на `sales-2.0-redesign` = **`0043`** (`0001→0043` линейно, файла `0044` в дереве НЕТ).
- **`0044` зарезервирован за leads-сессией** (она держит `0044_leads_init` в staged, см. `coordination/ACTIVE-SESSIONS.md`).
  → закупки берут **`0045`**, `down_revision="0044"` — **но цепочка должна остаться линейной**.
- **Перед записью** обязательно: `grep -h 'down_revision' migrations/versions/*.py | sort` (или `alembic heads`)
  и взять реальную единственную голову как `down_revision`. Если leads ещё не влит в эту ветку — координируй с
  leads-сессией порядок (две сессии не должны взять один номер = два head = падение `alembic upgrade head` у ВСЕХ).
- Дописать в `coordination/ACTIVE-SESSIONS.md` «Счётчик миграций» строку `0045 — procurement landed_cost` и свою
  полосу **до** написания файла.
- **Разнесение коммитов:** ORM-модель `LandedCost` → submodule **ZAK-3** (+ bump указателя в супер-проекте);
  миграция Alembic `0045_*` → **супер-проект** (`migrations/versions/`, не в submodule). Имена ограничений — через
  `NAMING_CONVENTION`, не вручную.

## 6. Соответствие границе §2.4 (проверено линзой границ)
- Нет cross-import: единственная связь — Protocol в `core/`, реализация в `procurement`, потребление в `sales`
  через `get_core` (симметрично stock/onec).
- Нет cross-schema FK: данные в `procurement.landed_cost`; `sku_code` — soft-ref-строка (без `ForeignKey`),
  **по конвенции снапшотов sales** (`modules/sales/models.py` хранит SKU-ссылки бэр-полем), а не потому что
  «sku в другой схеме». FK допустим только внутри схемы procurement (`purchase_request_id`).
- procurement — владелец источника истины; sales — read-only + хранитель снапшота. Записи sales→procurement нет.

## 7. Тест-контракт (доказать с обеих сторон)
**procurement (ZAK-3):**
- переход в `qc` создаёт ровно ОДНУ строку `landed_cost` (повторный PATCH не плодит дубль — upsert);
- `last_landed_cost(session, sku_code)` → dict с `unit_landed_cost_byn` (Decimal, не округлён), `shipment_id`, `fixed_at`;
- **критично:** нет строки → `None` (assert `is None`, не 0, не `{}`);
- две строки по одному `sku_code` → возвращается последняя по `fixed_at`; `estimated→actual` UPDATE не воскрешает старый estimated;
- `last_landed_cost_batch([a,b,c])` → ключи == set входа, `b→None`;
- BYN-инвариант: возвращаемое значение всегда BYN (конверсия — на стороне закупок);
- `register()` кладёт `core.services.landed_cost` (не None после `load_modules`).

**sales (через фасад, без импорта procurement):** `quote_line` при cost не None → margin/verdict;
`landed_cost is None`/`->None` → `grey`, сделка не падает, не 503; снапшот сохраняет
`unit_landed_cost_byn+fixed_at+shipment_id`.

## 8. Горизонт 2 (НЕ в мин.срезе — заложить совместимость, не строить сейчас)
- **Состав себестоимости** (по `docs/landed-cost.md`, разделы «## Данные»/«## Правила»): таблицы
  `purchase_invoice` / `purchase_invoice_line` (qty/вес/объём — базы распределения) / `landed_cost_expense`
  (`kind`: freight/customs/broker/cert/insurance/bank/other; `is_recoverable` — возмещаемый НДС НЕ входит;
  `allocation_base`: cost/weight/volume/qty). `landed_cost` становится результатом распределения (в docs —
  `landed_cost_allocation`; здесь упрощено до 1 строки-результата на номенклатуру).
- **estimated→actual:** UPDATE той же строки на `stage="actual"` по приходу счетов брокера/деммереджа (30–90 дн).
- **Событие** `procurement.landed_cost.calculated` (синхронный outbox-emit на `qc`, рядом с `procurement.received`;
  порядок: сперва зафиксировать cost, затем `received`). payload `{sku_code, unit_landed_cost_byn, shipment_id,
  stage, fx_rate, fx_date, fx_rate_basis, purchase_request_id}`. При `estimated→actual` — то же событие со
  `stage="actual"` → sales по подписке считает «маржу по факту» рядом с историческим снапшотом (R7).
- **By-shipment read** (нужен для R7, чтобы actual-пересчёт привязался к ТОМУ ЖЕ рейсу, а не к «последнему»):
  `async def landed_cost_for_shipment(session, sku_code, shipment_id) -> dict | None`. payload события уже несёт
  `shipment_id` — заложить совместимость сейчас.
- **Два FX-курса** (на дату PO и на дату оплаты, P4 методики): хранить в `purchase_invoice.fx_rate` + expense
  `kind="bank"`; в `landed_cost.fx_rate` — итоговый применённый, подписанный через `fx_rate_basis`.

## 9. Открытые вопросы (нужно решение методики/бухгалтерии/собственника)
1. Что считать «закрытым PO» для cost: стадия `qc` (физприём) или `done` (финал)? Принято фиксировать на `qc` — подтвердить.
2. Источник `sku_code` на приёмке: товар сейчас свободный текст (`item`). Нужен шаг `item→sku_code` при оприходовании
   (или поле `sku_code` в `PurchaseRequest`). **Это предусловие «по номенклатуре», не «положить из amount».**
3. Порог N% отклонения курса для флага «себестоимость устарела» (§7.4 методики) — за собственником, не зашивать.
4. Какой FX применять к `unit_landed_cost_byn` (дата ГТД/оприходования vs дата оплаты) — влияет на actual-пересчёт.
   Зафиксировать в `fx_rate_basis`.
5. Частичная приёмка — в мин.срезе одна строка на весь приход (Горизонт 2).

---
_Подготовлено 2026-06-24. Полоса методики/маржи — сессия «Маржа/ценообразование»; реализация — закупочная сессия (ZAK-3)._
