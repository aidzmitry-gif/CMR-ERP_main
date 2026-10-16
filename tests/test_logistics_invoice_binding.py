"""Real SQLite models and sales/accounting facades; no production proof registry."""
import hashlib
from datetime import datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from core.domain.models import AuditLog, OutboxEvent
from core.runtime.app import create_app
from core.services.eventbus import OutboxEventBus
from modules.accounting.models import AccessGrant, Organization
from modules.logistics import events
from modules.logistics.models import (
    CarrierBid,
    CarrierRfq,
    CarrierRfqInvite,
    FreightAuditLog,
    Shipment,
    ShipmentIntake,
    ShipmentInvoiceBinding,
)
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import Deal, DealDocument


@pytest_asyncio.fixture
async def exact(session, api):
    api.headers.update({"X-User": "ship-tester"})
    for org in (1, 2):
        session.add(Organization(id=org, name=f"Org{org}", unp=f"99999990{org}"))
    session.add(AccessGrant(organization_id=1, subject="ship-tester", role="chief"))
    await session.flush()
    for docid in (1, 2):
        session.add(Deal(id=docid, number=f"D{docid}", title="Synthetic", counterparty="Synthetic"))
    await session.flush()
    identities = []
    for docid in (1, 2):
        html = f"<p>original {docid}</p>"
        sha = hashlib.sha256(html.encode()).hexdigest()
        session.add(DealDocument(id=docid, deal_id=docid, number=f"I{docid}", kind="invoice",
            status="paid", reserve_status="reserved", version=1, amount=100,
            content_sha256=sha, original_html=html, issued_at=datetime(2026, 9, 10),
            snapshot_json={"items": [{"sku_code": "A", "qty": "2"}]}))
        session.add(DealOwnership(deal_id=docid, organization_id=docid, snapshot={}, evidence="test", actor="test"))
        identities.append(dict(organization_id=docid, document_id=docid,
            expected_version=1, expected_content_sha256=sha))
    await session.commit()
    return identities[0]


async def post_ship(api, exact, key="s1", **data):
    return await api.post("/logistics/shipments", json={"invoice": exact, "source_key": key,
                                                       "customer": "Synthetic", **data})


async def test_http_all_four_paths_and_idempotency(api, session, exact):
    first = await post_ship(api, exact)
    assert first.status_code == 201, first.text
    sid = first.json()["id"]
    assert first.json()["organization_id"] == 1
    assert (await post_ship(api, exact)).json()["id"] == sid
    assert (await post_ship(api, exact, customer="changed")).status_code == 409
    await session.rollback()
    result = await api.post(f"/logistics/shipments/{sid}/carrier-order", json={"carrier_code": "dpd"})
    assert result.status_code == 200, result.text
    assert (await api.patch(f"/logistics/shipments/{sid}/tracking", json={"tracking_status": "Assigned"})).status_code == 200
    assert (await api.patch(f"/logistics/shipments/{sid}", json={"status": "delivered"})).status_code == 200
    assert (await api.patch(f"/logistics/shipments/{sid}", json={"status": "planned"})).status_code == 409
    assert len(list(await session.scalars(select(ShipmentInvoiceBinding)))) == 1


@pytest.mark.parametrize("field,value", [("expected_version", 2), ("expected_content_sha256", "0" * 64),
                                         ("organization_id", 2)])
async def test_invalid_source_never_creates(api, session, exact, field, value):
    response = await post_ship(api, {**exact, field: value})
    assert response.status_code in (403, 409)
    assert list(await session.scalars(select(Shipment))) == []


