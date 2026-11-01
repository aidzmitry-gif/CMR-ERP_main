# ruff: noqa: F811 -- shared pytest fixtures are injected by name
"""New Office event projection regressions; isolated SQLite, not PG lock proof."""
from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from core.domain.models import OutboxEvent
from core.services.eventbus import EventContext
from core.services.logistics import ShippingProducerDispatcher
from modules.logistics.canonical_intakes import receive
from modules.logistics.models import (
    CarrierBid,
    CarrierRfq,
    Shipment,
    ShipmentIntake,
    ShipmentInvoiceBinding,
)
from modules.office import events, shipping_projection
from modules.office.models import OfficeDoc
from modules.office.shipping_associations import (
    OfficeInvoiceAssociation,
    source_hash,
)
from modules.office.shipping_producer import OfficeShippingProducer
from modules.sales.shipping_producer import SalesShippingProducer
from tests.test_logistics_invoice_binding import exact  # noqa: F401
from tests.test_office_shipping_associations import (  # noqa: F401
    change_reviewer,
    durable_state,
    office,
    prepare_office,
    replay_setup,
)
from tests.test_sales_shipping_associations import confirmation, order, prepare_order  # noqa: F401


def context(api, session):
    core = api._transport.app.state.core
    core.services.shipping_producer = ShippingProducerDispatcher(
        order=SalesShippingProducer(core), office=OfficeShippingProducer(core))
    return core, EventContext(session, core.services)


async def intake(session, envelope):
    return await session.scalar(select(ShipmentIntake).where(
        ShipmentIntake.source_key == envelope["payload"]["source"]["key"]))


def display_fields(doc):
    return {name: getattr(doc, name) for name in ("logistics_ref", "docs_status", "delivery", "stage", "op_date")}


async def test_shared_order_and_two_office_sources_project_all_exact_documents(api, session, office, order, exact):
    core, ctx = context(api, session)
    order_envelope = await prepare_order(api, order)
    response = await api.post("/sales/deals/1/documents/10/shipping-association-confirm",
        json=confirmation(order_envelope, exact, key="order-bind"))
    assert response.status_code == 200, response.text
    order_intake = await receive(session, core.services, "order", order_envelope["payload"])
    shipment_id = order_intake.shipment_id
    await session.commit()
    _, doc_id, envelope, intake_id = await replay_setup(api, session, office, exact)
    second = OfficeDoc(number="OFF-SECOND", company="Test", title="Same invoice", amount=100, stage="ready")
    legacy = OfficeDoc(number="LEGACY", title="Existing unprotected reference", stage="paid", op_date="2026-09-01")
    session.add_all([second, legacy])
    await session.commit()
    response = await api.post(f"/office/docs/{second.id}/shipping-reviewer", json={
        "subject": "ship-tester", "expected_revision": 0, "evidence": "Synthetic second source"})
    assert response.status_code == 200, response.text
    response = await api.post(f"/office/docs/{second.id}/carrier-request", json={
        "request_key": "office-second", "expected_source_hash": source_hash(second),
        "expected_assignment_revision": 1, "intent": envelope["payload"]["intent"]})
    assert response.status_code == 200, response.text
    second_envelope = response.json()
    response = await api.post(f"/office/docs/{second.id}/shipping-association-confirm",
        json=confirmation(second_envelope, exact, assignment=1, key="second-bind"))
    assert response.status_code == 200, response.text
    second_intake = await receive(session, core.services, "office", second_envelope["payload"])
    assert second_intake.shipment_id == shipment_id == (await intake(session, envelope)).shipment_id
    shipment = await session.get(Shipment, shipment_id)
    shipment.carrier, shipment.tracking_status = "Перевозчик " * 12, "Груз в пути " * 12
    legacy.logistics_ref = shipment.number
    office.stage, office.op_date = "paid", "2026-09-02"
    await session.commit()
    before, hashes = await durable_state(session), [source_hash(doc) for doc in (office, second)]
    await core.event_bus.dispatch("logistics.intake.observed", {"intake_id": order_intake.id}, ctx)
    assert all(doc.logistics_ref == shipment.number for doc in (office, second))
    assert second_intake.shipment_id == shipment_id and intake_id is not None
    await events.on_delivery_tracking({"shipment_id": shipment_id, "log_ref": "FORGED", "carrier_name": "FORGED"}, ctx)
    await session.commit()
    assert all(doc.logistics_ref == shipment.number and len(doc.delivery) == 64 and doc.delivery.endswith("…")
        and len(doc.docs_status) == 64 for doc in (office, second, legacy))
    assert office.stage == legacy.stage == "paid" and office.op_date == "2026-09-02" and legacy.op_date == "2026-09-01"
    assert [source_hash(doc) for doc in (office, second)] == hashes
    assert await durable_state(session) == before  # No fulfillment, outbox, stock, audit or financial mutation.
    assert len(list(await session.scalars(select(Shipment)))) == 1 and doc_id == office.id


