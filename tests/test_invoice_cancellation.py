import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import User
from core.services.logistics import snapshot_hash
from modules.accounting.models import Policy
from modules.logistics.models import CarrierBid, CarrierRfqInvite
from modules.office import shipping_associations as office_shipping  # noqa: F401
from modules.sales import shipping_associations as sales_shipping  # noqa: F401
from modules.sales.invoice_cancellation import SalesFulfillmentReview
from modules.sales.models import DealDocument
from modules.sales.reservation_source import SalesReservationSource
from modules.wms.invoice_shipments import PhysicalShipmentAct
from modules.wms.models import ReservationVersion, StockMovement
from tests.accounting.test_invoice_settlements import bank
from tests.accounting.test_postgres import pg_factory as pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import (
    issuance_pg as issuance_pg,  # noqa: F401
)
from tests.test_invoice_issuance import command, create, erp_money_flow, seed
from tests.test_invoice_physical_shipments import endpoint, request


async def prepared(api, session):
    ids, base = await seed(api, session)
    data, _ = await command(api, ids, base)
    response = await create(api, ids, data)
    assert response.status_code == 201, response.text
    document_id = response.json()["document"]["id"]
    assert document_id == 1
    facts = await SalesReservationSource().invoice_reservation(session, document_id)
    await session.commit()
    return ids["org"], facts


async def test_cancellation_preview_combines_exact_evidence_without_business_changes(api, session):
    org, facts = await prepared(api, session)
    path = f"/sales/organizations/{org}/invoices/1/cancellation/preview"
    identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    before = [await session.scalar(select(func.count()).select_from(model))
              for model in (StockMovement, ReservationVersion, PhysicalShipmentAct)]
    doc = await session.get(DealDocument, 1)
    original = (doc.status, doc.reserve_status, doc.original_html, doc.content_sha256)
    response = await api.post(path, json=identity)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["cancellation_authorized"] is False
    assert set(result["sections"]) == {"wms_issue", "wms_pick", "logistics_shipment",
                                       "accounting_issue", "legacy_fulfillment"}
    assert result["sections"]["wms_issue"]["facts"]["observed_state"] == "no_shipment"
    assert result["sections"]["legacy_fulfillment"]["facts"]["coverage_complete"] is False
    assert result["basis_digest"] == snapshot_hash({k: v for k, v in result.items() if k != "basis_digest"})
    assert (await api.post(path, json=identity)).json() == result
    assert before == [await session.scalar(select(func.count()).select_from(model))
                      for model in (StockMovement, ReservationVersion, PhysicalShipmentAct)]
    await session.refresh(doc)
    assert (doc.status, doc.reserve_status, doc.original_html, doc.content_sha256) == original
    wrong = deepcopy(identity)
    wrong["expected_version"] += 1
    assert (await api.post(path, json=wrong)).status_code == 409
    assert (await api.post(path.replace(f"/{org}/", f"/{org + 100}/"), json=identity)).status_code in (403, 404)


