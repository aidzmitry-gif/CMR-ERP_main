# ruff: noqa: F811 -- imported pytest fixtures
"""Actual SQLite adapters and caller-owned withdrawal; not complete cancel proof."""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from core.services.auth import CurrentUser
from core.services.logistics import snapshot_row
from modules.logistics.canonical_intakes import receive
from modules.logistics.models import (
    CarrierBid,
    CarrierRfq,
    CarrierRfqInvite,
    Shipment,
    ShipmentIntake,
    ShippingExecution,
)
from modules.office.shipping_associations import (  # noqa: F401
    OfficeInvoiceAssociation,
    ShippingRequest,
    ShippingReviewAssignment,
)
from modules.sales.models import DealDocument
from modules.sales.shipping_associations import OrderInvoiceAssociation, ShippingEnvelope
from tests.test_logistics_invoice_binding import exact  # noqa: F401
from tests.test_sales_shipping_associations import confirmation, order, prepare_order  # noqa: F401
from tests.test_shipping_payload import payload


def core(api):
    return api._transport.app.state.core


def receipt(exact):
    return {"exact_invoice": exact, "cancellation_receipt_id": str(uuid4()), "cancellation_request_sha256": "a" * 64}


async def collect(api, session, exact):
    gateway = core(api).services.logistics
    prepared = await gateway.prepare_invoice_fulfillment_snapshot(session, exact_invoice=exact,
        user=CurrentUser("ship-tester", ["director"]))
    return prepared, await gateway.collect_prepared_invoice_fulfillment_snapshot(session, prepared)


async def withdraw(api, session, exact, prepared=None, snapshot=None, digest=None, address=None):
    if prepared is None:
        prepared, snapshot = await collect(api, session, exact)
    return await core(api).services.logistics.withdraw_unexecuted_invoice(session, prepared=prepared,
        current_snapshot=snapshot, expected_digest=digest or snapshot["sha256"], cancel_receipt_identity=address or receipt(exact))


async def targets(api, exact):
    ship = await api.post("/logistics/shipments", json={"invoice": exact, "source_key": "withdraw-ship", "customer": "Synthetic"})
    rfq = await api.post("/logistics/rfqs", json={"invoice": exact, "source_key": "withdraw-rfq", "cargo": "Synthetic"})
    assert ship.status_code == rfq.status_code == 201
    return ship.json()["id"], rfq.json()["id"]


async def producer(api, session, order, exact, *, resolved=False):
    intent = {**payload()["intent"], "carrier_name": "", "carrier_code": ""}
    envelope = await prepare_order(api, order, intent)
    if not resolved:
        await receive(session, core(api).services, "order", envelope["payload"])
        await session.commit()
    response = await api.post("/sales/deals/1/documents/10/shipping-association-confirm", json=confirmation(envelope, exact))
    assert response.status_code == 200, response.text
    if resolved:
        await receive(session, core(api).services, "order", envelope["payload"])
        await session.commit()
    return envelope


async def domain(session):
    return {m.__name__: [snapshot_row(r) for r in await session.scalars(select(m).order_by(m.id))]
        for m in (Shipment, CarrierRfq, ShipmentIntake, ShippingExecution, OrderInvoiceAssociation, ShippingEnvelope)}


async def test_withdraw_safe_targets_pending_atomic_rollback(api, session, exact, order):
    await targets(api, exact)
    await producer(api, session, order, exact)
    before = await domain(session)
    prepared, snap = await collect(api, session, exact)
    result = await withdraw(api, session, exact, prepared, snap)
    assert len(result["changes"]) == 3 and result["coverage_complete"] is False
    after = await domain(session)
    assert after["Shipment"][0]["status"] == after["CarrierRfq"][0]["status"] == "withdrawn"
    assert after["ShipmentIntake"][0]["state"] == "withdrawn"
    for name in ("ShippingExecution", "OrderInvoiceAssociation", "ShippingEnvelope"):
        assert after[name] == before[name]
    with pytest.raises(HTTPException) as error:
        await withdraw(api, session, exact, prepared, snap)
    assert error.value.status_code == 409
    await session.rollback()
    assert await domain(session) == before


