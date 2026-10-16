from uuid import uuid4

import pytest
from sqlalchemy import func, select

from core.domain.models import OutboxEvent, Sku
from modules.sales.models import Deal, DealItem, DealItemRequest


async def seed(session):
    deal = Deal(number="ITEM-REQUEST", title="Synthetic", counterparty="Synthetic")
    sku = Sku(code="ITEM-REQUEST-SKU", title="Synthetic product", unit="шт")
    session.add_all([deal, sku])
    await session.commit()
    return deal.id, sku.id


async def test_item_request_replays_original_without_duplicate_rows_or_events(api, session):
    deal, sku = await seed(session)
    body = {"sku_id": sku, "qty": "2.50", "request_key": str(uuid4())}
    path = f"/sales/deals/{deal}/items"
    first = await api.post(path, json=body)
    assert first.status_code == 201, first.text
    repeated = await api.post(path, json={**body, "qty": 2.5})
    assert repeated.status_code == 201 and repeated.json() == first.json()
    assert await session.scalar(select(func.count()).select_from(DealItem)) == 1
    assert await session.scalar(select(func.count()).select_from(DealItemRequest)) == 1
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.event_type == "sales.item.changed")) == 1
    assert (await api.post(path, json={**body, "qty": 3})).status_code == 409
    # Deleting an item cannot free a key or resurrect the original on retry.
    assert (await api.delete(f"/sales/deal-items/{first.json()['id']}")).status_code == 204
    replay = await api.post(path, json=body)
    assert replay.status_code == 201 and replay.json() == first.json()
    assert await session.scalar(select(func.count()).select_from(DealItem)) == 0


async def test_new_item_request_allows_intentional_same_sku_batch(api, session):
    deal, sku = await seed(session)
    for _ in range(2):
        result = await api.post(f"/sales/deals/{deal}/items", json={
            "sku_id": sku, "qty": 1, "request_key": str(uuid4()),
        })
        assert result.status_code == 201, result.text
    assert await session.scalar(select(func.count()).select_from(DealItem)) == 2


@pytest.mark.parametrize("qty", [0, -1, "0.001", "NaN", "Infinity"])
async def test_invalid_item_quantity_never_creates_a_receipt(api, session, qty):
    deal, sku = await seed(session)
    response = await api.post(f"/sales/deals/{deal}/items", json={
        "sku_id": sku, "qty": qty, "request_key": str(uuid4()),
    })
    assert response.status_code == 422
    assert await session.scalar(select(func.count()).select_from(DealItemRequest)) == 0
