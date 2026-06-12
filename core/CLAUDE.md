# Ядро (core/) — контекст для Claude

Тонкое ядро-платформа: предоставляет контракт модуля, реестр+фасад, общие сервисы,
shared-kernel ORM и переиспользуемые механизмы (канбан, события, согласования).
Модули зависят от ядра, ядро о модулях НЕ знает (только про `ModuleContract`).

## Карта каталога
- `runtime/` — жизненный цикл и контракт:
  - `contract.py` — `ModuleContract` (ABC) + dataclass'ы `Permission`, `Role`, `TelegramCommand`, `Widget`.
  - `core.py` — класс **`Core`**: реестр (`routers/events/workflows/permissions/roles/...`) и фасад к `services`. Методы регистрации: `include_router`, `subscribe`, `register_workflow`, `declare_permissions`, `declare_role`, `register_telegram`, `register_widget`, `on_startup/on_shutdown`.
  - `loader.py` — `load_modules`: импорт `modules.<name>.module`, вызов `get_module().register(core)`; атрибутирует регистрации модулю через `_begin/_end`.
  - `app.py` — `create_app()`: `build_services` → `Core` → `load_modules` → FastAPI. Lifespan: `db.connect`, фоновый `_background_loop` (каждые 2с: `event_bus.relay_once` + `approvals.escalate_once`). Подключает системные роуты.
  - `deps.py` — FastAPI-зависимости: `get_core(request)`, `get_session(request)` (async-сессия на запрос).
  - `funnel.py` — **общий канбан** (см. ниже).
  - `system_routes.py` / `approval_routes.py` / `telegram_routes.py` — системные эндпоинты ядра.
- `db/` — `base.py` (`Base`/`DeclarativeBase` + `NAMING_CONVENTION`), `repository.py` (базовый async CRUD, **без commit**).
- `domain/` — shared kernel ORM (см. ниже), схема по умолчанию `public`.
- `services/` — общие сервисы и шлюзы (см. ниже).

## Shared kernel (`core/domain/models.py`, схема `public`)
Сущности, общие для всех модулей — читаются через ядро, не дублируются в модулях:
- `Counterparty` (контрагент, `unp` — УНП РБ), `Contact`, `Sku` (`code` unique), `User` (`app_user`).
- **Инфраструктурные таблицы ядра:**
  - `OutboxEvent` (`outbox_event`) — журнал событий transactional outbox (`event_type`, `payload` JSON, `processed_at`).
  - `Approval` (`approval`) — запрос на согласование (human-in-the-loop): `route` (роль), `status`, `due_at`, `escalation_level`.
  - `AuditLog` (`audit_log`) — неизменяемая проекция событий (append-only), пишется relay'ем.

## Сервисы и шлюзы (`core/services/`)
Собираются в `Services` (`__init__.py`, `build_services()`); многие — лёгкие заглушки с устойчивым контрактом, наполняются по частям дорожной карты.
- `db.py` — **`Database`**: ленивый async-движок (`init_engine`), `connect` (Postgres: `SELECT 1`; SQLite: `create_all`), `session_factory` (`expire_on_commit=False`).
- `eventbus.py` — `OutboxEventBus`: `emit(session, type, payload)` (в outbox), `relay_once` (доставка + `AuditLog`), `dispatch` (обработчики `(payload)` или `(payload, ctx)` через `EventContext`).
- `approvals.py` — `ApprovalService` (создание/эскалация согласований).
- `temporal.py`, `auth.py`, `litellm.py` — заглушки процессов/авторизации/LLM (части 4/5/Итерация 1).
- **Шлюзы-Protocol, наполняемые модулями** (если модуль выключен — поле `None`, потребители отдают 503):
  - `onec.py` `OneCGateway`, `stock.py` `StockGateway`, `registry.py` `RegistryGateway` ← модуль `integrations`.
  - `llm.py`/`litellm.py` `LLMGateway` (AI за feature-flag `AIOS_AI_ENABLED`).

## Общий канбан (`core/runtime/funnel.py`)
Переиспользуют sales, procurement, production, wms, hr, office, legal, knowledge:
- `build_board(stages, rows, to_card, *, stage_of=lambda r: r.stage) -> FunnelBoardOut` —
  группирует сущности по стадиям, считает `count` и `sum` (по `FunnelCard.amount`).
- `FunnelCard` — **универсальная** карточка (заполняются только нужные поля: `code/title/subtitle/amount/priority/owner/progress/next_step/insight/details/tags/...`).
- Модуль задаёт `STAGES = [{"id","title","color"}, ...]` (порядок = колонки) + функцию `_to_card`.

## Конвенции и подводные камни
- **Транзакция:** `repository.py` и shared-код НЕ коммитят — границей владеет роут/workflow. (Многие модули-каркасы это нарушают и коммитят в роуте — см. их CLAUDE.md.)
- **Схемы БД:** ядро — `public`; каждый модуль — своя схема через `__table_args__ = {"schema": "<name>"}`. Все модели наследуют `Base`, поэтому `Base.metadata` — полная схема для Alembic.
- **SQLite dev:** `Database` отображает схемы модулей в основную через `schema_translate_map={module: None}` и создаёт таблицы напрямую (`create_all`), импортируя `modules.<name>.models`. Источник истины для Postgres — **только Alembic-миграции**.
- **Имена ограничений** фиксированы `NAMING_CONVENTION` в `db/base.py` — стабильные имена индексов/FK в миграциях; не переопределять вручную.
- **Регистрация атрибутируется модулю** автоматически (`Core._current`), пока загрузчик держит контекст `_begin/_end` — внутри `register()` ничего дополнительно указывать не нужно.
- **Событие → обработчик:** хочешь доступ к сессии/сервисам в обработчике — объяви второй параметр `ctx` (`EventContext`), иначе получишь только `payload`.
