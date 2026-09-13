"""Unit-тесты обработчиков событий: ранние выходы (guard) без БД."""
from types import SimpleNamespace

import pytest


async def test_sales_handlers_ctx_none_are_noop():
    from modules.leads.events import on_campaign_launched
    from modules.sales.events import (
        on_incoming_message_ai,
        on_payment_paid,
        on_shipment_delivered,
    )

    # ctx=None → ранний выход, без обращения к БД и без исключений
    await on_campaign_launched({"leads": 3, "name": "К"}, None)
    await on_payment_paid({"ref": "x"}, None)
    await on_shipment_delivered({"deal_id": 1}, None)
    await on_incoming_message_ai({"direction": "in", "deal_id": 1}, None)


async def test_incoming_message_non_inbound_is_noop():
    from modules.sales.events import on_incoming_message_ai

    # исходящее сообщение (direction != in) не триггерит AI даже с контекстом
    ctx = SimpleNamespace(session=None, services=SimpleNamespace(llm=None))
    await on_incoming_message_ai({"direction": "out", "deal_id": 1}, ctx)


async def test_incoming_message_ai_disabled_is_noop():
    from modules.sales.events import on_incoming_message_ai

    # AI выключен → обработчик ничего не делает (не дойдёт до шлюза)
    ctx = SimpleNamespace(session=None, services=SimpleNamespace(llm=SimpleNamespace(enabled=False)))
    await on_incoming_message_ai({"direction": "in", "deal_id": 1}, ctx)


async def test_cross_module_handlers_missing_context_contract():
    from modules.finance.events import on_document_posted as finance_on_doc
    from modules.logistics.events import on_document_posted as logistics_on_doc
    from modules.wms.events import on_goods_received, on_stock_released, on_stock_reserved

    for handler in (on_stock_reserved, on_stock_released):
        with pytest.raises(ValueError, match="EventContext is required"):
            await handler({"items": [{"sku_code": "X", "qty": 1}]}, None)
    with pytest.raises(ValueError, match="EventContext is required"):
        await on_goods_received({"item": "Болт", "qty": 5}, None)
    await logistics_on_doc({"kind": "order", "deal_id": 1}, None)
    await finance_on_doc({"kind": "invoice", "number": "СЧ-1"}, None)


async def test_cross_module_handlers_wrong_kind_are_noop():
    from modules.finance.events import on_document_posted as finance_on_doc
    from modules.logistics.events import on_document_posted as logistics_on_doc

    # не тот тип документа → ранний выход (с непустым ctx, но без побочных эффектов)
    ctx = SimpleNamespace(session=None, services=None)
    await logistics_on_doc({"kind": "invoice"}, ctx)
    await finance_on_doc({"kind": "contract"}, ctx)