async def test_cancellation_preview_retains_partial_physical_shipment_as_blocker(api, session):
    org, facts = await prepared(api, session)
    body = await request(api, org, facts)
    issued = await api.post(endpoint(org), json=body)
    assert issued.status_code == 201, issued.text
    response = await api.post(f"/sales/organizations/{org}/invoices/1/cancellation/preview", json={
        "expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert "physical_shipment_requires_return_workflow" in result["observed_blockers"]
    assert result["sections"]["wms_issue"]["facts"]["acts"][0]["act_id"] == issued.json()["act_id"]


async def test_cancellation_preview_rechecks_refund_and_later_receipt(api, session):
    await erp_money_flow(api, session)
    policy = await session.scalar(select(Policy))
    doc = await session.get(DealDocument, 1)
    prefix = f"/sales/organizations/{policy.organization_id}/invoices/1"
    identity = {"expected_version": doc.version, "expected_content_sha256": doc.content_sha256}
    refunded = await api.post(prefix + "/cancellation/preview", json=identity)
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["money"]["state"] == "fully_refunded"
    assert refunded.json()["cancellation_authorized"] is False
    entry = await bank(api, (policy.organization_id, policy.id), 1, "later-in", amount="20.00")
    allocated = await api.post(prefix + "/settlements", json={"bank_entry_id": entry,
        "source_key": "later-in", "amount": "20.00", "evidence": "Synthetic later payment"})
    assert allocated.status_code == 201, allocated.text
    held = await api.post(prefix + "/cancellation/preview", json=identity)
    assert held.status_code == 200, held.text
    assert held.json()["money"]["state"] == "funds_held"
    assert "funds_not_fully_refunded" in held.json()["observed_blockers"]
    assert refunded.json()["basis_digest"] != held.json()["basis_digest"]


async def review_request(api, org, facts):
    prefix = f"/sales/organizations/{org}/invoices/1"
    money = (await api.get(prefix + "/money-reconciliation")).json()
    result = await api.post(prefix + "/money-reconciliation", json={
        "source_key": str(uuid4()), "expected_basis_digest": money["basis_digest"],
        "history_from": money["required_history_from"], "history_through": money["required_history_through"],
        "evidence": "Synthetic complete bank and cash reconciliation",
        "source_references": ["Synthetic bank archive", "Synthetic legacy cash archive"],
        "all_money_sources_checked": True})
    assert result.status_code == 201, result.text
    identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    preview = await api.post(prefix + "/cancellation/preview", json=identity)
    assert preview.status_code == 200, preview.text
    basis = preview.json()
    bounds = basis["sections"]["legacy_fulfillment"]["facts"]
    return prefix + "/fulfillment-review", {
        **identity, "request_key": str(uuid4()), "expected_basis_digest": basis["basis_digest"],
        "money_reconciliation_id": result.json()["id"], "evidence": "Synthetic complete fulfillment archive",
        "external_sources": [{"system": "Synthetic legacy warehouse", "reference": "Archive invoice 1",
            "history_from": bounds["required_history_from"], "history_through": bounds["required_history_through"],
            "confirmed_no_fulfillment": True}], "all_fulfillment_sources_identified": True}


async def test_fulfillment_review_replay_conflict_and_immutable_evidence(api, session):
    org, facts = await prepared(api, session)
    path, data = await review_request(api, org, facts)
    response = await api.post(path, json=data)
    assert response.status_code == 201, response.text
    assert response.json()["cancellation_authorized"] is False
    assert (await api.post(path, json=data)).json() == response.json()
    conflict = {**data, "evidence": "Different archive"}
    assert (await api.post(path, json=conflict)).status_code == 409
    assert (await api.post(path.replace(f"/organizations/{org}/", f"/organizations/{org+100}/"), json=data)).status_code in (403, 404)
    assert await session.scalar(select(func.count()).select_from(SalesFulfillmentReview)) == 1
    row = await session.get(SalesFulfillmentReview, response.json()["review_id"])
    assert len(row.snapshot["sections"]) == 5
    doc = await session.get(DealDocument, 1)
    assert doc.status != "cancelled"
    row.actor = "tampered"
    with pytest.raises(ValueError, match="cannot be changed or deleted"):
        await session.flush()
    await session.rollback()


@pytest.mark.parametrize("change,status", [
    ({"expected_basis_digest": "0" * 64}, 409),
    ({"money_reconciliation_id": 999999}, 409),
    ({"all_fulfillment_sources_identified": False}, 422),
    ({"evidence": "   "}, 422),
])
async def test_fulfillment_review_rejects_unconfirmed_or_stale_evidence(api, session, change, status):
    org, facts = await prepared(api, session)
    path, data = await review_request(api, org, facts)
    response = await api.post(path, json={**data, **change})
    assert response.status_code == status, response.text
    assert await session.scalar(select(func.count()).select_from(SalesFulfillmentReview)) == 0


async def test_fulfillment_review_requires_each_named_source_coverage(api, session):
    org, facts = await prepared(api, session)
    path, data = await review_request(api, org, facts)
    data["external_sources"][0]["history_through"] = "2000-01-01"
    response = await api.post(path, json=data)
    assert response.status_code == 409, response.text
    assert await session.scalar(select(func.count()).select_from(SalesFulfillmentReview)) == 0


async def test_fulfillment_review_historical_replay_does_not_authorize_after_shipment(api, session):
    org, facts = await prepared(api, session)
    path, data = await review_request(api, org, facts)
    confirmed = await api.post(path, json=data)
    assert confirmed.status_code == 201, confirmed.text
    shipment = await api.post(endpoint(org), json=await request(api, org, facts))
    assert shipment.status_code == 201, shipment.text
    replay = await api.post(path, json=data)
    assert replay.json() == confirmed.json()
    assert replay.json()["cancellation_authorized"] is False
    stale = await api.post(path, json={**data, "request_key": str(uuid4())})
    assert stale.status_code == 409, stale.text
    assert await session.scalar(select(func.count()).select_from(SalesFulfillmentReview)) == 1


async def test_fulfillment_review_accepts_verified_fully_refunded_bank_history(api, session):
    await erp_money_flow(api, session)
    policy = await session.scalar(select(Policy))
    facts = await SalesReservationSource().invoice_reservation(session, 1)
    await session.commit()
    path, data = await review_request(api, policy.organization_id, facts)
    result = await api.post(path, json=data)
    assert result.status_code == 201, result.text
    row = await session.get(SalesFulfillmentReview, result.json()["review_id"])
    assert row.snapshot["money"]["state"] == "fully_refunded"
    assert result.json()["cancellation_authorized"] is False


@pytest.mark.integration
async def test_pg_fulfillment_review_concurrent_replay_and_database_guards(issuance_pg):
    api, factory = issuance_pg
    async with factory() as session:
        connection = await session.connection()
        for model in (CarrierBid, CarrierRfqInvite, User):
            await connection.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        await session.commit()
        org, facts = await prepared(api, session)
    path, data = await review_request(api, org, facts)
    responses = await asyncio.gather(api.post(path, json=data), api.post(path, json=data))
    assert [r.status_code for r in responses] == [201, 201], [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(SalesFulfillmentReview)) == 1
    for sql in ("UPDATE sales.invoice_fulfillment_review SET actor='changed'",
                "DELETE FROM sales.invoice_fulfillment_review", "TRUNCATE sales.invoice_fulfillment_review CASCADE"):
        async with factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(sql))
            await session.rollback()


async def collected_verifier(api, session):
    from core.services.auth import CurrentUser
    from modules.sales.invoice_cancellation import (
        CancellationIdentity,
        collect_cancellation_basis,
        prepare_fulfillment_verifier,
    )
    org, facts = await prepared(api, session)
    path, data = await review_request(api, org, facts)
    saved = await api.post(path, json=data)
    assert saved.status_code == 201, saved.text
    services = api._transport.app.state.core.services
    user = CurrentUser("issuer", ["director"])
    await services.accounting.source_owner_authority(session, org, user)
    basis, current = await collect_cancellation_basis(session, services, org, 1,
        CancellationIdentity(expected_version=facts["version"], expected_content_sha256=facts["content_sha256"]), user)
    verifier = await prepare_fulfillment_verifier(session, services, org, basis, current,
        saved.json()["review_id"], saved.json()["review_digest"])
    return org, services, basis, current, verifier


async def test_saved_fulfillment_verifier_releases_exact_reserve_and_rollback_restores_it(api, session):
    org, services, basis, current, verifier = await collected_verifier(api, session)
    proof = verifier.proof
    before = await session.scalar(select(func.count()).select_from(StockMovement))
    release = await services.wms_reservations.release_invoice(session, org, current["source"], {
        "source_key": str(uuid4()), "expected_reservation_digest": basis["reservation_digest"],
        "expected_remaining_digest": basis["remaining_digest"], "fulfillment_review_id": proof.review_id,
        "fulfillment_review_digest": proof.review_digest, "evidence": "Synthetic cancelled invoice package",
    }, "issuer", verifier)
    assert release["snapshot"]["lines"]
    assert all(line["after_qty"] == "0.00" for line in release["snapshot"]["lines"])
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == before
    assert {r["scope"] for r in release["snapshot"]["fulfillment"]["references"]} == set(basis["sections"])
    await session.rollback()
    from modules.wms.invoice_reservations import InvoiceReservationRelease
    assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 0
    assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 1


@pytest.mark.parametrize("invalid", ["commit", "rollback", "source", "digest", "nested", "reuse"])
async def test_saved_fulfillment_verifier_cannot_escape_bound_transaction(api, session, invalid):
    from fastapi import HTTPException
    org, _, _, current, verifier = await collected_verifier(api, session)
    source, proof = current["source"], verifier.proof
    digest = proof.review_digest
    if invalid == "commit":
        await session.commit()
    elif invalid == "rollback":
        await session.rollback()
    elif invalid == "source":
        source = {**source, "version": source["version"] + 1}
    elif invalid == "digest":
        digest = "0" * 64
    elif invalid == "nested":
        await session.begin_nested()
    else:
        assert await verifier.verify_no_shipment(session, org, source, proof.review_id, digest) == proof
    with pytest.raises(HTTPException) as error:
        await verifier.verify_no_shipment(session, org, source, proof.review_id, digest)
    assert error.value.status_code == 409
    await session.rollback()


async def test_saved_fulfillment_verifier_rejects_history_after_midnight(api, session, monkeypatch):
    from datetime import date, timedelta

    from fastapi import HTTPException

    from modules.sales import invoice_cancellation
    org, _, _, current, verifier = await collected_verifier(api, session)
    class NextDay(date):
        @classmethod
        def today(cls):
            return verifier.review_date + timedelta(days=1)
    monkeypatch.setattr(invoice_cancellation, "date", NextDay)
    with pytest.raises(HTTPException) as error:
        await verifier.verify_no_shipment(session, org, current["source"],
            verifier.proof.review_id, verifier.proof.review_digest)
    assert error.value.status_code == 409
    await session.rollback()


async def cancel_request(api, org, facts):
    path, review = await review_request(api, org, facts)
    saved = await api.post(path, json=review)
    assert saved.status_code == 201, saved.text
    return path.replace('/fulfillment-review', '/cancel'), {
        "expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"],
        "request_key": str(uuid4()), "fulfillment_review_id": saved.json()["review_id"],
        "expected_review_digest": saved.json()["review_digest"],
        "evidence": "Synthetic lost deal, fully reconciled", "acknowledge_invoice_invalidation": True}