async def test_pending_unassociated_intake_projects_no_fulfillment_or_reference(api, session, office):
    core, ctx = context(api, session)
    envelope, _ = await prepare_office(api, office)
    row = await receive(session, core.services, "office", envelope["payload"])
    row_id = row.id
    await session.commit()
    before = await durable_state(session)
    await core.event_bus.dispatch("logistics.intake.observed", {"intake_id": row_id, "state": "resolved"}, ctx)
    await session.commit()
    assert office.docs_status == "Заявка ожидает обработки" and office.logistics_ref == ""
    assert not list(await session.scalars(select(OfficeInvoiceAssociation)))
    assert await durable_state(session) == before


async def test_rfq_before_and_after_real_award_uses_only_the_bound_shipment(api, session, office, exact):
    core, doc_id, envelope, row_id = await replay_setup(api, session, office, exact, mode="contract")
    ctx = EventContext(session, core.services)
    row = await intake(session, envelope)
    rfq_id = row.rfq_id
    await core.event_bus.dispatch("logistics.intake.observed", {"intake_id": row_id}, ctx)
    assert office.docs_status == "Выбор перевозчика" and office.logistics_ref == ""
    session.add(CarrierBid(rfq_id=rfq_id, carrier_code="dpd", price=100))
    await session.commit()
    response = await api.post(f"/logistics/rfqs/{rfq_id}/award", json={"carrier_code": "dpd"})
    assert response.status_code == 200, response.text
    awarded = response.json()
    await core.event_bus.dispatch("logistics.contract.signed", {"rfq_id": rfq_id, "shipment_number": "FORGED"}, ctx)
    await session.commit()
    assert office.logistics_ref == awarded["shipment_number"] and office.delivery
    assert office.stage == "ready" and office.op_date is None and office.id == doc_id


async def test_current_saved_facts_override_stale_event_and_prelock_snapshot(api, session, office, exact, monkeypatch):
    core, _, envelope, _ = await replay_setup(api, session, office, exact)
    row = await intake(session, envelope)
    shipment_id = row.shipment_id
    gateway = core.services.logistics
    original = gateway.office_shipping_projection_context
    calls = 0

    async def changed_after_discovery(*args, **kwargs):
        nonlocal calls
        result = await original(*args, **kwargs)
        calls += 1
        if calls == 1:
            await session.execute(update(Shipment).where(Shipment.id == shipment_id).values(status="delivered"))
            assert result["shipment"]["status"] == "planned"
        return result

    monkeypatch.setattr(gateway, "office_shipping_projection_context", changed_after_discovery)
    await events.on_delivery_tracking({"shipment_id": shipment_id, "tracking_status": "Old transit"}, EventContext(session, core.services))
    assert calls == 2 and office.docs_status == "Доставлено, закрываем документы"
    assert office.op_date is None and office.stage == "ready"
    await session.commit()
    # Event name is not proof of delivery either.
    await session.execute(update(Shipment).where(Shipment.id == shipment_id).values(status="planned"))
    await session.commit()
    await events.on_delivery_delivered({"shipment_id": shipment_id, "delivered_at": "2099-01-01"}, EventContext(session, core.services))
    assert office.docs_status == "Доставка запланирована" and office.op_date is None


async def test_changed_source_group_fails_before_any_display_assignment(api, session, office, exact, monkeypatch):
    core, _, _, row_id = await replay_setup(api, session, office, exact)
    original = core.services.logistics.office_shipping_projection_context
    calls = 0

    async def changed_group(*args, **kwargs):
        nonlocal calls
        result = deepcopy(await original(*args, **kwargs))
        calls += 1
        if calls == 2:
            result["sources"].append(deepcopy(result["sources"][0]))
        return result

    monkeypatch.setattr(core.services.logistics, "office_shipping_projection_context", changed_group)
    before = display_fields(office)
    with pytest.raises(HTTPException) as error:
        await shipping_projection.on_intake_observed({"intake_id": row_id}, EventContext(session, core.services))
    assert error.value.status_code == 409 and display_fields(office) == before
    assert not session.dirty


@pytest.mark.parametrize("tamper", ["reference", "invoice_binding", "association_confirmation", "pending_reference", "rfq_reference"])
async def test_projection_refuses_conflicting_or_corrupt_lineage(api, session, office, exact, tamper):
    core, _, envelope, row_id = await replay_setup(api, session, office, exact,
        mode="contract" if tamper == "rfq_reference" else "spot",
        state="pending" if tamper == "pending_reference" else "resolved")
    row = await intake(session, envelope)
    row_id = row.id
    if tamper in {"reference", "pending_reference", "rfq_reference"}:
        office.logistics_ref = "OTHER-DELIVERY"
    elif tamper == "invoice_binding":
        await session.execute(update(ShipmentInvoiceBinding).where(ShipmentInvoiceBinding.shipment_id == row.shipment_id)
            .values(content_sha256="0" * 64))
    else:
        await session.execute(update(OfficeInvoiceAssociation).values(confirmation_sha256="0" * 64))
    await session.commit()
    before = display_fields(office)
    with pytest.raises(HTTPException) as error:
        await shipping_projection.on_intake_observed({"intake_id": row_id}, EventContext(session, core.services))
    assert error.value.status_code == 409 and display_fields(office) == before
    assert not session.dirty