@pytest.mark.parametrize("model,field,value", [
    (Shipment, "status", "assigned"), (Shipment, "status", "in_transit"), (Shipment, "status", "delivered"),
    (Shipment, "carrier", "Selected preference"), (Shipment, "carrier_code", "dpd"),
    (Shipment, "carrier_order_no", "BOOKED"), (Shipment, "tracking_no", "TRACK"),
    (Shipment, "tracking_status", "picked up"), (Shipment, "amount", 1), (Shipment, "eta", "tomorrow"),
    (CarrierRfq, "status", "sent"), (CarrierRfq, "status", "collecting"), (CarrierRfq, "status", "negotiation"),
    (CarrierRfq, "status", "awarded"), (CarrierRfq, "status", "contracted"),
    (CarrierRfq, "shipment_id", 1), (CarrierRfq, "awarded_carrier_code", "dpd"), (CarrierRfq, "awarded_price", 1),
])
async def test_risky_target_blocks_all_writes(api, session, exact, model, field, value):
    await targets(api, exact)
    await session.execute(update(model).values({field: value}))
    await session.commit()
    before = await domain(session)
    with pytest.raises(HTTPException) as error:
        await withdraw(api, session, exact)
    assert error.value.status_code == 409
    assert await domain(session) == before


@pytest.mark.parametrize("engagement", ["bid", "sent", "invited", "viewed", "responded", "declined", "unknown"])
async def test_any_tender_engagement_blocks(api, session, exact, engagement):
    _, rid = await targets(api, exact)
    session.add(CarrierBid(rfq_id=rid, carrier_code="dpd", price=1) if engagement == "bid" else
        CarrierRfqInvite(rfq_id=rid, carrier_code="dpd", status=engagement))
    await session.commit()
    before = await domain(session)
    with pytest.raises(HTTPException) as error:
        await withdraw(api, session, exact)
    assert error.value.status_code == 409
    assert await domain(session) == before


@pytest.mark.parametrize("change", ["digest", "actual", "foreign_receipt", "expired", "dirty"])
async def test_withdraw_context_and_current_rows_rechecked(api, session, exact, change):
    sid, _ = await targets(api, exact)
    prepared, snap = await collect(api, session, exact)
    address = receipt(exact)
    if change == "actual":
        await session.execute(update(Shipment).where(Shipment.id == sid).values(customer="changed"))
    elif change == "foreign_receipt":
        address["exact_invoice"] = {**exact, "organization_id": 2}
    elif change == "expired":
        await session.commit()
    elif change == "dirty":
        (await session.get(Shipment, sid)).customer = "dirty"
    with pytest.raises(HTTPException) as error:
        await withdraw(api, session, exact, prepared, snap, "0" * 64 if change == "digest" else None, address)
    assert error.value.status_code == 409
    await session.rollback()
    assert (await session.get(Shipment, sid)).status == "planned"


async def test_withdrawn_targets_block_late_http_writers(api, session, exact):
    sid, rid = await targets(api, exact)
    await withdraw(api, session, exact)
    await session.commit()
    before = await domain(session)
    for method, url, data in (
        ("PATCH", f"/logistics/shipments/{sid}", {"status": "assigned"}),
        ("POST", f"/logistics/shipments/{sid}/carrier-order", {"carrier_code": "dpd"}),
        ("PATCH", f"/logistics/shipments/{sid}/tracking", {"tracking_status": "moving"}),
        ("POST", f"/logistics/rfqs/{rid}/broadcast", {}),
        ("POST", f"/logistics/rfqs/{rid}/bids", {"carrier_code": "dpd", "price": 1}),
        ("POST", f"/logistics/rfqs/{rid}/negotiate", {"carrier_code": "dpd", "new_price": 1}),
        ("POST", f"/logistics/rfqs/{rid}/award", {"carrier_code": "dpd"}),
    ):
        response = await api.request(method, url, json=data)
        assert response.status_code == 409, (url, response.text)
    assert await domain(session) == before
    # A late token is synthetic stale external input; terminal guard is still required.
    session.add(CarrierRfqInvite(rfq_id=rid, carrier_code="dpd", token="late-token"))
    await session.commit()
    response = await api.post("/logistics/rfqs/bid/late-token", json={"price": 1, "eta_days": 1})
    assert response.status_code == 409
    assert not list(await session.scalars(select(CarrierBid)))


