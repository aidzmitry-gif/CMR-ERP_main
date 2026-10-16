# ruff: noqa: F811 -- imported pytest fixtures are injected by parameter name
"""Real Office/ Sales adapters and shared execution; SQLite is not concurrency proof."""
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, update

from core.domain.models import OutboxEvent, User
from core.runtime.app import create_app
from core.services.auth import CurrentUser
from modules.logistics.models import ShippingExecution
from modules.office import events
from modules.office.models import OfficeDoc
from modules.office.shipping_access import assign_reviewer, visible_docs
from modules.office.shipping_associations import (
    OfficeInvoiceAssociation,
    ShippingRequest,
    source_hash,
)
from modules.office.shipping_producer import ConfirmInput, OfficeShippingProducer, RequestInput
from modules.sales.models import DealDocument
from tests.test_logistics_invoice_binding import exact  # noqa: F401
from tests.test_sales_shipping_associations import confirmation, order, prepare_order  # noqa: F401
from tests.test_shipping_payload import payload


@pytest_asyncio.fixture
async def office(session, api, exact):
    session.add(User(username="ship-tester", full_name="Reviewer", role="director", status="active"))
    doc = OfficeDoc(number="OFF-1", company="Test", title="Goods", amount=100, stage="ready")
    session.add(doc)
    await session.commit()
    response = await api.post(f"/office/docs/{doc.id}/shipping-reviewer", json={
        "subject": "ship-tester", "expected_revision": 0, "evidence": "Review original shipment document"})
    assert response.status_code == 200, response.text
    return doc


async def prepare_office(api, office, intent=None):
    data = {"request_key": "office-1", "expected_source_hash": source_hash(office),
            "expected_assignment_revision": 1, "intent": intent or payload()["intent"]}
    response = await api.post(f"/office/docs/{office.id}/carrier-request", json=data)
    assert response.status_code == 200, response.text
    return response.json(), data


async def test_reverse_snapshot_current_scope_is_opaque(api, session, office, exact):
    from core.runtime.contract import Role

    envelope, _ = await prepare_office(api, office)
    response = await api.post(f"/office/docs/{office.id}/shipping-association-confirm", json=confirmation(envelope, exact, assignment=1))
    assert response.status_code == 200, response.text
    core = api._transport.app.state.core
    core.declare_role(Role("snapshot-office-reader", permissions=("office.doc.read",)))
    producer = OfficeShippingProducer(core)
    user = CurrentUser("ship-tester", ["snapshot-office-reader"])
    discovery = await producer.discover_invoice_shipping_sources(session, exact_invoice=exact, user=user)
    result = await producer.lock_invoice_shipping_sources_snapshot(session, exact_invoice=exact, user=user, discovery=discovery)
    assert len(result["sources"]) == 1
    await assign_reviewer(core, session, office.id, CurrentUser("ship-tester", ["director"]),
        subject="", expected_revision=1, evidence="Access revoked")
    await session.commit()
    with pytest.raises(HTTPException) as error:
        await producer.discover_invoice_shipping_sources(session, exact_invoice=exact, user=user)
    assert error.value.status_code == 403 and error.value.detail == "producer_scope_unavailable"


async def test_office_http_same_request_and_late_bind_same_hash(api, session, office, exact):
    envelope, data = await prepare_office(api, office)
    assert (await api.post(f"/office/docs/{office.id}/carrier-request", json=data)).json() == envelope
    producer = OfficeShippingProducer(create_app().state.core)
    lookup = dict(source_kind="office", source_key=envelope["payload"]["source"]["key"], source_revision="1")
    assert await producer.resolve_shipping_source(session, **lookup) is None
    confirm = confirmation(envelope, exact, assignment=1)
    url = f"/office/docs/{office.id}/shipping-association-"
    assert (await api.post(url + "preview", json=confirm)).status_code == 200
    assert not list(await session.scalars(select(ShippingExecution)))
    first = await api.post(url + "confirm", json=confirm)
    assert first.status_code == 200, first.text
    repeat = await api.post(url + "confirm", json=confirm)
    assert repeat.status_code == 200 and repeat.json()["replayed"]
    verified = await producer.verify_shipping_source(session, **lookup, actual_payload_hash=envelope["payload_sha256"])
    assert verified["execution_id"] == first.json()["execution_id"]
    assert (await session.get(ShippingRequest, envelope["envelope_id"])).payload_sha256 == envelope["payload_sha256"]
    assert len(list(await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "logistics.delivery.requested")))) == 1