@pytest.mark.parametrize("kind", ["pending", "shipment", "rfq"])
async def test_cancel_wakeup_reads_withdrawal_and_preserves_history_without_r6(api, session, office, exact, kind):
    core, _, envelope, _ = await replay_setup(api, session, office, exact,
        mode="contract" if kind == "rfq" else "spot", state="pending" if kind == "pending" else "resolved")
    row = await intake(session, envelope)
    row_id = row.id
    ctx = EventContext(session, core.services)
    await shipping_projection.on_intake_observed({"intake_id": row_id}, ctx)
    await session.commit()
    reference = office.logistics_ref
    if kind == "pending":
        row.state, row.pending_reason = "withdrawn", "Synthetic recorded withdrawal"
    else:
        target = await session.get(CarrierRfq if kind == "rfq" else Shipment, row.rfq_id if kind == "rfq" else row.shipment_id)
        target.status = "withdrawn"
    office.stage, office.op_date = "paid", "2026-09-09"
    await session.commit()
    await change_reviewer(api, session, office.id, "revoke")
    before = await durable_state(session)
    payload = {"organization_id": exact["organization_id"], "document_id": exact["document_id"],
        "document_version": exact["expected_version"], "content_sha256": exact["expected_content_sha256"]}
    fields = display_fields(office)
    await shipping_projection.on_invoice_cancelled({**payload, "content_sha256": "0" * 64}, ctx)
    assert display_fields(office) == fields  # Foreign exact identity cannot select this source.
    await shipping_projection.on_invoice_cancelled(payload, ctx)
    await session.commit()
    assert "отозвана" in office.docs_status and office.logistics_ref == reference
    assert office.stage == "paid" and office.op_date == "2026-09-09"
    assert await durable_state(session) == before
    assert (await session.get(ShipmentIntake, row_id)).state == ("withdrawn" if kind == "pending" else "resolved")


async def test_new_id_events_reject_malformed_ids_and_keep_legacy_protected_guard(api, session, office, exact):
    core, _, _, _ = await replay_setup(api, session, office, exact)
    ctx = EventContext(session, core.services)
    before = display_fields(office)
    await events.on_delivery_delivered({"doc_number": office.number, "carrier_name": "Forged", "delivered_at": "2099-01-01"}, ctx)
    assert display_fields(office) == before
    for value in (None, True, "1", 0, -1):
        with pytest.raises(HTTPException) as error:
            await events.on_delivery_delivered({"shipment_id": value, "doc_number": office.number}, ctx)
        assert error.value.status_code == 422 and display_fields(office) == before


async def test_authorized_resolve_reconciles_history_and_publishers_send_saved_ids_without_eta_date(api, session, office, exact):
    core, _, envelope, _ = await replay_setup(api, session, office, exact, state="pending")
    row = await intake(session, envelope)
    row_id = row.id
    for _ in range(2):
        response = await api.post(f"/logistics/intakes/{row_id}/resolve")
        assert response.status_code == 200, response.text
    shipment_id = response.json()["shipment_id"]
    observed = list(await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "logistics.intake.observed")))
    assert len(observed) == 2 and all(event.payload["intake_id"] == row_id for event in observed)
    assert len(list(await session.scalars(select(Shipment)))) == 1
    response = await api.patch(f"/logistics/shipments/{shipment_id}/tracking", json={
        "tracking_status": "Synthetic transit", "eta": "2026-12-31"})
    assert response.status_code == 200, response.text
    response = await api.patch(f"/logistics/shipments/{shipment_id}", json={"status": "in_transit"})
    assert response.status_code == 200, response.text
    response = await api.patch(f"/logistics/shipments/{shipment_id}", json={"status": "delivered"})
    assert response.status_code == 200, response.text
    wakeups = list(await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type.in_(
        ["logistics.delivery.tracking", "logistics.delivery.delivered"])).order_by(OutboxEvent.id)))
    assert len(wakeups) == 3 and all(event.payload["shipment_id"] == shipment_id for event in wakeups)
    assert wakeups[-1].payload["delivered_at"] == ""
    ctx = EventContext(session, core.services)
    for event in reversed(wakeups):
        await core.event_bus.dispatch(event.event_type, event.payload, ctx)
    await session.commit()
    assert office.docs_status == "Доставлено, закрываем документы" and office.op_date is None
    assert office.stage == "ready" and len(list(await session.scalars(select(ShipmentIntake)))) == 1
