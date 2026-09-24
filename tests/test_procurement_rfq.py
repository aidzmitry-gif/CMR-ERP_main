"""Тесты RFQ / тендера закупки: запрос цен → предложения → выбор победителя + событие.

Сравнение предложений сортируется по цене (минимальная — лучшая, best_bid_id).
``award`` помечает победителя, закрывает RFQ и эмитит ``procurement.rfq.awarded``.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.procurement.models import PurchaseOrder

pytestmark = pytest.mark.asyncio


async def test_unscoped_order_creation_cannot_bypass_organization(api, session):
    response = await api.post("/procurement/orders", json={
        "supplier": "Free text", "lines": [{"sku_code": "A", "qty": 1, "goods_value_byn": 10}],
    })
    assert response.status_code == 410
    assert (await session.scalars(select(PurchaseOrder.id))).all() == []


async def test_rfq_flow_award_and_event(api, session):
    rfq = (
        await api.post("/procurement/rfq", json={"item": "АКБ 48V", "sku_code": "AKB-48", "qty": 100})
    ).json()
    rid = rfq["id"]
    assert rfq["status"] == "open"

    # два предложения: 1200 и 950 (лучшее — 950)
    await api.post(f"/procurement/rfq/{rid}/bids", json={"supplier_id": 1, "price_byn": 1200, "lead_time_days": 30})
    last = (await api.post(f"/procurement/rfq/{rid}/bids", json={"supplier_id": 2, "price_byn": 950, "lead_time_days": 45})).json()

    # bids отсортированы по цене, лучшая помечена
    assert [b["price_byn"] for b in last["bids"]] == [950.0, 1200.0]
    best = next(b for b in last["bids"] if b["id"] == last["best_bid_id"])
    assert best["price_byn"] == 950.0

    win_bid_id = best["id"]
    awarded = (await api.post(f"/procurement/rfq/{rid}/award", json={"bid_id": win_bid_id})).json()
    assert awarded["status"] == "awarded"
    winners = [b for b in awarded["bids"] if b["is_winner"]]
    assert len(winners) == 1 and winners[0]["id"] == win_bid_id

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "procurement.rfq.awarded" in types


async def test_rfq_award_unknown_bid_404(api):
    rfq = (await api.post("/procurement/rfq", json={"item": "X"})).json()
    r = await api.post(f"/procurement/rfq/{rfq['id']}/award", json={"bid_id": 99999})
    assert r.status_code == 404


async def test_rfq_closed_rejects_bids(api):
    rfq = (await api.post("/procurement/rfq", json={"item": "X"})).json()
    rid = rfq["id"]
    bid = (await api.post(f"/procurement/rfq/{rid}/bids", json={"supplier_id": 1, "price_byn": 100})).json()
    await api.post(f"/procurement/rfq/{rid}/award", json={"bid_id": bid["bids"][0]["id"]})
    # после award RFQ закрыт — новые предложения не принимаются
    r = await api.post(f"/procurement/rfq/{rid}/bids", json={"supplier_id": 3, "price_byn": 80})
    assert r.status_code == 409


async def test_reaward_rejected(api):
    """Повторный award уже закрытого RFQ → 409 (нельзя переиграть тендер)."""
    rfq = (await api.post("/procurement/rfq", json={"item": "X"})).json()
    rid = rfq["id"]
    bid = (await api.post(f"/procurement/rfq/{rid}/bids", json={"supplier_id": 1, "price_byn": 100})).json()
    bid_id = bid["bids"][0]["id"]
    assert (await api.post(f"/procurement/rfq/{rid}/award", json={"bid_id": bid_id})).status_code == 200
    assert (await api.post(f"/procurement/rfq/{rid}/award", json={"bid_id": bid_id})).status_code == 409


async def test_negative_bid_price_rejected(api):
    rfq = (await api.post("/procurement/rfq", json={"item": "X"})).json()
    r = await api.post(f"/procurement/rfq/{rfq['id']}/bids", json={"supplier_id": 1, "price_byn": -5})
    assert r.status_code == 422


async def test_award_selects_winner_without_creating_unowned_order(api, session):
    """An unscoped RFQ cannot create an order or a payment forecast for an unknown company."""
    rfq = (
        await api.post("/procurement/rfq", json={"item": "АКБ", "sku_code": "AKB-1", "qty": 10})
    ).json()
    rid = rfq["id"]
    await api.post(f"/procurement/rfq/{rid}/bids", json={"supplier_id": 7, "price_byn": 20})
    bid = (await api.post(f"/procurement/rfq/{rid}/bids", json={"supplier_id": 9, "price_byn": 15})).json()
    win = bid["best_bid_id"]  # 15 — лучшая цена
    awarded = (await api.post(f"/procurement/rfq/{rid}/award", json={"bid_id": win})).json()

    assert awarded["status"] == "awarded" and awarded["created_order_id"] is None
    assert [b["supplier_id"] for b in awarded["bids"] if b["is_winner"]] == [9]
    assert (await session.scalars(select(PurchaseOrder.id))).all() == []
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    assert any(e.event_type == "procurement.rfq.awarded" for e in events)
    assert not any(e.event_type == "procurement.po.drafted" for e in events)


async def test_rfq_404(api):
    assert (await api.get("/procurement/rfq/9999")).status_code == 404
