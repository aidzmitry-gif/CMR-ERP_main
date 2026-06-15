# Модуль integrations — контекст для Claude

**Тип:** in-tree папка основного репозитория (не submodule)
**API-префикс:** `/integrations`
**Схема БД:** `integrations` (таблица `stock_item`)
**Статус:** частично наполнен (рабочая синхронизация 1С + ЕГР, шлюзы)

## Назначение
Внешние интеграции: 1С (контрагенты, SKU, остатки/цены), складские остатки/резервы и
реестр ЕГР РБ (проверка контрагентов по УНП). Публикует коннекторы в фасаде ядра, чтобы
остальные модули работали с внешними системами через `core.services`, не импортируя этот модуль.

## Файлы
- `module.py` — `IntegrationsModule`; в `register` монтирует роуты, объявляет permission
  `integrations.sync` и **кладёт в фасад ядра**: `services.onec = OneCClient(onec_base_url)`,
  `services.stock = StockService()`, `services.registry = RegistryClient()`.
- `client.py` — `OneCClient` (реализует `OneCGateway`): чтение из 1С; пустой `onec_base_url` → mock-данные.
- `stock.py` — `StockService` (реализует `StockGateway`): остатки/резервы.
- `registry.py` — `RegistryClient` (реализует `RegistryGateway`): поиск по УНП в ЕГР.
- `service.py` — `sync_1c(session, event_bus, onec)`: контрагенты — через идемпотентный адаптер ядра `core.services.reference_import` (матч по УНП + alias-провенанс источника в golden record); SKU/остатки — upsert в shared kernel + `integrations.stock_item`; эмитит событие.
- `models.py` — ORM `StockItem` (схема `integrations`).
- `schemas.py` — `StockOut`, `RegistryOut`.

## Что регистрирует в ядре (register())
- Роуты: префикс `/integrations`.
- Permission: `integrations.sync`.
- **Шлюзы фасада**: `services.onec`, `services.stock`, `services.registry` (контракты-Protocol в `core/services/onec.py`, `stock.py`, `registry.py`).
- Подписок/workflow/ролей/telegram нет.

## События
- **Публикует**: `integration.1c.synced` (payload: `{counterparties, new_counterparties, counterparty_aliases, stock}`) — из `sync_1c`.
- **Подписан на**: —

## Внешние интеграции
- **1С (OneCGateway / OneCClient)**: `fetch_counterparties()`, `fetch_stock()`. `onec_base_url` пуст → mock-источник (для dev/прототипа). Sync пишет в shared-kernel `Counterparty`/`Sku` (по УНП/коду — идемпотентно) и в `integrations.stock_item`.
- **Остатки (StockGateway / StockService)**: остатки/резервы по SKU и складам (используют sales/wms через `core.services.stock`).
- **Реестр ЕГР (RegistryGateway / RegistryClient)**: `lookup(unp)` — карточка контрагента по УНП (sales-28).

## API-эндпоинты
- `POST /integrations/1c/sync` — синхронизация из 1С (роут владеет транзакцией: сам `commit`).
- `GET /integrations/1c/stock` — остатки/цены (`stock_item`, сортировка по `sku_code`).
- `GET /integrations/egr/{unp}` — поиск контрагента по УНП (503 если реестр не подключён, 404 если не найден).

## Подводные камни / детали
- Этот модуль — **источник шлюзов `onec/stock/registry`**: если он выключен в `ENABLED_MODULES`, `core.services.onec/stock/registry == None`, и зависящие роуты отдают 503. Держать его включённым раньше потребителей (sales, wms).
- Sync идемпотентен: контрагенты — match по УНП через `reference_import` (+ alias-провенанс `counterparty_alias` по Ref_Key 1С, без дублей при повторе; пустое имя дозаполняется, существующее не перезатирается), SKU — по коду, остатки — по `(sku_code, warehouse)`.
- Даты хранятся как naive UTC (`_utcnow()` срезает tzinfo).
