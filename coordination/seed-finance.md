<!-- Транзитный засев для переоткрытия полосы. Не коммитить. Сгенерирован координатором 2026-06-27, сверен адверсариально (approved). -->
# Финансы (fin-7) — переоткрытие

Ты — полоса **Финансы**, submodule **fin-7** (`modules/finance`), **единый писатель** проводок/платежей/маржи. Ветка: `sales-2.0-redesign`. Запускайся из корня суперпроекта; правки субмодуля — через `git -C modules/finance`.

## Зона / модель
- `modules/finance/**`, фронт `frontend/src/app/erp/finance/**`, миграции finance в `migrations/versions/` (это **суперпроект**, не субмодуль).
- Таблица `finance.payment` (id, ref, amount, status, kind, created_at). `Payment.kind` ∈ {receivable (счёт/доход), freight (расход доставки), freight_refund (возврат)}.

## Состояние (проверено)
- fin-7 HEAD `278dadd` — залита логика проекции фрахта: `Payment.kind` + обработчик `on_freight_cost` на `logistics.freight.cost`. Код в субмодуле закоммичен, чисто.
- ⚠️ Миграция `0053_finance_payment_kind` — **файл СУПЕРПРОЕКТА** (`migrations/versions/`), НЕ субмодуля fin-7. В main НЕ влита (ветка `freight-finance`/PR #11), в рабочем дереве sales-2.0-redesign сейчас **untracked**. В fin-7 закоммичена логика (events.py/models.py/module.py, коммит 278dadd). Реконсиляцию согласуй с координатором.
- Security-review (2026-06-26) по диффу — критичного не найдено.

## Цепочка миграций
- Линейна и проверена: `0052→0053→0054→0055`, **голова = 0055**, на 0055 никто не ссылается. **0056 зарезервирован за Складом/WMS — НЕ брать.** Нужен свой номер — пинг координатору (он впишет номер и down_revision до написания файла).

## Хэндофф логистики (2026-06-27)
- Логистика **эмитит**, ты **проецируешь** (логистика в finance напрямую не пишет).
- `logistics.freight.cost` → `Payment(kind="freight")` — ✅ работает.
- **`logistics.freight.audit_refund` → `Payment(kind="freight_refund")` или отрицательная сумма — ТВОЯ ОТКРЫТАЯ ЗАДАЧА** (переплата перевозчику к возврату, variance>0; payload `{shipment_code,carrier,amount,entity_ref:"audit:{id}"}`). Логистика-сторона+тест готовы, подписки finance ещё нет.
- Не ломай `Payment.kind` и подписку `on_freight_cost`.

## Решение координатора по приоритету
- **ПЕРВЫМ — обработчик audit_refund** (деньги к возврату собственнику + закрывает хэндофф логистики). Маржу/валовую-прибыль дашборд **НЕ начинай**: блокер — методика цены (landed cost→цена) ещё не готова (дизайн-фаза).
- Деньги: в payload `str(amount)`, в ORM Decimal/Numeric(14,2); конвертация `Decimal(str(...))`. `POST /payments` коммитит сам; обработчики пишут через `ctx.session`, коммит делает outbox-delivery.

## Координация (канон)
- Писать МОЖНО только в `coordination/.activity.local.md` и `PUSH-LOG.md` (авто, хуки). Реестр (ACTIVE-SESSIONS/DEPENDENCY-MAP/STATUS), счётчик миграций, `.claude/settings.json` — **только через координатора**.
- Не трогать: shared-kernel (counterparty, sku, ref_*, outbox/audit), `modules/integrations`, `core/services/*` (кроме своих events). Чужие submodules — только эмиты, не пиши.
- Хотспоты (захват у координатора перед правкой): для finance релевантны `config/modules.py`, `config/settings.py`, `core/services/__init__.py`; полный реестровый набор также включает `core/db/base.py`, `frontend/src/lib/api.ts`, `frontend/src/components/sidebar.tsx`.
- Push: cherry-pick ТОЛЬКО своего коммита на чистую ветку от origin; правка субмодуля = коммит + bump указателя; никакого amend/reset/rebase на общей ветке. Push/commit — по явной просьбе.

В конце доложи координатору: обработчик готов? нужен ли номер миграции? готовность к следующему хэндоффу.