@pytest.mark.parametrize("paid_refunded", [False, True])
async def test_atomic_cancellation_releases_once_preserves_original_and_records_event(api, session, paid_refunded):
    from core.domain.models import OutboxEvent
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
    from modules.wms.invoice_reservations import InvoiceReservationRelease
    if paid_refunded:
        await erp_money_flow(api, session)
        policy = await session.scalar(select(Policy))
        org = policy.organization_id
        facts = await SalesReservationSource().invoice_reservation(session, 1)
        await session.commit()
    else:
        org, facts = await prepared(api, session)
    doc = await session.get(DealDocument, 1)
    if paid_refunded:
        doc.status = "paid"
    original = (doc.original_html, doc.content_sha256, doc.version, doc.amount)
    await session.commit()
    path, data = await cancel_request(api, org, facts)
    response = await api.post(path, json=data)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "cancelled"
    assert (await api.post(path, json=data)).json() == response.json()
    assert (await api.post(path, json={**data, "request_key": str(uuid4())})).status_code == 409
    await session.refresh(doc)
    assert (doc.original_html, doc.content_sha256, doc.version, doc.amount) == original
    assert (doc.status, doc.reserve_status) == ("cancelled", "released")
    assert await session.scalar(select(func.count()).select_from(InvoiceCancellationReceipt)) == 1
    assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 1
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.event_type == "sales.invoice.cancelled")) == 1
    assert await session.scalar(select(func.count()).select_from(PhysicalShipmentAct)) == 0