@pytest.mark.parametrize("different", [None, "route_to", "cargo", "mode"])
async def test_order_and_office_real_shared_execution(api, session, office, order, exact, different):
    order_envelope = await prepare_order(api, order)
    first = await api.post("/sales/deals/1/documents/10/shipping-association-confirm", json=confirmation(order_envelope, exact))
    assert first.status_code == 200, first.text
    intent = payload()["intent"]
    if different:
        intent[different] = "contract" if different == "mode" else "Other value"
    envelope, _ = await prepare_office(api, office, intent)
    result = await api.post(f"/office/docs/{office.id}/shipping-association-confirm", json=confirmation(envelope, exact, assignment=1))
    assert result.status_code == (409 if different else 200), result.text
    if not different:
        assert result.json()["execution_id"] == first.json()["execution_id"]
    assert len(list(await session.scalars(select(ShippingExecution)))) == 1


async def test_revoke_before_bind_rejected_and_stale_revision_conflicts(api, session, office, exact):
    doc_id = office.id
    envelope, _ = await prepare_office(api, office)
    data = confirmation(envelope, exact, assignment=1)
    response = await api.post(f"/office/docs/{office.id}/shipping-reviewer", json={
        "subject": "", "expected_revision": 1, "evidence": "Assignment revoked"})
    assert response.status_code == 200
    response = await api.post(f"/office/docs/{office.id}/shipping-association-confirm", json=data)
    assert response.status_code == 404
    assert not list(await session.scalars(select(OfficeInvoiceAssociation)))
    with pytest.raises(HTTPException) as error:
        await assign_reviewer(create_app().state.core, session, doc_id, CurrentUser("ship-tester", ["director"]),
            subject="ship-tester", expected_revision=1, evidence="Stale change")
    assert error.value.status_code == 409


async def test_revoke_after_bind_blocks_automatic_verification(api, session, office, exact):
    envelope, _ = await prepare_office(api, office)
    data = confirmation(envelope, exact, assignment=1)
    assert (await api.post(f"/office/docs/{office.id}/shipping-association-confirm", json=data)).status_code == 200
    assert (await api.post(f"/office/docs/{office.id}/shipping-reviewer", json={
        "subject": "", "expected_revision": 1, "evidence": "Revoke before promotion"})).status_code == 200
    producer = OfficeShippingProducer(create_app().state.core)
    verified = await producer.verify_shipping_source(session, source_kind="office",
        source_key=envelope["payload"]["source"]["key"], source_revision="1", actual_payload_hash=envelope["payload_sha256"])
    assert verified["fulfillment_allowed"] is False
    assert verified["exact_invoice"] == exact


async def test_unknown_scope_does_not_follow_owner_text_or_global_chief(api, session, office):
    # Test role grants only document read, not assignment privilege.
    from core.runtime.contract import Role

    core = create_app().state.core
    core.declare_role(Role("office-reader-test", permissions=("office.doc.read",)))
    user = CurrentUser("another-chief", ["office-reader-test"])
    office.owner = "another-chief"
    await session.flush()
    assert await visible_docs(core, session, user) == []
    assigned = CurrentUser("ship-tester", ["office-reader-test"])
    assert [d.id for d in await visible_docs(core, session, assigned)] == [office.id]