async def test_legacy_and_foreign_reads(api, session, exact):
    session.add(Shipment(customer="Unknown"))
    await session.commit()
    sid = (await post_ship(api, exact)).json()["id"]
    rows = (await api.get("/logistics/shipments")).json()
    assert len(rows) == 1 and rows[0]["id"] == sid
    other = {"X-User": "foreign", "X-User-Roles": "logistics"}
    session.add(AccessGrant(organization_id=2, subject="foreign", role="reader"))
    await session.commit()
    assert (await api.get("/logistics/shipments", headers=other)).json() == []
    assert (await api.post(f"/logistics/shipments/{sid}/quote", json={"zone_code": "z2"}, headers=other)).status_code == 404
    assert (await api.patch(f"/logistics/shipments/{sid}", json={"status": "delivered"}, headers=other)).status_code == 404
    for endpoint in ("dashboard", "costs", "cost-insights"):
        response = await api.get("/logistics/" + endpoint)
        assert response.status_code == 409 and response.json()["detail"] == "organization_scope_incomplete"


async def test_rfq_award_bound_atomic_and_retry(api, session, exact):
    response = await api.post("/logistics/rfqs", json={"invoice": exact, "source_key": "r1", "cargo": "A"})
    assert response.status_code == 201, response.text
    rid = response.json()["id"]
    session.add(CarrierBid(rfq_id=rid, carrier_code="dpd", price=100))
    await session.commit()
    first = await api.post(f"/logistics/rfqs/{rid}/award", json={})
    assert first.status_code == 200, first.text
    again = await api.post(f"/logistics/rfqs/{rid}/award", json={})
    assert first.json()["shipment_id"] == again.json()["shipment_id"]
    assert len(list(await session.scalars(select(ShipmentInvoiceBinding)))) == 1
    assert (await api.get(f"/logistics/rfqs/{rid}", headers={"X-User": "unknown"})).status_code == 404


@pytest.mark.parametrize("kind,mode", [("order", "spot"), ("office", "spot"), ("office", "contract")])
async def test_event_pending_then_persisted_resolution(session, api, exact, kind, mode):
    core = create_app().state.core
    ctx = SimpleNamespace(session=session, services=core.services)
    payload = {"kind": "order", "mode": mode, "source_key": "producer:1", "source_revision": "1",
               "company": "Synthetic", "weight": "2.25"}
    handler = events.on_document_posted if kind == "order" else events.on_office_delivery_requested
    await handler(payload, ctx)
    await handler(payload, ctx)
    assert list(await session.scalars(select(Shipment))) == []
    pending = list(await session.scalars(select(ShipmentIntake)))
    assert len(pending) == 1 and pending[0].state == "pending"

    class TestProducer:
        async def resolve_shipping_source(self, session, **lookup):
            assert lookup == dict(source_kind=kind, source_key="producer:1", source_revision="1")
            return exact

    core.services.shipping_producer = TestProducer()
    await handler(payload, ctx)
    await handler(payload, ctx)
    assert pending[0].state == "resolved"
    if mode == "contract":
        assert pending[0].rfq_id and not pending[0].shipment_id
    else:
        assert pending[0].shipment_id
        assert str((await session.get(Shipment, pending[0].shipment_id)).weight_kg) == "2.25"


async def test_terminal_invoice_blocked_and_no_implicit_identity(api, session, exact):
    assert (await api.post("/logistics/shipments", json={"customer": "X"})).status_code == 422
    # Synthetic terminal fixture; cancellation service belongs to its own suite.
    await session.execute(update(DealDocument).where(DealDocument.id == exact["document_id"]).values(status="cancelled"))
    await session.commit()
    assert (await post_ship(api, exact)).status_code == 409


async def test_membership_is_not_logistics_write(api, session, exact):
    # finance has package access and book membership but no logistics permission.
    response = await post_ship_with_headers(api, exact, {"X-User-Roles": "finance"})
    assert response.status_code == 403


async def post_ship_with_headers(api, exact, headers):
    return await api.post("/logistics/shipments", json={"invoice": exact, "source_key": "k", "customer": "X"}, headers=headers)