async def test_cancel_failure_after_release_rolls_back_entire_package(api, session, monkeypatch):
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
    from modules.wms.invoice_reservations import InvoiceReservationRelease
    org, facts = await prepared(api, session)
    path, data = await cancel_request(api, org, facts)
    bus = api._transport.app.state.core.event_bus
    original_emit = bus.emit
    def fail(session, event_type, payload, version=1):
        if event_type == "sales.invoice.cancelled":
            raise RuntimeError("Synthetic failure after release")
        return original_emit(session, event_type, payload, version)
    monkeypatch.setattr(bus, "emit", fail)
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        await api.post(path, json=data)
    for model in (InvoiceCancellationReceipt, InvoiceReservationRelease):
        assert await session.scalar(select(func.count()).select_from(model)) == 0
    doc = await session.get(DealDocument, 1)
    assert doc.status != "cancelled" and doc.reserve_status == "reserved"
    assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 1
    await session.commit()
    monkeypatch.setattr(bus, "emit", original_emit)
    assert (await api.post(path, json=data)).status_code == 201


@pytest.mark.integration
@pytest.mark.parametrize("paid_refunded", [False, True])
async def test_pg_atomic_cancellation_and_deferred_package(issuance_pg, paid_refunded):
    api, factory = issuance_pg
    async with factory() as session:
        connection = await session.connection()
        for model in (CarrierBid, CarrierRfqInvite, User):
            await connection.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        await session.commit()
        await test_atomic_cancellation_releases_once_preserves_original_and_records_event(api, session, paid_refunded)
    for sql in ("UPDATE sales.invoice_cancellation_receipt SET actor='changed'",
                "DELETE FROM sales.invoice_cancellation_receipt", "TRUNCATE sales.invoice_cancellation_receipt",
                "UPDATE sales.deal_document SET status='issued' WHERE id=1"):
        async with factory() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text(sql))
            await session.rollback()


