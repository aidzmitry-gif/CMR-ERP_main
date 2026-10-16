"""The legacy RFQ API cannot create, expose or award an unowned document.

The supported company workflow is exercised in accounting/test_scoped_rfq.py.
"""
import pytest
from sqlalchemy import func, select

from core.domain.models import OutboxEvent
from modules.procurement.models import Rfq, RfqBid

pytestmark = pytest.mark.asyncio


async def test_unscoped_rfq_routes_do_not_write_or_publish(api, session):
    assert (await api.get("/procurement/rfq")).status_code == 410
    assert (await api.post("/procurement/rfq", json={"item": "Без юрлица"})).status_code == 410
    assert (await api.get("/procurement/rfq/1")).status_code == 410
    assert (await api.post("/procurement/rfq/1/bids", json={
        "supplier_id": 1, "price_byn": 100,
    })).status_code == 410
    assert (await api.post("/procurement/rfq/1/award", json={"bid_id": 1})).status_code == 410
    assert (await session.scalar(select(func.count()).select_from(Rfq))) == 0
    assert (await session.scalar(select(func.count()).select_from(RfqBid))) == 0
    assert not (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == "procurement.rfq.awarded"))).all()