@pytest.mark.parametrize("suffix,method,payload", [
    ("", "patch", {"status": "delivered"}),
    ("/carrier-order", "post", {"carrier_code": "dpd"}),
    ("/tracking", "patch", {"tracking_status": "late"}),
])
async def test_existing_writer_rechecks_terminal_source(api, session, exact, suffix, method, payload):
    sid = (await post_ship(api, exact)).json()["id"]
    await session.execute(update(DealDocument).where(DealDocument.id == 1).values(reserve_status="released"))
    await session.commit()
    response = await getattr(api, method)(f"/logistics/shipments/{sid}{suffix}", json=payload)
    assert response.status_code == 409
    assert (await session.get(Shipment, sid)).status == "planned"


async def test_binding_cannot_be_reassigned(api, session, exact):
    sid = (await post_ship(api, exact)).json()["id"]
    binding = await session.get(ShipmentInvoiceBinding, sid)
    binding.organization_id = 2
    with pytest.raises(ValueError, match="immutable"):
        await session.flush()
    await session.rollback()


async def test_pending_http_resolve_requires_real_producer_service(api, session, exact, monkeypatch):
    core = api._transport.app.state.core
    monkeypatch.setattr(core.services, "shipping_producer", None)
    await events.on_office_delivery_requested({"source_key": "office:1", "source_revision": "1"},
        SimpleNamespace(session=session, services=core.services))
    await session.commit()
    intake = (await session.scalars(select(ShipmentIntake))).one()
    response = await api.post(f"/logistics/intakes/{intake.id}/resolve")
    assert response.status_code == 503
    assert intake.state == "pending"


@pytest.mark.parametrize("suffix,payload", [
    ("/carrier-order", {"carrier_code": "cdek", "shipping_cost": 999, "payer": "клиент"}),
    ("/tracking", {"tracking_status": "rewritten", "tracking_no": "OTHER"}),
    ("", {"status": "planned"}),
])
async def test_delivered_live_invoice_cannot_rewrite_freight(api, session, exact, suffix, payload):
    sid = (await post_ship(api, exact, amount=80, carrier_code="dpd", carrier="DPD")).json()["id"]
    assert (await api.patch(f"/logistics/shipments/{sid}", json={"status": "delivered"})).status_code == 200
    row = await session.get(Shipment, sid)
    before = {col.name: getattr(row, col.name) for col in Shipment.__table__.columns}
    cost_events = list(await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == "logistics.freight.cost")))
    assert len(cost_events) == 1 and float(cost_events[0].payload["amount"]) == 80
    method = api.post if suffix == "/carrier-order" else api.patch
    response = await method(f"/logistics/shipments/{sid}{suffix}", json=payload)
    assert response.status_code == 409
    await session.refresh(row)
    assert before == {col.name: getattr(row, col.name) for col in Shipment.__table__.columns}
    # Exact delivered retry remains harmless and does not re-emit or correct costs.
    assert (await api.patch(f"/logistics/shipments/{sid}", json={"status": "delivered"})).status_code == 200
    assert len(list(await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == "logistics.freight.cost")))) == 1


@pytest.mark.parametrize("role", ["director", "logistics"])
async def test_unscoped_audit_get_post_seed_neither_leak_nor_write(api, session, exact, role):
    secret = FreightAuditLog(shipment_code="FOREIGN-SHIP", carrier_code="dpd", invoice_amount=900,
                            expected_amount=100, variance=800, reason="foreign commercial detail", status="open")
    session.add(secret)
    await session.commit()
    before = {col.name: getattr(secret, col.name) for col in FreightAuditLog.__table__.columns}
    headers = {"X-User-Roles": role}
    responses = [
        await api.get("/logistics/costs/audit?period=2026-09", headers=headers),
        await api.post("/logistics/costs/audit", headers=headers, json={"shipment_code": "FOREIGN-SHIP",
            "carrier_code": "dpd", "invoice_amount": 1000, "expected_amount": 0, "reason": "overwrite"}),
        await api.post("/logistics/costs/audit/seed", headers=headers),
    ]
    for response in responses:
        assert response.status_code == 409
        assert response.json() == {"detail": "organization_scope_incomplete"}
    await session.refresh(secret)
    assert before == {col.name: getattr(secret, col.name) for col in FreightAuditLog.__table__.columns}
    assert len(list(await session.scalars(select(FreightAuditLog)))) == 1
    assert list(await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == "logistics.freight.audit_refund"))) == []


