"""New invoice/Office warehouse bridge cases; synthetic SQLite, not PG locks."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, update

from core.domain.models import OutboxEvent, User
from core.runtime.contract import Role
from core.services.eventbus import EventContext
from modules.accounting.models import AccessGrant, Organization
from modules.office import warehouse_projection
from modules.office.models import OfficeDoc
from modules.office.shipping_associations import (
    OfficeInvoiceAssociation,
    ShippingReviewAssignment,
    source_hash,
)
from modules.sales.reservation_source import SalesReservationSource
from modules.wms import (
    invoice_remainder,  # noqa: F401 -- register existing release tables before fixture create_all
)
from modules.wms.invoice_shipments import PhysicalShipmentAct
from modules.wms.models import ReservationVersion, StockMovement, WarehouseDirectory
from modules.wms.reservation_events import apply
from tests.test_invoice_issuance import command, create, seed
from tests.test_sales_shipping_associations import confirmation
from tests.test_shipping_payload import payload


async def prepared(api, session, *, two_warehouses=False, wms_enabled=True, bound=True):
    ids, base = await seed(api, session, qty="5", wms_enabled=wms_enabled)
    if two_warehouses:
        session.add(WarehouseDirectory(organization_id=ids["org"], name="W2", title="Second synthetic warehouse",
            created_by="issuer", wms_enabled=wms_enabled, prohibit_negative_stock=True))
        session.add(StockMovement(organization_id=ids["org"], sku_code=ids["code"], warehouse="W2",
            kind="in", qty=10, reason="receipt"))
        await session.commit()
    cmd, _ = await command(api, ids, base)
    if two_warehouses:
        cmd["allocations"] = [{"line_no": 1, "warehouse": "W", "qty": "2.00"},
                              {"line_no": 1, "warehouse": "W2", "qty": "3.00"}]
    issued = await create(api, ids, cmd)
    assert issued.status_code == 201, issued.text
    document_id = issued.json()["document"]["id"]
    await api._transport.app.state.core.services.accounting.lock_event_organization(session, ids["org"])
    facts = await SalesReservationSource().invoice_reservation(session, document_id)
    quantities = [(ids["code"], row["warehouse"], Decimal(row["qty"])) for row in cmd["allocations"]]
    await apply(session, document_id, quantities, organization_id=ids["org"], release=False)
    if await session.scalar(select(User).where(User.username == "issuer")) is None:
        session.add(User(username="issuer", full_name="Synthetic issuer", role="director", status="active"))
    await session.commit()
    doc = await bind_office(api, session, ids["org"], facts, "FIRST", associate=bound)
    return ids["org"], facts, doc


async def bind_office(api, session, org, facts, suffix, *, associate=True):
    doc = OfficeDoc(number="OFF-WAREHOUSE-" + suffix, company="Exact buyer", title="Five issued goods",
        amount=600, deal_id=facts["deal_id"], stage="ready")
    session.add(doc)
    await session.commit()
    response = await api.post(f"/office/docs/{doc.id}/shipping-reviewer", json={
        "subject": "issuer", "expected_revision": 0, "evidence": "Synthetic exact invoice reviewer"})
    assert response.status_code == 200, response.text
    response = await api.post(f"/office/docs/{doc.id}/carrier-request", json={
        "request_key": "warehouse-" + suffix, "expected_source_hash": source_hash(doc),
        "expected_assignment_revision": 1, "intent": payload()["intent"]})
    assert response.status_code == 200, response.text
    if not associate:
        return doc
    exact = {"organization_id": org, "document_id": facts["document_id"],
        "expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    response = await api.post(f"/office/docs/{doc.id}/shipping-association-confirm",
        json=confirmation(response.json(), exact, assignment=1, key="warehouse-bind-" + suffix))
    assert response.status_code == 200, response.text
    return doc


def url(doc):
    return f"/office/docs/{doc.id}/warehouse-progress"


async def ship(api, org, facts, lines, *, document_mode=False):
    endpoint = f"/wms/organizations/{org}/invoices/{facts['document_id']}/" + (
        "document-shipments" if document_mode else "physical-shipments")
    identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    preview = await api.post(endpoint + "/preview", json=identity)
    assert preview.status_code == 200, preview.text
    basis = preview.json()
    response = await api.post(endpoint, json={**identity, "source_key": str(uuid4()),
        "expected_reservation_digest": basis["reservation_digest"], "expected_remaining_digest": basis["remaining_digest"],
        "expected_physical_digest": basis["physical_digest"], "operation_date": date.today().isoformat(),
        "evidence": "Synthetic actual issue for new projection tests", "lines": lines})
    assert response.status_code == 201, response.text
    return response.json()


async def event_for(session, act):
    row = await session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "wms.invoice.physical_shipped")
        .order_by(OutboxEvent.id.desc()))
    assert row.payload["act_id"] == act["act_id"]
    return row.payload


async def source_state(session):
    result = {}
    for model in (StockMovement, ReservationVersion, PhysicalShipmentAct, OutboxEvent, OfficeInvoiceAssociation):
        result[model.__name__] = [{c.name: getattr(row, c.name) for c in model.__table__.columns}
            for row in await session.scalars(select(model).order_by(list(model.__table__.primary_key.columns)[0]))]
    return result


async def test_actual_two_warehouse_partial_full_and_stale_event_project_all_offices(api, session):
    org, facts, doc = await prepared(api, session, two_warehouses=True)
    second = await bind_office(api, session, org, facts, "SECOND")
    first_act = await ship(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "2.00"}])
    first_event = await event_for(session, first_act)
    core = api._transport.app.state.core
    ctx = EventContext(session, core.services)
    before = await source_state(session)
    await core.event_bus.dispatch("wms.invoice.physical_shipped", first_event, ctx)
    await session.commit()
    assert all(row.stage == "ready" and "частично" in row.docs_status and "остаток" in row.next_step for row in (doc, second))
    assert await source_state(session) == before
    response = await api.get(url(doc))
    assert response.status_code == 200, response.text
    observed = response.json()["progress"]
    assert observed["state"] == "partial" and observed["coverage_complete"] is False
    assert [(row["warehouse"], row["expected_qty"], row["shipped_qty"]) for row in observed["lines"]] == [
        (row["warehouse"], "2.00" if row["warehouse"] == "W" else "3.00", "2.00" if row["warehouse"] == "W" else "0.00")
        for row in observed["lines"]]
    final_act = await ship(api, org, facts, [{"line_no": 1, "warehouse": "W2", "qty": "3.00"}])
    before = await source_state(session)
    await core.event_bus.dispatch("wms.invoice.physical_shipped", first_event, ctx)  # Older event, current complete facts.
    await session.commit()
    assert all(row.stage == "shipped" and row.wms_ref == "physical-shipment:" + final_act["source_key"] for row in (doc, second))
    assert all(row.op_date is None for row in (doc, second)) and await source_state(session) == before
    response = await api.get(url(doc))
    assert response.status_code == 200, response.text
    final = response.json()["progress"]
    assert final["state"] == "complete" and len(final["acts"]) == 2
    assert {row["warehouse"] for row in final["lines"]} == {"W", "W2"}


async def test_partial_issue_and_actual_remainder_release_never_become_complete(api, session):
    org, facts, doc = await prepared(api, session)
    await ship(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "1.00"}])
    prefix = f"/wms/organizations/{org}/invoices/{facts['document_id']}/remainder-release"
    identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    preview = await api.post(prefix + "/preview", json=identity)
    assert preview.status_code == 200, preview.text
    receipt = await api.post(prefix, json={**identity, "source_key": str(uuid4()),
        "expected_basis_digest": preview.json()["basis_digest"], "evidence": "Synthetic authorized remainder release"})
    assert receipt.status_code == 201, receipt.text
    event_row = await session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "wms.invoice.remainder_released"))
    core = api._transport.app.state.core
    await core.event_bus.dispatch("wms.invoice.remainder_released", event_row.payload, EventContext(session, core.services))
    await session.commit()
    response = await api.get(url(doc))
    assert response.status_code == 200, response.text
    progress = response.json()["progress"]
    assert progress["state"] == "partial" and doc.stage == "ready" and "резерва снят" in doc.next_step
    assert [(row["expected_qty"], row["shipped_qty"], row["reserved_qty"], row["released_qty"]) for row in progress["lines"]] == [
        ("5.00", "1.00", "0.00", "4.00")]
    assert progress["releases"] == [{"release_id": receipt.json()["release_id"], "digest": receipt.json()["digest"]}]


@pytest.mark.parametrize("stage", ["docs", "await_pay", "paid", "draft"])
async def test_complete_issue_never_regresses_later_or_draft_stage_or_actual_date(api, session, stage):
    org, facts, doc = await prepared(api, session)
    act = await ship(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "5.00"}])
    doc.stage, doc.op_date, doc.docs_status, doc.next_step = stage, "2026-09-11", "Keep financial status", "Keep workflow"
    await session.commit()
    before = await source_state(session)
    core = api._transport.app.state.core
    await warehouse_projection.on_physical_shipped(await event_for(session, act), EventContext(session, core.services))
    await session.commit()
    assert (doc.stage, doc.op_date, doc.docs_status, doc.next_step) == (stage, "2026-09-11", "Keep financial status", "Keep workflow")
    assert doc.wms_ref == "physical-shipment:" + act["source_key"] and await source_state(session) == before


async def test_scoped_get_has_no_dml_and_manual_reconcile_changes_only_url_document(api, session):
    org, facts, doc = await prepared(api, session)
    endpoint = url(doc)
    second = await bind_office(api, session, org, facts, "SECOND")
    await ship(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "5.00"}])
    writes = []

    def observed(_conn, _cursor, sql, _parameters, _context, _many):
        if sql.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}:
            writes.append(sql)

    event.listen(session.bind.sync_engine, "before_cursor_execute", observed)
    try:
        response = await api.get(url(doc))
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", observed)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store" and response.json()["progress"]["state"] == "complete"
    assert writes == [] and doc.stage == second.stage == "ready" and not doc.wms_ref and not second.wms_ref
    before = await source_state(session)
    response = await api.post(url(doc) + "/reconcile")
    assert response.status_code == 200, response.text
    assert response.json()["document_stage"] == "shipped" and second.stage == "ready" and second.wms_ref == ""
    assert await source_state(session) == before
    api._transport.app.state.core.declare_role(Role("warehouse-test-reader", permissions=("office.doc.read",)))
    assert (await api.post(endpoint + "/reconcile", headers={"X-User-Roles": "warehouse-test-reader"})).status_code == 403
    session.add_all([Organization(id=999, name="Foreign synthetic book", unp="999999999"),
        User(username="foreign", full_name="Synthetic foreign reader", role="director", status="active"),
        AccessGrant(organization_id=999, subject="foreign", role="reader")])
    await session.commit()
    assert (await api.get(endpoint, headers={"X-User": "foreign"})).status_code == 404


async def test_reviewer_revision_change_during_warehouse_read_fails_closed(api, session, monkeypatch):
    _, _, doc = await prepared(api, session)
    service = api._transport.app.state.core.services.wms_reservations
    original = service.invoice_shipping_progress

    async def revoked(*args, **kwargs):
        result = await original(*args, **kwargs)
        await session.execute(ShippingReviewAssignment.__table__.insert().values(office_doc_id=doc.id,
            revision=2, subject="", evidence="Synthetic concurrent revocation", actor="issuer"))
        return result

    monkeypatch.setattr(service, "invoice_shipping_progress", revoked)
    response = await api.get(url(doc))
    assert response.status_code == 409, response.text
    await session.refresh(doc)
    assert doc.stage == "ready" and doc.wms_ref == ""


@pytest.mark.parametrize("tamper", ["anchor", "reference", "confirmation", "source", "organization"])
async def test_event_rejects_foreign_anchor_reference_and_corrupt_office_lineage(api, session, tamper, monkeypatch):
    org, facts, doc = await prepared(api, session)
    act = await ship(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "1.00"}])
    anchor = dict(await event_for(session, act))
    if tamper == "anchor":
        anchor["digest"] = "0" * 64
    elif tamper == "organization":
        anchor["organization_id"] = org + 999

        async def forbidden(*_args, **_kwargs):
            raise AssertionError("Claimed foreign organization must not be locked")

        monkeypatch.setattr(api._transport.app.state.core.services.accounting, "lock_event_organization", forbidden)
    elif tamper == "reference":
        doc.wms_ref = "physical-shipment:" + str(uuid4())
    elif tamper == "confirmation":
        await session.execute(update(OfficeInvoiceAssociation).values(confirmation_sha256="0" * 64))
    else:
        doc.weight = "Changed after confirmation"
    await session.commit()
    before = (doc.stage, doc.wms_ref, doc.docs_status, doc.next_step)
    core = api._transport.app.state.core
    with pytest.raises(HTTPException) as error:
        await warehouse_projection.on_physical_shipped(anchor, EventContext(session, core.services))
    assert error.value.status_code == 409 and (doc.stage, doc.wms_ref, doc.docs_status, doc.next_step) == before
    assert not session.dirty


@pytest.mark.parametrize("tamper", ["act_digest", "movement_organization"])
async def test_corrupt_warehouse_proof_is_an_error_not_empty_progress(api, session, tamper):
    org, facts, doc = await prepared(api, session)
    act = await ship(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "1.00"}])
    if tamper == "act_digest":
        await session.execute(update(PhysicalShipmentAct).where(PhysicalShipmentAct.id == act["act_id"]).values(digest="0" * 64))
    else:
        session.add(Organization(id=999, name="Foreign movement book", unp="999999999"))
        await session.flush()
        await session.execute(update(StockMovement).where(StockMovement.doc_ref == f"physical-act:{act['act_id']}")
            .values(organization_id=999))
    await session.commit()
    response = await api.get(url(doc))
    assert response.status_code == 409 and "progress" not in response.json()
    await session.refresh(doc)
    assert doc.stage == "ready" and doc.wms_ref == ""


async def test_unassociated_document_is_explicit_and_never_reads_warehouse(api, session, monkeypatch):
    api.headers["X-User"] = "test"
    session.add(User(username="test", full_name="Synthetic", role="director", status="active"))
    doc = OfficeDoc(number="UNASSOCIATED", stage="ready")
    session.add(doc)
    await session.commit()

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Unassociated source must not read warehouse")

    monkeypatch.setattr(api._transport.app.state.core.services.wms_reservations, "invoice_shipping_progress", forbidden)
    response = await api.get(url(doc))
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "unassociated" and response.json()["progress"] is None
    assert (await api.post(url(doc) + "/reconcile")).status_code == 409
    await session.refresh(doc)
    assert doc.stage == "ready"


async def test_verified_zero_recorded_acts_does_not_advance_office_or_claim_external_absence(api, session):
    _, _, doc = await prepared(api, session)
    response = await api.get(url(doc))
    assert response.status_code == 200, response.text
    progress = response.json()["progress"]
    assert progress["state"] == "none_recorded" and progress["coverage_complete"] is False and progress["acts"] == []
    assert progress["lines"][0]["reserved_qty"] == "5.00"
    assert (await api.post(url(doc) + "/reconcile")).status_code == 200
    assert doc.stage == "ready" and doc.wms_ref == ""


async def test_document_mode_act_keeps_its_execution_mode_without_claiming_wms_device_proof(api, session):
    org, facts, doc = await prepared(api, session, wms_enabled=False)
    await ship(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": "5.00"}], document_mode=True)
    response = await api.post(url(doc) + "/reconcile")
    assert response.status_code == 200, response.text
    progress = response.json()["progress"]
    assert progress["state"] == "complete" and progress["coverage_complete"] is False
    assert [act["execution_mode"] for act in progress["acts"]] == ["document"]
    assert (await session.scalar(select(WarehouseDirectory))).wms_enabled is False


async def test_binding_committed_during_first_authorization_is_not_adopted(api, session, monkeypatch):
    org, facts, doc = await prepared(api, session, bound=False)
    endpoint = url(doc)
    recovered = await api.get(f"/office/docs/{doc.id}/shipping-source")
    assert recovered.status_code == 200, recovered.text
    envelope = recovered.json()["request"]
    exact = {"organization_id": org, "document_id": facts["document_id"],
        "expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    body = confirmation(envelope, exact, assignment=1, key="warehouse-late-bind")
    confirm_url = f"/office/docs/{doc.id}/shipping-association-confirm"
    original = warehouse_projection.authorize_doc
    calls = 0

    async def bind_during_auth(*args, **kwargs):
        nonlocal calls
        result = await original(*args, **kwargs)
        calls += 1
        if calls == 1:
            # Real association command during a yielded auth boundary, not PG concurrency proof.
            committed = await api.post(confirm_url, json=body)
            assert committed.status_code == 200, committed.text
        return result

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Late binding must stop before warehouse disclosure")

    monkeypatch.setattr(warehouse_projection, "authorize_doc", bind_during_auth)
    monkeypatch.setattr(api._transport.app.state.core.services.wms_reservations, "invoice_shipping_progress", forbidden)
    response = await api.get(endpoint)
    assert response.status_code == 409, response.text
    await session.refresh(doc)
    assert doc.wms_ref == "" and doc.stage == "ready"


async def test_deal_scope_is_rechecked_after_warehouse_wait_before_disclosure(api, session, monkeypatch):
    _, _, doc = await prepared(api, session)
    endpoint = url(doc)
    source = api._transport.app.state.core.services.sales_source
    original = source.authorize_shipping_deal
    calls = 0

    async def scope_revoked(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HTTPException(404, "Synthetic deal scope revoked while waiting")
        return await original(*args, **kwargs)

    monkeypatch.setattr(source, "authorize_shipping_deal", scope_revoked)
    response = await api.get(endpoint)
    assert response.status_code == 404 and calls == 2, response.text
    await session.refresh(doc)
    assert doc.stage == "ready" and doc.wms_ref == ""


async def test_read_source_matches_full_default_facts_without_dml_or_autoflush(api, session):
    org, facts, _ = await prepared(api, session)
    core = api._transport.app.state.core
    await core.services.accounting.lock_event_organization(session, org)
    exact = {"organization_id": org, "document_id": facts["document_id"],
        "expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    writes = []

    def observed(_conn, _cursor, sql, _parameters, _context, _many):
        if sql.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}:
            writes.append(sql)

    event.listen(session.bind.sync_engine, "before_cursor_execute", observed)
    pending = None
    try:
        ordinary = deepcopy(await core.services.sales_source.invoice_shipping_source(session, **exact, operation="historical_claim"))
        assert len(writes) == 1 and "UPDATE" in writes[0] and "deal" in writes[0]
        writes.clear()
        pending = OfficeDoc(number="PENDING-NOT-FLUSHED", stage="draft")
        session.add(pending)
        read = await core.services.sales_source.invoice_shipping_read_source(session, **exact)
        assert read == ordinary and read["fulfillment_allowed"] is False
        assert writes == [] and pending in session.new
        session.expunge(pending)
        pending = None
        for operation in ("fulfill", "cancellation"):
            with pytest.raises(ValueError):
                await core.services.sales_source.invoice_shipping_source(session, **exact,
                    operation=operation, _read_only=True)
        assert writes == []
    finally:
        if pending is not None and pending in session.new:
            session.expunge(pending)
        event.remove(session.bind.sync_engine, "before_cursor_execute", observed)