@pytest.mark.parametrize("tamper", ["payload", "snapshot", "source", "evidence"])
async def test_office_saved_integrity_tamper_rejected(api, session, office, exact, tamper):
    envelope, _ = await prepare_office(api, office)
    producer = OfficeShippingProducer(create_app().state.core)
    data = ConfirmInput.model_validate(confirmation(envelope, exact, assignment=1))
    await producer.association(session, office.id, data, CurrentUser("ship-tester", ["director"]), confirm=True)
    await session.commit()
    if tamper == "payload":
        changed = {**envelope["payload"], "intent": {**envelope["payload"]["intent"], "cargo": "Forged"},
                   "payload_sha256": envelope["payload_sha256"]}
        await session.execute(update(ShippingRequest).values(payload=changed))
    elif tamper == "snapshot":
        await session.execute(update(ShippingRequest).values(source_snapshot={"forged": True}))
    elif tamper == "source":
        await session.execute(update(OfficeDoc).where(OfficeDoc.id == office.id).values(address="Changed"))
    else:
        await session.execute(update(OfficeInvoiceAssociation).values(evidence_refs={
            **data.evidence_refs.model_dump(), "source_sha256": "0" * 64}))
    with pytest.raises(HTTPException) as error:
        await producer.verify_shipping_source(session, source_kind="office",
            source_key=envelope["payload"]["source"]["key"], source_revision="1", actual_payload_hash=envelope["payload_sha256"])
    assert error.value.status_code == 409


async def test_terminal_invoice_new_binding_and_legacy_request_rejected(api, session, office, exact):
    doc_id = office.id
    envelope, _ = await prepare_office(api, office)
    await session.execute(update(DealDocument).where(DealDocument.id == 1).values(status="cancelled"))
    await session.commit()
    result = await api.post(f"/office/docs/{office.id}/shipping-association-confirm", json=confirmation(envelope, exact, assignment=1))
    assert result.status_code == 409
    result = await api.post(f"/office/docs/{doc_id}/carrier-request", json={"carrier": "dpd"})
    assert result.status_code == 422


async def test_legacy_reference_cannot_mutate_protected_office(api, session, office):
    await prepare_office(api, office)
    ctx = SimpleNamespace(session=session, services=create_app().state.core.services)
    await events.on_delivery_delivered({"doc_number": office.number, "carrier_name": "FORGED", "delivered_at": "today"}, ctx)
    await session.refresh(office)
    assert office.delivery == "" and office.op_date is None


async def test_assignment_inactive_and_anonymous_fail(api, session, office):
    session.add(User(username="inactive", full_name="Inactive", status="disabled"))
    await session.commit()
    result = await api.post(f"/office/docs/{office.id}/shipping-reviewer", json={
        "subject": "inactive", "expected_revision": 1, "evidence": "Assignment"})
    assert result.status_code == 422
    assert (await api.get("/office/docs", headers={"X-User": "anonymous"})).status_code == 403


async def test_request_and_event_rollback_together(api, session, office):
    producer = OfficeShippingProducer(create_app().state.core)
    await producer.prepare(session, office.id, RequestInput(request_key="rollback", expected_source_hash=source_hash(office),
        expected_assignment_revision=1, intent=payload()["intent"]), CurrentUser("ship-tester", ["director"]))
    await session.rollback()
    assert not list(await session.scalars(select(ShippingRequest)))
    assert not list(await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "logistics.delivery.requested")))


async def replay_setup(api, session, office, exact, *, mode="spot", state="resolved"):
    from core.services.logistics import ShippingProducerDispatcher
    from modules.logistics.canonical_intakes import receive
    from modules.sales.shipping_producer import SalesShippingProducer

    core = api._transport.app.state.core
    core.services.shipping_producer = ShippingProducerDispatcher(
        order=SalesShippingProducer(core), office=OfficeShippingProducer(core))
    doc_id = office.id
    envelope, _ = await prepare_office(api, office, {**payload()["intent"], "mode": mode})
    if state == "pending":
        row = await receive(session, core.services, "office", envelope["payload"])
        assert row.state == "pending"
        await session.commit()
    result = await api.post(f"/office/docs/{doc_id}/shipping-association-confirm",
        json=confirmation(envelope, exact, assignment=1))
    assert result.status_code == 200, result.text
    intake_id = None
    if state == "resolved":
        row = await receive(session, core.services, "office", envelope["payload"])
        assert row.state == "resolved"
        intake_id = row.id
        await session.commit()
    return core, doc_id, envelope, intake_id