@pytest.mark.parametrize("event_type,payload,handler", [
    ("sales.document.posted", {"kind": "order"}, events.on_document_posted),
    ("logistics.delivery.requested", {"source_key": "office:ctx"}, events.on_office_delivery_requested),
])
async def test_deliver_missing_context_never_acknowledges_intake(session, event_type, payload, handler):
    bus = OutboxEventBus()
    bus.subscribe(event_type, handler)
    event = OutboxEvent(event_type=event_type, version=1, payload=payload)
    session.add(event)
    await session.flush()
    with pytest.raises(ValueError, match="requires event context"):
        await bus._deliver(session, event, None)
    await session.flush()
    await session.refresh(event)
    assert event.processed_at is None
    assert list(await session.scalars(select(ShipmentIntake))) == []
    assert list(await session.scalars(select(AuditLog))) == []


async def test_deliver_unrelated_sales_kind_remains_ignored_without_context(session):
    bus = OutboxEventBus()
    bus.subscribe("sales.document.posted", events.on_document_posted)
    event = OutboxEvent(event_type="sales.document.posted", version=1, payload={"kind": "contract"})
    session.add(event)
    await session.flush()
    await bus._deliver(session, event, None)
    await session.flush()
    assert event.processed_at is not None
    assert list(await session.scalars(select(ShipmentIntake))) == []
    assert len(list(await session.scalars(select(AuditLog)))) == 1


@pytest.mark.parametrize("action,payload", [
    ("broadcast", {}),
    ("bids", {"carrier_code": "dpd", "price": 50}),
    ("negotiate", {"carrier_code": "dpd", "new_price": 50}),
    ("public", {"price": 50, "eta_days": 1}),
])
async def test_awarded_rfq_terms_are_terminal(api, session, exact, action, payload):
    response = await api.post("/logistics/rfqs", json={"invoice": exact, "source_key": "terminal-rfq", "cargo": "A"})
    assert response.status_code == 201
    rid = response.json()["id"]
    bid = CarrierBid(rfq_id=rid, carrier_code="dpd", price=100)
    invitation = CarrierRfqInvite(rfq_id=rid, carrier_code="dpd", token="terminal-token", status="invited")
    session.add_all([bid, invitation])
    await session.commit()
    award = await api.post(f"/logistics/rfqs/{rid}/award", json={"carrier_code": "dpd"})
    assert award.status_code == 200
    rfq = await session.get(CarrierRfq, rid)
    before = {col.name: getattr(rfq, col.name) for col in CarrierRfq.__table__.columns}
    before_events = list(await session.scalars(select(OutboxEvent.id)))
    url = "/logistics/rfqs/bid/terminal-token" if action == "public" else f"/logistics/rfqs/{rid}/{action}"
    rejected = await api.post(url, json=payload)
    assert rejected.status_code == 409
    await session.refresh(rfq)
    await session.refresh(invitation)
    assert before == {col.name: getattr(rfq, col.name) for col in CarrierRfq.__table__.columns}
    assert invitation.status == "invited"
    assert len(list(await session.scalars(select(CarrierBid).where(CarrierBid.rfq_id == rid)))) == 1
    assert list(await session.scalars(select(OutboxEvent.id))) == before_events
    history = await api.get(f"/logistics/rfqs/{rid}")
    assert history.status_code == 200 and history.json()["status"] == "contracted"
    replay = await api.post(f"/logistics/rfqs/{rid}/award", json={"carrier_code": "dpd"})
    assert replay.status_code == 200 and replay.json() == award.json()
    assert list(await session.scalars(select(OutboxEvent.id))) == before_events


