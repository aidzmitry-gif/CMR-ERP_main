# ruff: noqa: F811 -- imported pytest fixtures are injected by parameter name
"""Office read recovery and exact target attribution; isolated SQLite, not PG locking proof."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, select, update

from core.domain.models import OutboxEvent, User
from core.runtime.contract import Role
from modules.logistics.models import (
    CarrierRfq,
    Shipment,
    ShipmentIntake,
    ShipmentInvoiceBinding,
    ShippingExecution,
)
from modules.office import shipping_producer as office_api
from modules.office.models import OfficeDoc
from modules.office.shipping_associations import (
    OfficeInvoiceAssociation,
    ShippingRequest,
    ShippingReviewAssignment,
)
from tests.test_logistics_invoice_binding import exact  # noqa: F401
from tests.test_office_shipping_associations import (  # noqa: F401
    office,
    prepare_office,
    replay_setup,
)


async def read_context(api, doc_id):
    return await api.get(f"/office/docs/{doc_id}/shipping-source")


async def source_intake(session, envelope):
    source = envelope["payload"]["source"]
    return await session.scalar(select(ShipmentIntake).where(
        ShipmentIntake.source_kind == source["kind"], ShipmentIntake.source_key == source["key"],
        ShipmentIntake.source_revision == source["revision"]))


async def award_fixture(session, intake, exact):
    """Stored rows matching existing rfq-award route; no external carrier action."""
    rfq = await session.get(CarrierRfq, intake.rfq_id)
    shipment = Shipment(number="SYNTHETIC-AWARD", customer="Synthetic", status="assigned", carrier="Synthetic carrier")
    session.add(shipment)
    await session.flush()
    session.add(ShipmentInvoiceBinding(shipment_id=shipment.id, organization_id=exact["organization_id"],
        deal_id=1, document_id=exact["document_id"], document_version=exact["expected_version"],
        content_sha256=exact["expected_content_sha256"], source_key=f"rfq-award:{rfq.id}",
        request_digest="0" * 64, actor="ship-tester"))
    rfq.shipment_id, rfq.status = shipment.id, "contracted"
    await session.commit()
    return shipment


async def test_workspace_recovers_persisted_request_without_any_write(api, session, office):
    first = await read_context(api, office.id)
    assert first.status_code == 200, first.text
    assert first.json()["request"] is None and first.json()["logistics"]["state"] == "not_prepared"
    envelope, command = await prepare_office(api, office)
    before = list(await session.scalars(select(OutboxEvent.id)))
    writes = []
    engine = session.get_bind()

    def statement(_conn, _cursor, sql, _params, _context, _many):
        if sql.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "REPLACE"}:
            writes.append(sql)

    def mutation(*_args):
        writes.append("flush or commit")

    event.listen(engine, "before_cursor_execute", statement)
    event.listen(session.sync_session, "before_flush", mutation)
    event.listen(session.sync_session, "before_commit", mutation)
    try:
        result = await read_context(api, office.id)
    finally:
        event.remove(engine, "before_cursor_execute", statement)
        event.remove(session.sync_session, "before_flush", mutation)
        event.remove(session.sync_session, "before_commit", mutation)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["principal"] == "ship-tester" and data["is_current_reviewer"] is True
    assert data["request"]["request_key"] == command["request_key"]
    assert {key: data["request"][key] for key in envelope} == envelope
    assert "assignment_revision" not in data["request"]  # Prepare did not persist that guard.
    assert data["logistics"]["state"] == "not_received" and data["logistics"]["target"] is None
    assert data["source_matches_request"] is True and data["association"] is None
    assert writes == [] and list(await session.scalars(select(OutboxEvent.id))) == before


async def test_workspace_keeps_historical_source_separate_from_current_document(api, session, office, exact):
    _, doc_id, envelope, _ = await replay_setup(api, session, office, exact)
    await session.execute(update(OfficeDoc).where(OfficeDoc.id == doc_id).values(weight="800"))
    await session.commit()
    response = await read_context(api, doc_id)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["source_matches_request"] is False
    assert data["source_snapshot"]["weight"] == "800"
    assert data["request"]["source_sha256"] == envelope["source_sha256"]
    assert data["request"]["source_snapshot"]["weight"] != "800"
    assert data["logistics"]["state"] == "source_changed" and data["logistics"]["shipment"] is None


@pytest.mark.parametrize("mode", ["spot", "contract"])
@pytest.mark.parametrize("state", ["pending", "withdrawn", "resolved"])
async def test_workspace_reports_only_its_exact_intake(api, session, office, exact, mode, state):
    core, doc_id, envelope, _ = await replay_setup(api, session, office, exact, mode=mode,
                                                  state="resolved" if state == "resolved" else "pending")
    intake = await source_intake(session, envelope)
    if state == "withdrawn":
        intake.state, intake.pending_reason = "withdrawn", "Synthetic withdrawal"
        await session.commit()
    response = await read_context(api, doc_id)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["logistics"]["state"] == state and data["logistics"]["intake_id"] == intake.id
    assert data["association"]["request_key"] != data["request"]["request_key"]
    if state != "resolved":
        assert data["logistics"]["target"] is None and data["logistics"]["shipment"] is None
    else:
        assert data["logistics"]["target"]["kind"] == ("rfq" if mode == "contract" else "shipment")
        assert (data["logistics"]["shipment"] is None) == (mode == "contract")
    assert core is api._transport.app.state.core


async def test_financial_stage_does_not_invent_physical_delivery(api, session, office, exact):
    _, doc_id, envelope, _ = await replay_setup(api, session, office, exact)
    await session.execute(update(OfficeDoc).where(OfficeDoc.id == doc_id).values(stage="paid", docs_status="Оплачено"))
    await session.commit()
    data = (await read_context(api, doc_id)).json()
    assert data["document_stage"] == "paid" and data["logistics"]["shipment"]["status"] == "planned"
    intake = await source_intake(session, envelope)
    shipment = await session.get(Shipment, intake.shipment_id)
    shipment.status, shipment.tracking_status = "delivered", "Synthetic physical confirmation"
    await session.commit()
    confirmed = (await read_context(api, doc_id)).json()["logistics"]["shipment"]
    assert confirmed["status"] == "delivered" and confirmed["tracking_status"] == "Synthetic physical confirmation"


async def test_rfq_award_projects_the_exact_bound_shipment(api, session, office, exact):
    _, doc_id, envelope, _ = await replay_setup(api, session, office, exact, mode="contract")
    shipment = await award_fixture(session, await source_intake(session, envelope), exact)
    response = await read_context(api, doc_id)
    assert response.status_code == 200, response.text
    data = response.json()["logistics"]
    assert data["target"]["kind"] == "rfq" and data["shipment"]["id"] == shipment.id
    assert set(data["shipment"]) == {"id", "number", "status", "carrier_name", "tracking_status", "tracking_no", "eta"}


@pytest.mark.parametrize("tamper", ["request_payload", "request_snapshot", "association_confirmation",
    "binding_invoice", "binding_source", "execution_intent", "award_binding", "missing_association", "missing_binding",
    "execution_identity_pending"])
async def test_workspace_refuses_corrupt_or_foreign_lineage(api, session, office, exact, tamper):
    _, doc_id, envelope, _ = await replay_setup(api, session, office, exact,
        mode="contract" if tamper == "award_binding" else "spot",
        state="pending" if tamper == "execution_identity_pending" else "resolved")
    intake = await source_intake(session, envelope)
    request = await session.get(ShippingRequest, envelope["envelope_id"])
    assoc = await session.scalar(select(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.office_doc_id == doc_id))
    if tamper == "request_payload":
        forged = deepcopy(request.payload)
        forged["intent"]["cargo"] = "Changed synthetic cargo"
        await session.execute(update(ShippingRequest).where(ShippingRequest.id == request.id).values(payload=forged))
    elif tamper == "request_snapshot":
        await session.execute(update(ShippingRequest).where(ShippingRequest.id == request.id)
            .values(source_snapshot={**request.source_snapshot, "company": "Changed synthetic company"}))
    elif tamper == "association_confirmation":
        await session.execute(update(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.id == assoc.id)
            .values(confirmation_sha256="0" * 64))
    elif tamper == "execution_intent":
        execution = await session.get(ShippingExecution, assoc.execution_id)
        await session.execute(update(ShippingExecution).where(ShippingExecution.id == execution.id)
            .values(intent={**execution.intent, "cargo": "Different synthetic cargo"}))
    elif tamper == "execution_identity_pending":
        await session.execute(update(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.id == assoc.id)
            .values(execution_id="not-a-canonical-execution"))
    elif tamper == "award_binding":
        shipment = await award_fixture(session, intake, exact)
        await session.execute(update(ShipmentInvoiceBinding).where(ShipmentInvoiceBinding.shipment_id == shipment.id)
            .values(source_key="other-award"))
    elif tamper == "missing_association":
        await session.execute(delete(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.id == assoc.id))
    elif tamper == "missing_binding":
        await session.execute(delete(ShipmentInvoiceBinding).where(ShipmentInvoiceBinding.shipment_id == intake.shipment_id))
    else:
        changed = {"document_version": 2} if tamper == "binding_invoice" else {"source_key": "other-execution"}
        await session.execute(update(ShipmentInvoiceBinding).where(ShipmentInvoiceBinding.shipment_id == intake.shipment_id)
            .values(**changed))
    await session.commit()
    response = await read_context(api, doc_id)
    assert response.status_code == 409, response.text
    assert "SYNTHETIC-AWARD" not in response.text and "Changed synthetic" not in response.text


@pytest.mark.parametrize("state", ["pending", "withdrawn"])
async def test_unresolved_state_cannot_hide_a_target(api, session, office, exact, state):
    _, doc_id, envelope, _ = await replay_setup(api, session, office, exact, state="pending")
    intake = await source_intake(session, envelope)
    target = Shipment(customer="Unrelated synthetic shipment")
    session.add(target)
    await session.flush()
    intake.state, intake.shipment_id = state, target.id  # Valid FK, inconsistent source state.
    await session.commit()
    assert (await read_context(api, doc_id)).status_code == 409


@pytest.mark.parametrize("drift", ["source", "request", "association", "reviewer"])
async def test_read_never_adopts_context_bound_after_authorization(api, session, office, exact, monkeypatch, drift):
    if drift != "request":
        await prepare_office(api, office)
    original = office_api.authorize_doc
    fired = False

    async def changed(core, db, doc, user, permission, **kwargs):
        nonlocal fired
        allowed = await original(core, db, doc, user, permission, **kwargs)
        if not fired and permission == "office.doc.read":
            fired = True
            if drift == "source":
                await db.execute(update(OfficeDoc).where(OfficeDoc.id == doc.id).values(weight="900"))
            elif drift == "reviewer":
                db.add(ShippingReviewAssignment(office_doc_id=doc.id, revision=2, subject="", actor="ship-tester", evidence="Synthetic revocation"))
            elif drift == "request":
                # A concurrent accepted preparation; the GET itself must not adopt it.
                from core.services.auth import CurrentUser
                from modules.office.shipping_associations import source_hash
                from tests.test_shipping_payload import payload

                await office_api.OfficeShippingProducer(core).prepare(db, doc.id, office_api.RequestInput(
                    request_key="concurrent-request", expected_source_hash=source_hash(doc),
                    expected_assignment_revision=1, intent=payload()["intent"]), CurrentUser("ship-tester", ["director"]))
            else:
                saved = await db.scalar(select(ShippingRequest).where(ShippingRequest.office_doc_id == doc.id))
                # Foreign organization, installed by a different concurrent transaction.
                db.add(OfficeInvoiceAssociation(id=str(uuid4()), request_id=saved.id, office_doc_id=doc.id,
                    organization_id=2, exact_invoice={**exact, "organization_id": 2}, execution_id=str(uuid4()),
                    intent_digest="0" * 64, assignment_revision=1, request_key="foreign-confirmation",
                    confirmation_sha256="0" * 64, evidence_refs={}, actor="another-actor"))
            await db.commit()
        return allowed

    monkeypatch.setattr(office_api, "authorize_doc", changed)
    response = await read_context(api, office.id)
    assert fired and response.status_code == (404 if drift == "association" else 409), response.text
    assert "foreign-confirmation" not in response.text and "another-actor" not in response.text


async def test_missing_logistics_adapter_is_unknown_not_an_empty_success(api, session, office):
    await prepare_office(api, office)
    api._transport.app.state.core.services.logistics = None
    response = await read_context(api, office.id)
    assert response.status_code == 200, response.text
    assert response.json()["request"] is not None and response.json()["logistics"]["state"] == "unavailable"


async def test_reviewer_revocation_preserves_history_without_permission_to_act(api, session, office, exact):
    _, doc_id, _, _ = await replay_setup(api, session, office, exact)
    session.add(ShippingReviewAssignment(office_doc_id=doc_id, revision=2, subject="", actor="ship-tester", evidence="Synthetic revocation"))
    await session.commit()
    response = await read_context(api, doc_id)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["association"]["current_review_matches"] is False and data["is_current_reviewer"] is False
    assert data["capabilities"] == {"can_request": False, "can_associate": False}
    assert data["logistics"]["state"] == "resolved"


async def test_read_scope_never_becomes_write_authority(api, session, office, monkeypatch):
    core = api._transport.app.state.core
    # Use an existing module-admitted role; narrow only this isolated core's RBAC.
    monkeypatch.setattr(core, "roles", [role for role in core.roles if role.name != "assistant"]
                        + [Role("assistant", permissions=("office.doc.read",))])
    await session.execute(update(User).where(User.username == "ship-tester").values(role="assistant"))
    await session.commit()
    api.headers.update({"X-User-Roles": "assistant"})
    response = await read_context(api, office.id)
    assert response.status_code == 200, response.text
    assert response.json()["is_current_reviewer"] is True
    assert response.json()["capabilities"] == {"can_request": False, "can_associate": False}