@pytest.mark.integration
async def test_pg_cancellation_rejects_direct_status_and_incomplete_package(issuance_pg, monkeypatch):
    from core.domain.models import OutboxEvent
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
    from modules.wms.invoice_reservations import InvoiceReservationRelease
    api, factory = issuance_pg
    async with factory() as session:
        connection = await session.connection()
        for model in (CarrierBid, CarrierRfqInvite, User):
            await connection.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        await session.commit()
        org, facts = await prepared(api, session)
        with pytest.raises(DBAPIError, match="atomic cancellation"):
            await session.execute(text("UPDATE sales.deal_document SET status='cancelled' WHERE id=1"))
        await session.rollback()
    path, data = await cancel_request(api, org, facts)
    bus = api._transport.app.state.core.event_bus
    emit = bus.emit
    def missing_event(session, event_type, payload, version=1):
        if event_type != "sales.invoice.cancelled":
            emit(session, event_type, payload, version)
    monkeypatch.setattr(bus, "emit", missing_event)
    with pytest.raises(DBAPIError, match="cancellation package"):
        await api.post(path, json=data)
    async with factory() as session:
        for model in (InvoiceCancellationReceipt, InvoiceReservationRelease):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 1
        doc = await session.get(DealDocument, 1)
        assert doc.status != "cancelled" and doc.reserve_status == "reserved"
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "sales.invoice.cancelled")) == 0
    monkeypatch.setattr(bus, "emit", emit)
    assert (await api.post(path, json=data)).status_code == 201