@pytest.mark.parametrize("field,precision", [("weight", 12), ("amount", 14)])
@pytest.mark.parametrize("invalid", ["bad", "", "NaN", "Infinity", "-1", "0.001", True, "1000000000000"])
def test_shipping_numbers_reject_invalid_values(field, precision, invalid):
    from fastapi import HTTPException

    from modules.logistics.shipment_writer import shipping_number

    with pytest.raises(HTTPException) as caught:
        shipping_number({field: invalid}, field, precision)
    assert caught.value.status_code == 422


@pytest.mark.parametrize("field,precision", [("weight", 12), ("amount", 14)])
def test_shipping_numbers_preserve_zero_and_exact_value(field, precision):
    from decimal import Decimal

    from modules.logistics.shipment_writer import shipping_number

    assert shipping_number({}, field, precision) == Decimal("0")
    assert shipping_number({field: "0.00"}, field, precision) == Decimal("0.00")
    assert shipping_number({field: "123.45"}, field, precision) == Decimal("123.45")


@pytest.mark.parametrize("mode,field", [("spot", "weight"), ("contract", "weight"), ("contract", "amount")])
async def test_invalid_numeric_payload_never_promotes(session, api, exact, mode, field):
    from fastapi import HTTPException

    core = create_app().state.core
    ctx = SimpleNamespace(session=session, services=core.services)
    payload = {"source_key": "invalid:1", "source_revision": "1", "mode": mode, field: "bad"}

    class Producer:
        async def resolve_shipping_source(self, session, **lookup):
            return exact

    core.services.shipping_producer = Producer()
    with pytest.raises(HTTPException) as caught:
        await events.on_office_delivery_requested(payload, ctx)
    assert caught.value.status_code == 422
    await session.rollback()
    assert list(await session.scalars(select(Shipment))) == []
    assert list(await session.scalars(select(CarrierRfq))) == []
    assert list(await session.scalars(select(ShipmentInvoiceBinding))) == []


@pytest.mark.parametrize("rfq", [False, True])
@pytest.mark.parametrize("terminal", ["cancelled", "released"])
async def test_exact_http_create_replay_after_terminal_does_not_fulfill(api, session, exact, rfq, terminal):
    endpoint = "/logistics/rfqs" if rfq else "/logistics/shipments"
    body = {"invoice": exact, "source_key": "historical-retry", "cargo": "Synthetic"}
    if not rfq:
        body["customer"] = "Synthetic"
    first = await api.post(endpoint, json=body)
    assert first.status_code == 201, first.text
    row_id = first.json()["id"]
    values = {"status": "cancelled"} if terminal == "cancelled" else {"reserve_status": "released"}
    await session.execute(update(DealDocument).where(DealDocument.id == 1).values(**values))
    await session.commit()
    replay = await api.post(endpoint, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == row_id
    changed = await api.post(endpoint, json={**body, "cargo": "Changed"})
    assert changed.status_code == 409
    new = await api.post(endpoint, json={**body, "source_key": "new-after-terminal"})
    assert new.status_code == 409
    forbidden = await api.post(endpoint, json=body, headers={"X-User": "unknown", "X-User-Roles": "logistics"})
    assert forbidden.status_code == 403
    await session.rollback()
    assert len(list(await session.scalars(select(CarrierRfq if rfq else Shipment)))) == 1


@pytest.mark.parametrize("prefix", ["execution:", "intake:", "rfq-award:"])
@pytest.mark.parametrize("rfq", [False, True])
async def test_http_cannot_preempt_internal_workflow_keys(api, session, exact, prefix, rfq):
    body = {"invoice": exact, "source_key": prefix + "1", "cargo": "Tampered"}
    if not rfq:
        body["customer"] = "Synthetic"
    response = await api.post("/logistics/rfqs" if rfq else "/logistics/shipments", json=body)
    assert response.status_code == 422
    assert list(await session.scalars(select(CarrierRfq if rfq else Shipment))) == []
