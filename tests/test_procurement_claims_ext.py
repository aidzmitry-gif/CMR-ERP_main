"""Company-owned supplier claims record resolutions, not bank receipts."""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from core.domain.models import Counterparty, OutboxEvent
from modules.finance.models import Payment
from modules.procurement.models import Supplier
from modules.procurement.order_creation import PurchaseOrderCreation  # noqa: F401
from modules.procurement.scoped_claims import ClaimEdit, ClaimOwnership  # noqa: F401

pytestmark = pytest.mark.asyncio
EVENT = "procurement.claim.resolution_recorded"


@pytest_asyncio.fixture
async def api(api, session):
    api.headers["X-User"] = "claims-test-owner"
    party = Counterparty(name="Synthetic claim supplier", unp="999999991")
    session.add(party)
    await session.flush()
    supplier = Supplier(counterparty_id=party.id, name=party.name,
                        unp=party.unp, status="active")
    session.add(supplier)
    await session.commit()
    response = await api.post("/accounting/organizations", json={
        "name": "Synthetic claims company", "unp": "999999994",
    })
    assert response.status_code == 201, response.text
    api.headers["X-Expected-Organization"] = str(response.json()["id"])
    api.headers["X-Expected-Principal"] = "claims-test-owner"
    api.claim_supplier_id = supplier.id
    yield api


def _path(api):
    return f"/procurement/organizations/{api.headers['X-Expected-Organization']}/claims"


async def _create(api, **changes):
    body = {"claim_key": str(uuid4()), "supplier_id": api.claim_supplier_id,
            "supplier": "Synthetic claim supplier", "supplier_unp": "999999991",
            "item": "Synthetic battery", "reason": "Synthetic quality act",
            "claim_type": "брак", "qty_affected": 0,
            "ownership_evidence": "Synthetic company quality act"}
    body.update(changes)
    response = await api.post(_path(api), json=body)
    assert response.status_code == 201, response.text
    assert response.json()["organization_id"] == int(api.headers["X-Expected-Organization"])
    return response.json()["claim"]


def _resolution(**changes):
    return {"edit_key": str(uuid4()), "expected_status": "open", "status": "resolved",
            "resolution": "Synthetic confirmed resolution", **changes}


async def _resolve(api, claim, body=None):
    response = await api.post(f"{_path(api)}/{claim['id']}/resolve",
                              json=body if body is not None else _resolution())
    assert response.status_code == 200, response.text
    return response.json()


async def _claim_events(api, session):
    events = list((await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type.in_((EVENT, "procurement.claim.resolved"))))).all())
    assert all(event.event_type == EVENT for event in events)
    assert all(event.payload["organization_id"] == int(api.headers["X-Expected-Organization"])
               for event in events)
    await session.commit()
    core = api._transport.app.state.core
    assert await core.event_bus.relay_pending(
        core.services.db.session_factory, core.services,
        event_types=(EVENT, "procurement.claim.resolved"),
    ) == len(events)
    for event in events:
        await session.refresh(event)
        assert event.processed_at is not None
    assert await session.scalar(select(func.count()).select_from(Payment)) == 0
    return events


async def test_manual_claim_create(api):
    body = await _create(api, item="АКБ 48V", claim_type="недопоставка",
                         qty_affected=12, amount_byn="3400.00", reason="Пришло 88 из 100")
    assert body["status"] == "open" and body["source"] == "manual"
    assert body["claim_type"] == "недопоставка" and body["qty_affected"] == 12
    assert body["amount_byn"] == "3400.00"
    assert body["supplier_id"] == api.claim_supplier_id


async def test_resolve_emits_event(api, session):
    claim = await _create(api, amount_byn="500.00")
    result = await _resolve(api, claim, _resolution(resolution="Поставщик компенсировал 500 BYN"))
    assert result["claim"]["resolution"] == "Поставщик компенсировал 500 BYN"
    events = await _claim_events(api, session)
    assert len(events) == 1
    payload = events[0].payload
    assert payload["claim_id"] == claim["id"] and payload["supplier_id"] == api.claim_supplier_id
    assert payload["claim_type"] == "брак" and payload["amount_byn"] == "500.00"
    assert payload["status"] == "resolved"


async def test_resolve_enriches_order_id(api, session):
    org = api.headers["X-Expected-Organization"]
    response = await api.post(f"/procurement/organizations/{org}/orders", json={
        "request_key": str(uuid4()), "document": {
            "supplier": "Synthetic claim supplier", "supplier_id": api.claim_supplier_id,
            "supplier_unp": "999999991", "eta_date": None, "freight_byn": "0.00",
            "lines": [{"sku_code": "A", "qty": "1.00", "goods_value_byn": "100.00",
                       "weight": "0.000", "volume": "0.0000"}],
        }, "ownership_evidence": "Synthetic order quality act", "request_basis": None,
    })
    assert response.status_code == 201, response.text
    order = response.json()
    claim = await _create(api, amount_byn="500.00", order_id=order["order_id"])
    assert claim["order_code"] == order["number"]
    await _resolve(api, claim)
    events = await _claim_events(api, session)
    assert len(events) == 1
    assert events[0].payload["order_id"] == order["order_id"]


async def test_resolve_order_id_none_without_order_code(api, session):
    claim = await _create(api, amount_byn="100.00")
    assert claim["order_code"] == ""
    await _resolve(api, claim)
    events = await _claim_events(api, session)
    assert len(events) == 1
    assert events[0].payload["order_id"] is None


async def test_invalid_claim_status_rejected(api, session):
    claim = await _create(api)
    response = await api.post(f"{_path(api)}/{claim['id']}/resolve",
                              json=_resolution(status="closed"))
    assert response.status_code == 422
    assert any(error["loc"][-1] == "status" for error in response.json()["detail"])
    assert await session.scalar(select(func.count()).select_from(ClaimEdit)) == 0
    assert (await api.get(f"{_path(api)}/{claim['id']}")).json()["claim"]["status"] == "open"
    assert await _claim_events(api, session) == []


async def test_resolve_event_not_double_emitted(api, session):
    claim = await _create(api, claim_type="срок")
    command = _resolution(status="rejected")
    first = await _resolve(api, claim, command)
    assert await _resolve(api, claim, command) == first
    path = f"{_path(api)}/{claim['id']}/resolve"
    assert (await api.post(path, json={**command, "resolution": "уточнение"})).status_code == 409
    assert (await api.post(path, json={**command, "edit_key": str(uuid4())})).status_code == 409
    assert await session.scalar(select(func.count()).select_from(ClaimEdit)) == 1
    assert len(await _claim_events(api, session)) == 1