@pytest.mark.integration
@pytest.mark.parametrize("correction", [False, True])
async def test_pg_cancellation_package_rechecks_bank_written_after_application_review(issuance_pg, monkeypatch, correction):
    from modules.accounting import service as accounting_service
    from modules.accounting.documents import BankDocument
    from modules.accounting.models import Entry
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
    from modules.wms.invoice_reservations import InvoiceReservationRelease
    from tests.accounting.test_bank_documents import document
    api, factory = issuance_pg
    async with factory() as session:
        connection = await session.connection()
        for model in (CarrierBid, CarrierRfqInvite, User):
            await connection.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        await session.commit()
        await erp_money_flow(api, session)
        policy = await session.scalar(select(Policy))
        org, policy_id = policy.organization_id, policy.id
        facts = await SalesReservationSource().invoice_reservation(session, 1)
        await session.commit()
    path, data = await cancel_request(api, org, facts)
    wms = api._transport.app.state.core.services.wms_reservations
    release = wms.release_invoice
    async def faulty_writer(session, organization_id, source, request, actor, verifier):
        result = await release(session, organization_id, source, request, actor, verifier)
        # Fault injection: an internal writer violates the no-money-edits contract.
        posting = BankDocument(**document(policy_id=policy_id, source="fault-bank-after-review",
            statement_reference="fault-bank-after-review", amount="1.00",
            settlement_dimensions={"settlement_document": "sales:document:1"})).posting()
        if correction:
            original_id = await session.scalar(select(Entry.id).where(
                Entry.organization_id == org, Entry.operation == "bank_settlement").order_by(Entry.id).limit(1))
            posting = posting.model_copy(update={"correction_of": original_id})
        await accounting_service.post(session, org, posting, "issuer")
        return result
    monkeypatch.setattr(wms, "release_invoice", faulty_writer)
    with pytest.raises(DBAPIError, match="cancellation package"):
        await api.post(path, json=data)
    async with factory() as session:
        for model in (InvoiceCancellationReceipt, InvoiceReservationRelease):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.source == "fault-bank-after-review")) == 0
        doc = await session.get(DealDocument, 1)
        assert doc.status != "cancelled" and doc.reserve_status == "reserved"


@pytest.mark.integration
async def test_pg_cancellation_rejects_malformed_saved_sections_even_with_faulty_verifier(issuance_pg, monkeypatch):
    from dataclasses import replace

    from core.services.wms import no_shipment_review_digest
    from modules.sales import invoice_cancellation as cancellation
    from modules.wms.invoice_reservations import InvoiceReservationRelease
    api, factory = issuance_pg
    async with factory() as session:
        connection = await session.connection()
        for model in (CarrierBid, CarrierRfqInvite, User):
            await connection.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        await session.commit()
        org, facts = await prepared(api, session)
    path, data = await cancel_request(api, org, facts)
    valid_id, valid_digest = data["fulfillment_review_id"], data["expected_review_digest"]
    async with factory() as session:
        valid = await session.get(SalesFulfillmentReview, valid_id)
        snapshot = deepcopy(valid.snapshot)
        snapshot["sections"] = {key: None for key in snapshot["sections"]}
        malformed = SalesFulfillmentReview(id=str(uuid4()), organization_id=org, document_id=1,
            money_reconciliation_id=valid.money_reconciliation_id, request_key=str(uuid4()),
            request_hash=valid.request_hash, request=deepcopy(valid.request), snapshot=snapshot, actor=valid.actor)
        malformed.digest = cancellation.review_digest(malformed)
        session.add(malformed)
        await session.commit()
        bad_id, bad_digest = malformed.id, malformed.digest
    original = cancellation.prepare_fulfillment_verifier
    async def faulty_verifier(session, services, org_id, basis, current, review_id, expected_digest):
        verified = await original(session, services, org_id, basis, current, valid_id, valid_digest)
        proof = replace(verified.proof, review_id=bad_id,
            references=tuple(replace(ref, record_id=bad_id + ':' + ref.scope, revision=bad_digest)
                             for ref in verified.proof.references))
        proof = replace(proof, review_digest=no_shipment_review_digest(proof))
        # Inject an internal verification defect; immutable database guards remain enabled.
        return replace(verified, stored_review_digest=bad_digest, proof=proof)
    monkeypatch.setattr(cancellation, "prepare_fulfillment_verifier", faulty_verifier)
    with pytest.raises(DBAPIError, match="cancellation package"):
        await api.post(path, json={**data, "fulfillment_review_id": bad_id, "expected_review_digest": bad_digest})
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(cancellation.InvoiceCancellationReceipt)) == 0
        assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == 0
        doc = await session.get(DealDocument, 1)
        assert doc.status != "cancelled" and doc.reserve_status == "reserved"