async def change_reviewer(api, session, doc_id, change):
    if change == "reassign":
        session.add(User(username="replacement", full_name="Replacement", role="director", status="active"))
        await session.commit()
    result = await api.post(f"/office/docs/{doc_id}/shipping-reviewer", json={
        "subject": "replacement" if change == "reassign" else "", "expected_revision": 1, "evidence": "Change reviewer"})
    assert result.status_code == 200, result.text
    if change == "return":
        result = await api.post(f"/office/docs/{doc_id}/shipping-reviewer", json={
            "subject": "ship-tester", "expected_revision": 2, "evidence": "New reviewer mandate"})
        assert result.status_code == 200, result.text


async def durable_state(session):
    from core.domain.models import AuditLog
    from modules.logistics.models import CarrierRfq, Shipment, ShipmentIntake
    from modules.wms.models import StockMovement

    result = {}
    for model in (ShippingExecution, Shipment, CarrierRfq, ShipmentIntake, OutboxEvent, StockMovement, AuditLog):
        rows = list(await session.scalars(select(model).order_by(model.id).execution_options(populate_existing=True)))
        result[model.__name__] = [{c.name: getattr(row, c.name) for c in model.__table__.columns} for row in rows]
    return result


@pytest.mark.parametrize("mode", ["spot", "contract"])
@pytest.mark.parametrize("change", ["revoke", "reassign", "return"])
async def test_exact_resolved_auto_replay_after_reviewer_change_has_no_effects(api, session, office, exact, mode, change):
    from modules.logistics.canonical_intakes import receive

    core, doc_id, envelope, intake_id = await replay_setup(api, session, office, exact, mode=mode)
    await change_reviewer(api, session, doc_id, change)
    before = await durable_state(session)
    row = await receive(session, core.services, "office", envelope["payload"])
    assert row.id == intake_id and row.state == "resolved"
    await session.commit()
    assert await durable_state(session) == before
    if change != "return":
        response = await api.post(f"/logistics/intakes/{intake_id}/resolve")
        assert response.status_code in {403, 404}, response.text
    else:
        # Current authorized reviewer may inspect/retry history; a new mandate
        # still does not authorize new fulfillment of the old pending request.
        response = await api.post(f"/logistics/intakes/{intake_id}/resolve")
        assert response.status_code == 200, response.text
    response = await api.post(f"/logistics/intakes/{intake_id}/resolve",
        headers={"X-User": "unassigned-chief", "X-User-Roles": "director"})
    assert response.status_code in {403, 404}, response.text


@pytest.mark.parametrize("state", ["pending", "new"])
@pytest.mark.parametrize("change", ["revoke", "reassign", "return"])
async def test_changed_reviewer_blocks_pending_or_new_promotion(api, session, office, exact, state, change):
    from modules.logistics.canonical_intakes import receive

    core, doc_id, envelope, _ = await replay_setup(api, session, office, exact, state=state)
    await change_reviewer(api, session, doc_id, change)
    before = await durable_state(session)
    with pytest.raises(HTTPException) as error:
        await receive(session, core.services, "office", envelope["payload"])
    assert error.value.status_code == 409
    await session.rollback()
    assert await durable_state(session) == before


