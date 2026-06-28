"""Тесты RFQ / тендера закупки: запрос цен → предложения → выбор победителя + событие.

Сравнение предложений сортируется по цене (минимальная — лучшая, best_bid_id).
``award`` помечает победителя, закрывает RFQ и эмитит ``procurement.rfq.awarded``.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent

pytestmark = pytest.mark.asyncio


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


async def test_award_creates_draft_po_and_emits_po_drafted(api, session):
    """P7: award → черновик PO у победителя с позицией из RFQ + эмит procurement.po.drafted."""
    rfq = (
        await api.post("/procurement/rfq", json={"item": "АКБ", "sku_code": "AKB-1", "qty": 10})
    ).json()
    rid = rfq["id"]
    await api.post(f"/procurement/rfq/{rid}/bids", json={"supplier_id": 7, "price_byn": 20})
    bid = (await api.post(f"/procurement/rfq/{rid}/bids", json={"supplier_id": 9, "price_byn": 15})).json()
    win = bid["best_bid_id"]  # 15 — лучшая цена
    awarded = (await api.post(f"/procurement/rfq/{rid}/award", json={"bid_id": win})).json()

    oid = awarded["created_order_id"]
    assert oid is not None
    order = (await api.get(f"/procurement/orders/{oid}")).json()
    assert order["status"] == "draft"  # черновик, не «в пути»
    assert order["supplier_id"] == 9
    assert len(order["lines"]) == 1
    ln = order["lines"][0]
    assert ln["sku_code"] == "AKB-1" and ln["qty"] == 10.0
    assert ln["goods_value_byn"] == 150.0  # цена 15 × кол-во 10

    drafted = [
        e for e in (await session.execute(select(OutboxEvent))).scalars().all()
        if e.event_type == "procurement.po.drafted"
    ]
    assert len(drafted) == 1
    p = drafted[0].payload
    assert p["po_ref"] == order["number"]
    assert p["supplier_id"] == 9
    assert p["planned_amount"] == "150.00"  # str(BYN) для finance FIN-B1
    assert p["currency"] == "BYN"
    assert p["deal_id"] is None  # PO обслуживает много сделок (фриз §2)


async def test_rfq_404(api):
    assert (await api.get("/procurement/rfq/9999")).status_code == 404
