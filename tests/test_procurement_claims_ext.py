"""Owned manual supplier claims and replay-safe resolution events.

Resolution records a company fact; it must not imply an unowned cash receipt.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.domain.models import Counterparty, OutboxEvent
from modules.procurement import scoped_claims  # noqa: F401 -- register tables before the session fixture.
from modules.procurement.models import Supplier

pytestmark = pytest.mark.asyncio


async def _claim_events(session):
    events = list(await session.scalars(select(OutboxEvent)))
    assert not any(e.event_type == "procurement.claim.resolved" for e in events)
    return [e for e in events if e.event_type == "procurement.claim.resolution_recorded"]


async def _context(api, session, supplier_id=5):
    api.headers.update({"X-User": "claim-owner-test", "X-Expected-Principal": "claim-owner-test"})
    response = await api.post("/accounting/organizations", json={
        "name": "Synthetic claim company", "unp": "999999984",
    })
    assert response.status_code == 201, response.text
    org = response.json()["id"]
    party = Counterparty(name="Synthetic supplier", unp="999999985")
    session.add(party)
    await session.flush()
    session.add(Supplier(id=supplier_id, counterparty_id=party.id, name=party.name,
                         unp=party.unp, status="active"))
    await session.commit()
    return org, supplier_id


async def _create(api, org, supplier_id, **changes):
    body = {"claim_key": str(uuid4()), "supplier_id": supplier_id, "supplier": "Synthetic supplier",
            "supplier_unp": "999999985", "item": "Synthetic claimed item", "reason": "Synthetic supplier issue",
            "claim_type": "брак", "qty_affected": 0,
            "ownership_evidence": "Synthetic primary claim reviewed for this company"}
    body.update(changes)
    if body.get("amount_byn") is not None:
        body["amount_byn"] = f"{Decimal(str(body['amount_byn'])):.2f}"
    return await api.post(f"/procurement/organizations/{org}/claims", json=body)


def _resolution(status="resolved", resolution="Synthetic resolution"):
    return {"edit_key": str(uuid4()), "expected_status": "open", "status": status, "resolution": resolution}


async def _resolve(api, org, claim_id, body):
    return await api.post(f"/procurement/organizations/{org}/claims/{claim_id}/resolve", json=body)


async def test_manual_claim_create(api, session):
    org, supplier = await _context(api, session)
    r = await _create(api, org, supplier, item="АКБ 48V", claim_type="недопоставка",
                      qty_affected=12, amount_byn=3400, reason="Пришло 88 из 100")
    assert r.status_code == 201, r.text
    result = r.json()
    body = result["claim"]
    assert result["organization_id"] == org
    assert body["status"] == "open" and body["source"] == "manual"
    assert body["claim_type"] == "недопоставка" and body["qty_affected"] == 12
    assert Decimal(body["amount_byn"]) == Decimal("3400.00")
    assert body["supplier_id"] == 5


async def test_resolve_emits_event(api, session):
    org, supplier = await _context(api, session)
    created = await _create(api, org, supplier, amount_byn=500)
    assert created.status_code == 201, created.text
    claim = created.json()["claim"]
    r = await _resolve(api, org, claim["id"], _resolution(resolution="Поставщик компенсировал 500 BYN"))
    assert r.status_code == 200, r.text
    assert r.json()["claim"]["resolution"] == "Поставщик компенсировал 500 BYN"
    events = await _claim_events(session)
    assert len(events) == 1
    p = events[0].payload
    assert p["organization_id"] == org
    assert p["claim_id"] == claim["id"] and p["supplier_id"] == 5
    assert p["claim_type"] == "брак" and p["amount_byn"] == "500.00"
    assert p["status"] == "resolved"


async def test_resolve_enriches_order_id(api, session):
    """The resolution carries the explicitly selected owned order identity."""
    org, supplier = await _context(api, session)
    response = await api.post(f"/procurement/organizations/{org}/orders", json={
        "request_key": str(uuid4()), "ownership_evidence": "Synthetic related order",
        "request_basis": None, "document": {"supplier_id": supplier, "supplier": "Synthetic supplier",
            "supplier_unp": "999999985", "freight_byn": "0.00", "lines": [
                {"sku_code": "A", "qty": "1.00", "goods_value_byn": "100.00", "weight": "0.000", "volume": "0.0000"}]},
    })
    assert response.status_code == 201, response.text
    order_id = response.json()["order_id"]
    created = await _create(api, org, supplier, amount_byn=500, order_id=order_id)
    assert created.status_code == 201, created.text
    result = await _resolve(api, org, created.json()["claim"]["id"], _resolution())
    assert result.status_code == 200, result.text
    events = await _claim_events(session)
    assert len(events) == 1
    assert events[0].payload["order_id"] == order_id


async def test_resolve_order_id_none_without_order_code(api, session):
    org, supplier = await _context(api, session)
    created = await _create(api, org, supplier, amount_byn=100)
    assert created.status_code == 201, created.text
    response = await _resolve(api, org, created.json()["claim"]["id"], _resolution())
    assert response.status_code == 200, response.text
    events = await _claim_events(session)
    assert len(events) == 1
    assert events[0].payload["order_id"] is None


async def test_invalid_claim_status_rejected(api, session):
    org, supplier = await _context(api, session, supplier_id=1)
    created = await _create(api, org, supplier)
    assert created.status_code == 201, created.text
    r = await _resolve(api, org, created.json()["claim"]["id"], _resolution(status="closed"))
    assert r.status_code == 422
    assert await _claim_events(session) == []


async def test_resolve_event_not_double_emitted(api, session):
    org, supplier = await _context(api, session, supplier_id=1)
    created = await _create(api, org, supplier, claim_type="срок")
    assert created.status_code == 201, created.text
    claim_id = created.json()["claim"]["id"]
    body = _resolution(status="rejected")
    first = await _resolve(api, org, claim_id, body)
    assert first.status_code == 200, first.text
    assert (await _resolve(api, org, claim_id, body)).json() == first.json()
    changed = await _resolve(api, org, claim_id, {**body, "resolution": "уточнение"})
    assert changed.status_code == 409
    assert len(await _claim_events(session)) == 1