@pytest.mark.parametrize("tamper", ["incoming", "snapshot", "historical_subject", "historical_missing"])
async def test_revoked_resolved_replay_still_checks_immutable_history(api, session, office, exact, tamper):
    from sqlalchemy import delete

    from modules.logistics.canonical_intakes import receive
    from modules.logistics.models import ShipmentIntake
    from modules.office.shipping_associations import ShippingReviewAssignment

    core, doc_id, envelope, intake_id = await replay_setup(api, session, office, exact)
    await change_reviewer(api, session, doc_id, "revoke")
    incoming = envelope["payload"]
    forged = {**incoming, "intent": {**incoming["intent"], "cargo": "Forged"}, "payload_sha256": envelope["payload_sha256"]}
    if tamper == "incoming":
        incoming = forged
    elif tamper == "snapshot":
        await session.execute(update(ShipmentIntake).where(ShipmentIntake.id == intake_id).values(snapshot=forged))
    elif tamper == "historical_subject":
        await session.execute(update(ShippingReviewAssignment).where(ShippingReviewAssignment.revision == 1).values(subject="forged"))
    else:
        await session.execute(delete(ShippingReviewAssignment).where(ShippingReviewAssignment.revision == 1))
    await session.commit()
    with pytest.raises(HTTPException) as error:
        await receive(session, core.services, "office", incoming)
    assert error.value.status_code == 409
    await session.rollback()


async def test_current_reviewer_does_not_override_terminal_invoice_for_pending(api, session, office, exact):
    from modules.logistics.canonical_intakes import receive

    core, _, envelope, _ = await replay_setup(api, session, office, exact, state="pending")
    await session.execute(update(DealDocument).where(DealDocument.id == 1).values(status="cancelled"))
    await session.commit()
    verified = await core.services.shipping_producer.verify_shipping_source(session, source_kind="office",
        source_key=envelope["payload"]["source"]["key"], source_revision="1", actual_payload_hash=envelope["payload_sha256"])
    assert verified["fulfillment_allowed"] is True
    before = await durable_state(session)
    with pytest.raises(HTTPException) as error:
        await receive(session, core.services, "office", envelope["payload"])
    assert error.value.status_code == 409
    await session.rollback()
    assert await durable_state(session) == before


def test_client_cannot_supply_fulfillment_permission():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RequestInput.model_validate({"request_key": "forged", "expected_source_hash": "0" * 64,
            "expected_assignment_revision": 1, "intent": payload()["intent"], "fulfillment_allowed": True})


@pytest.mark.parametrize("role", ["finance", "assistant"])
@pytest.mark.parametrize("assigned", [True, False])
async def test_bound_office_read_requires_current_organization_grant(api, session, office, exact, role, assigned):
    from sqlalchemy import delete

    from modules.accounting.models import AccessGrant

    office.deal_id = 1
    await session.commit()
    doc_id = office.id
    envelope, _ = await prepare_office(api, office)
    result = await api.post(f"/office/docs/{doc_id}/shipping-association-confirm",
                           json=confirmation(envelope, exact, assignment=1))
    assert result.status_code == 200, result.text
    session.add(User(username="scoped-reader", full_name="Scoped reader", role=role, status="active", deal_visibility="all"))
    session.add(AccessGrant(organization_id=2, subject="scoped-reader", role="reader"))
    await session.commit()
    if assigned:
        result = await api.post(f"/office/docs/{doc_id}/shipping-reviewer", json={
            "subject": "scoped-reader", "expected_revision": 1, "evidence": "Explicit reassignment"})
        assert result.status_code == 200, result.text
    api.headers.update({"X-User": "scoped-reader", "X-User-Roles": role})

    async def visible(expected):
        detail = await api.get(f"/office/docs/{doc_id}/shipping-source")
        assert detail.status_code == (200 if expected else 404), detail.text
        listing = await api.get("/office/docs")
        assert listing.status_code == 200, listing.text
        assert (doc_id in {row["id"] for row in listing.json()}) == expected

    await visible(False)
    session.add(AccessGrant(organization_id=1, subject="scoped-reader", role="reader"))
    await session.commit()
    await visible(True)
    await session.execute(delete(AccessGrant).where(AccessGrant.organization_id == 1,
                                                   AccessGrant.subject == "scoped-reader"))
    await session.commit()
    await visible(False)
