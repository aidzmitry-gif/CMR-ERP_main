from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from core.domain.models import OutboxEvent
from modules.sales.models import PriceQuote, PriceQuoteRequest


async def test_price_request_exact_replay_lookup_and_conflict(api, session):
    body = {"sku_code": "EXACT", "counterparty": "Synthetic", "price": "12.50", "request_key": str(uuid4())}
    first = await api.post("/sales/prices", json=body)
    assert first.status_code == 201, first.text
    repeated = await api.post("/sales/prices", json={**body, "price": 12.5})
    assert repeated.status_code == 201 and repeated.json() == first.json()
    assert (await api.get(f"/sales/price-requests/{body['request_key']}")).json() == first.json()
    assert (await api.post("/sales/prices", json={**body, "price": "13.00"})).status_code == 409
    assert await session.scalar(select(func.count()).select_from(PriceQuote)) == 1
    assert await session.scalar(select(func.count()).select_from(PriceQuoteRequest)) == 1
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.event_type == "sales.price.quoted")) == 1
    # Historical acknowledgement survives price-row deletion, without resurrecting it.
    await session.execute(delete(PriceQuote))
    await session.commit()
    assert (await api.post("/sales/prices", json=body)).json() == first.json()
    assert await session.scalar(select(func.count()).select_from(PriceQuote)) == 0


async def test_new_price_keys_are_intentional_quotes_and_legacy_response_is_preserved(api, session):
    body = {"sku_code": "EXACT", "counterparty": "Synthetic", "price": 10}
    for _ in range(2):
        assert (await api.post("/sales/prices", json={**body, "request_key": str(uuid4())})).status_code == 201
    legacy = await api.post("/sales/prices", json=body)
    assert legacy.status_code == 201 and legacy.json() == {"ok": True}
    assert await session.scalar(select(func.count()).select_from(PriceQuote)) == 3
    assert (await api.get(f"/sales/price-requests/{uuid4()}")).status_code == 404
    assert (await api.get("/sales/price-requests/not-a-key")).status_code == 422


@pytest.mark.parametrize("price", [0, -1, "0.001", "NaN", "Infinity"])
async def test_price_request_rejects_invalid_exact_amount(api, session, price):
    response = await api.post("/sales/prices", json={"sku_code": "EXACT", "price": price,
        "request_key": str(uuid4())})
    assert response.status_code == 422
    assert await session.scalar(select(func.count()).select_from(PriceQuoteRequest)) == 0
