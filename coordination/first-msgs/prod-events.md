# Воркер: prod-events — Production подписки на события

## Цель
Подключить модуль производства к шине событий: подписаться на `sales.deal.handoff` и
`procurement.order.received` — создавать производственные задания автоматически.
Критерий: `pytest tests/test_prod_events.py` = 0 failed, `import main` = OK.

## Контекст
- CWD: `D:\6 Проекты\CRM ERP\Сlaude CRM - проект`
- Submodule: `modules/production/` (PRO-4.git)
- Шина событий: transactional outbox, `core.subscribe(event_type, handler)`
- Паттерн обработчика: `async def on_event(payload, ctx)` или `(payload,)` — см. modules/finance/events.py как эталон
- Auth: `AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev` обязательно

## Что делать

### Шаг 1 — Читать существующее
- `modules/production/module.py` — что уже зарегистрировано
- `modules/production/models.py` — таблицы (ProductionPlan, ProductionOrder и т.д.)
- `modules/production/routes.py` — эндпоинты
- `modules/finance/events.py` — паттерн обработчика события

### Шаг 2 — Создать modules/production/events.py
```python
# on_deal_handoff: при передаче сделки в производство → создать ProductionPlan
async def on_deal_handoff(payload, ctx):
    deal_id = payload.get("deal_id")
    if not deal_id:
        return
    # проверить идемпотентность: если план уже есть для deal_id — пропустить
    # создать ProductionPlan(deal_id=deal_id, status="planned", source_event="sales.deal.handoff")
    # session.add(...); await ctx.session.commit()

# on_order_received: при получении закупочного заказа → обновить статус материалов
async def on_order_received(payload, ctx):
    po_number = payload.get("po_number")
    # найти связанные ProductionPlan по po_number или sku_codes
    # отметить материалы как "available"
```

### Шаг 3 — Зарегистрировать в module.py
```python
core.subscribe("sales.deal.handoff", on_deal_handoff)
core.subscribe("procurement.order.received", on_order_received)
```

### Шаг 4 — Возможно нужна миграция
Если в ProductionPlan нет `deal_id` или `source_event` — добавить через аллокатор:
`python scripts/next_migration.py prod-events "production plan deal_id source_event"`
Если поля уже есть — миграцию не создавать.

### Шаг 5 — Тесты tests/test_prod_events.py
- `sales.deal.handoff` → ProductionPlan создан с нужным deal_id
- идемпотентность: второй emit не создаёт дубль
- `procurement.order.received` → не падает (graceful если нет связанного плана)
- `import main` = OK

## DoD
- pytest зелёный + import main + ruff
- Коммит в modules/production/ → bump gitlink суперпроект
- НЕ пушить
- `STATE: COMPLETE`