@pytest.mark.parametrize("resolved", [False, True])
async def test_terminal_intake_event_exact_replay_preserves_history(api, session, order, exact, resolved):
    envelope = await producer(api, session, order, exact, resolved=resolved)
    result = await withdraw(api, session, exact)
    await session.execute(update(DealDocument).where(DealDocument.id == exact["document_id"]).values(status="cancelled"))
    await session.commit()
    before = await domain(session)
    intake = await receive(session, core(api).services, "order", envelope["payload"])
    assert intake.state == ("resolved" if resolved else "withdrawn")
    assert intake.observed_transition is False
    await session.commit()
    assert await domain(session) == before
    assert result["resolved_intake_ids_preserved"] == ([intake.id] if resolved else [])
    if not resolved:
        response = await api.post(f"/logistics/intakes/{intake.id}/resolve")
        assert response.status_code == 409
    forged = {**envelope["payload"], "intent": {**envelope["payload"]["intent"], "cargo": "forged"}}
    with pytest.raises(HTTPException):
        await receive(session, core(api).services, "order", forged)


async def test_unknown_intake_untouched_and_legacy_promote_terminal(api, session, exact):
    from modules.logistics.shipment_writer import promote

    row = ShipmentIntake(source_kind="office", source_key="unknown-private", source_revision="1", request_digest="0" * 64,
        snapshot={}, pending_reason="unknown", state="withdrawn")
    session.add(row)
    await session.commit()
    before = snapshot_row(row)
    await withdraw(api, session, exact)
    assert snapshot_row(row) == before
    with pytest.raises(HTTPException) as error:
        await promote(session, core(api), row, exact)
    assert error.value.status_code == 409


async def test_cancelled_invoice_exact_create_replay_but_no_new_work(api, session, exact):
    sid, _ = await targets(api, exact)
    await withdraw(api, session, exact)
    await session.execute(update(DealDocument).where(DealDocument.id == exact["document_id"]).values(status="cancelled"))
    await session.commit()
    before = await domain(session)
    body = {"invoice": exact, "source_key": "withdraw-ship", "customer": "Synthetic"}
    replay = await api.post("/logistics/shipments", json=body)
    assert replay.status_code == 201 and replay.json()["id"] == sid and replay.json()["status"] == "withdrawn"
    rejected = await api.post("/logistics/shipments", json={**body, "source_key": "late-new"})
    assert rejected.status_code == 409
    assert await domain(session) == before


async def test_cancelled_bound_source_without_intake_does_not_insert(api, session, exact, order):
    envelope = await prepare_order(api, order)
    result = await api.post("/sales/deals/1/documents/10/shipping-association-confirm", json=confirmation(envelope, exact))
    assert result.status_code == 200
    await session.execute(update(DealDocument).where(DealDocument.id == exact["document_id"]).values(status="cancelled"))
    await session.commit()
    before = await domain(session)
    with pytest.raises(HTTPException) as error:
        await receive(session, core(api).services, "order", envelope["payload"])
    assert error.value.status_code == 409
    assert await domain(session) == before
    assert not session.new and not session.dirty


async def test_foreign_bound_risky_shipment_is_untouched(api, session, exact):
    from modules.logistics.shipment_writer import create

    await targets(api, exact)
    doc = await session.get(DealDocument, 2)
    foreign = {"organization_id": 2, "document_id": 2, "expected_version": doc.version,
        "expected_content_sha256": doc.content_sha256}
    row = await create(session, core(api), foreign, "foreign-risky", {"customer": "Foreign", "status": "assigned",
        "carrier_order_no": "external-booking"})
    await session.commit()
    before = snapshot_row(row)
    result = await withdraw(api, session, exact)
    assert len(result["changes"]) == 2
    assert snapshot_row(row) == before


async def test_legacy_resolved_historical_replay_after_cancel(api, session, exact, order):
    from modules.logistics.shipment_writer import receive as legacy_receive

    envelope = await prepare_order(api, order)
    result = await api.post("/sales/deals/1/documents/10/shipping-association-confirm", json=confirmation(envelope, exact))
    assert result.status_code == 200
    legacy = {"source_key": "sales:order:10", "source_revision": "1", "company": "Synthetic", "title": "Legacy"}
    row = await legacy_receive(session, core(api).services, "order", legacy)
    await session.commit()
    await session.execute(update(DealDocument).where(DealDocument.id == exact["document_id"]).values(status="cancelled"))
    await session.commit()
    before = await domain(session)
    replay = await legacy_receive(session, core(api).services, "order", legacy)
    assert replay.id == row.id and replay.observed_transition is False
    await session.commit()
    response = await api.post(f"/logistics/intakes/{row.id}/resolve")
    assert response.status_code == 200, response.text
    assert await domain(session) == before