@pytest.mark.integration
async def test_pg_cancellation_requires_actual_withdrawal_of_bound_targets(issuance_pg, monkeypatch):
    from modules.logistics.models import CarrierRfq, Shipment
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
    from modules.wms.invoice_reservations import InvoiceReservationRelease
    from tests.test_logistics_withdrawal import targets
    api, factory = issuance_pg
    async with factory() as session:
        connection = await session.connection()
        for model in (CarrierBid, CarrierRfqInvite, User):
            await connection.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        await session.commit()
        org, facts = await prepared(api, session)
    exact = {"organization_id": org, "document_id": 1, "expected_version": facts["version"],
             "expected_content_sha256": facts["content_sha256"]}
    ship_id, rfq_id = await targets(api, exact)
    path, data = await cancel_request(api, org, facts)
    gateway = api._transport.app.state.core.services.logistics
    original = gateway.withdraw_unexecuted_invoice
    async def omit_withdrawal(session, **kwargs):
        # Faulty writer claims withdrawal without changing its actual bound rows.
        body = {"schema_version": 1, "exact_invoice": exact,
            "cancel_receipt_identity": kwargs["cancel_receipt_identity"],
            "before_snapshot_sha256": kwargs["expected_digest"], "changes": [],
            "resolved_intake_ids_preserved": [], "enforcement": "application_only", "coverage_complete": False,
            "coverage_gaps": kwargs["current_snapshot"]["coverage_gaps"]}
        return {**body, "sha256": snapshot_hash(body)}
    monkeypatch.setattr(gateway, "withdraw_unexecuted_invoice", omit_withdrawal)
    with pytest.raises(DBAPIError, match="cancellation package"):
        await api.post(path, json=data)
    async with factory() as session:
        for model in (InvoiceCancellationReceipt, InvoiceReservationRelease):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        assert (await session.get(Shipment, ship_id)).status == "planned"
        assert (await session.get(CarrierRfq, rfq_id)).status == "draft"
    monkeypatch.setattr(gateway, "withdraw_unexecuted_invoice", original)
    response = await api.post(path, json=data)
    assert response.status_code == 201, response.text
    async with factory() as session:
        assert (await session.get(Shipment, ship_id)).status == "withdrawn"
        assert (await session.get(CarrierRfq, rfq_id)).status == "withdrawn"


@pytest.mark.parametrize("field,value", [("status", "issued"), ("reserve_status", "reserved")])
async def test_cancelled_receipt_prevents_orm_reopening(api, session, field, value):
    org, facts = await prepared(api, session)
    path, data = await cancel_request(api, org, facts)
    assert (await api.post(path, json=data)).status_code == 201
    doc = await session.get(DealDocument, 1)
    setattr(doc, field, value)
    with pytest.raises(ValueError, match="cancellation is terminal"):
        await session.flush()
    await session.rollback()


@pytest.mark.parametrize("risk,code", [
    ("carrier", "unexecuted_logistics_withdrawal_required"),
    ("accounting_queue", "accounting_fulfillment_classification_required"),
])
async def test_cancellation_preview_explains_review_restrictions_before_saving(api, session, risk, code):
    from modules.accounting.models import Inbox
    from modules.logistics.models import Shipment
    org, facts = await prepared(api, session)
    identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    if risk == "carrier":
        response = await api.post("/logistics/shipments", json={
            "invoice": {"organization_id": org, "document_id": 1, **identity},
            "source_key": "preview-carrier", "customer": "Synthetic"})
        assert response.status_code == 201, response.text
        shipment = await session.get(Shipment, response.json()["id"])
        shipment.carrier = "Carrier engagement requires review"
    else:
        session.add(Inbox(organization_id=org, event_key="preview-unprocessed", month="2026-09",
            payload={"source": "sales:document:1"}, error=None, entry_id=None))
    await session.commit()
    path, data = await review_request(api, org, facts)
    response = await api.post(path.replace('/fulfillment-review', '/cancellation/preview'), json=identity)
    assert response.status_code == 200, response.text
    result = response.json()
    assert code in result["observed_blockers"]
    issue = next(item for item in result["eligibility_issues"] if item["code"] == code)
    assert issue["message"] and issue["detail"]
    assert result["basis_digest"] == snapshot_hash({k: v for k, v in result.items() if k != "basis_digest"})
    assert (await api.post(path, json=data)).status_code == 409
    assert await session.scalar(select(func.count()).select_from(SalesFulfillmentReview)) == 0
