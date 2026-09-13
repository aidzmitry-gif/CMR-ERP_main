"""Won handoff must not replace confirmed/unknown line prices with quote history."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent, Sku
from core.services.eventbus import EventContext
from modules.sales.events import on_deal_won_handoff
from modules.sales.models import Deal, DealItem, PriceQuote


@pytest.mark.parametrize('prices,cost,expected', [
    ([125.50],10,231.0),([0],10,-20.0),([None],10,None),
    ([125.50,None],10,None),([125.50,0],10,211.0),
    ([125.50],None,None),([125.50],'10.0025',231.0),
    ([125.50,0],100,-149.0),([125.50],0,251.0),
])
async def test_handoff_uses_each_confirmed_line_and_complete_cost(api,session,prices,cost,expected):
    deal=Deal(number='HANDOFF-MONEY',title='Synthetic',counterparty='Buyer',amount=9999)
    sku=Sku(code='HANDOFF-MONEY',title='Synthetic',unit='шт')
    session.add_all([deal,sku])
    await session.flush()
    session.add_all([DealItem(deal_id=deal.id,sku_id=sku.id,qty=2,unit_price=p) for p in prices])
    session.add(PriceQuote(sku_code=sku.code,counterparty=deal.counterparty,price=999))
    await session.commit()
    services=api._transport.app.state.core.services
    original=services.landed_cost
    services.landed_cost=SimpleNamespace(last_landed_cost_batch=AsyncMock(return_value={
        sku.code:None if cost is None else {'unit_landed_cost_byn':cost}}))
    try:
        ctx=EventContext(session=session,services=services)
        await on_deal_won_handoff({'deal_id':deal.id},ctx)
        await session.commit()
        await on_deal_won_handoff({'deal_id':deal.id},ctx)
        await session.commit()
    finally:
        services.landed_cost=original
    events=(await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type=='sales.deal.handoff'))).all()
    assert len(events)==1
    assert events[0].payload['gross_profit']==expected
    assert events[0].payload['amount']==9999  # Commercial amount is not an invoice/payment total.
