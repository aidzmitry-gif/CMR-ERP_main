"""Existing G12YU SQL counterexamples on the canonical migration draft.

No registered 0198 or production acceptance is claimed. The fixture applies
exact existing 0198 SQL to a fresh marked database migrated to public 0194.
Only the obsolete private-chain fixture selector and test prefixes change.
Original source SHA256: 9cbab079e1330706cc36d268366bbd580da82e687f3cd1a4da0532fc687804eb.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.integration.test_unreserved_cancellation_postgres import (
    CONTRACT_AVAILABLE,
    issuance_pg,  # noqa: F401
    pg_factory,  # noqa: F401
    unreserved_pg,  # noqa: F401
)

pytestmark = pytest.mark.skipif(not CONTRACT_AVAILABLE, reason="Registered 0198 or an explicit local proposal required")


@pytest.fixture
def registered_api(unreserved_pg):  # noqa: F811
    return unreserved_pg


async def _atomic_on_order(api, session, *, refunded=False, later=False):
    from datetime import date, timedelta

    from sqlalchemy import select

    from modules.accounting.models import Policy
    from modules.sales.models import DealDocument
    from tests.test_invoice_issuance import create, erp_money_flow, seed

    if refunded:
        await erp_money_flow(api, session, reserve_mode="on_order")
        doc = await session.get(DealDocument, 1)
        policy = await session.scalar(select(Policy))
        return {"org": policy.organization_id, "deal": doc.deal_id}, doc, None
    ids, base = await seed(api, session)
    base.update(reserve_mode="on_order", valid_until=(date.today() + timedelta(days=5)).isoformat())
    preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
    assert preview.status_code == 200, preview.text
    p = preview.json()
    issued = await create(api, ids, {**base, "request_key": "atomic-no-stock-issue",
        "expected_document_version": p["document_version"], "expected_basis_digest": p["basis_digest"],
        "allocations": [], "unreserved_confirmed": True})
    assert issued.status_code == 201, issued.text
    session.expire_all()
    doc = await session.get(DealDocument, issued.json()["document"]["id"])
    if later:
        reserved = await api.post(f"/sales/deals/{ids['deal']}/documents/{doc.id}/reservation", json={
            "organization_id": ids["org"], "request_key": "atomic-late-reserve", "expected_document_version": doc.version,
            "expected_content_sha256": doc.content_sha256,
            "allocations": [{"line_no": 1, "warehouse": "W", "qty": "2.00"}],
            "evidence": "Synthetic complete warehouse journal", "journal_complete": True})
        assert reserved.status_code == 201, reserved.text
        await session.refresh(doc)
    return ids, doc, base


async def _atomic_command(api, session, ids, doc):
    from tests.test_invoice_cancellation import cancel_request

    facts = {"version": doc.version, "content_sha256": doc.content_sha256}
    await session.commit()
    return await cancel_request(api, ids["org"], facts)


async def _assert_no_warehouse_changes(session, doc_id):
    from sqlalchemy import select

    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.invoice_issuance import (
        InvoiceLateReservationReceipt,
        unreserved_issuance_anchor,
        verified_receipt,
    )
    from modules.sales.models import DealDocument
    from modules.wms.invoice_fulfillment import unreserved_snapshot

    doc = await session.get(DealDocument, doc_id)
    owner = await session.get(DealOwnership, doc.deal_id)
    issuance = await verified_receipt(session, doc, owner.organization_id)
    source = {"organization_id": owner.organization_id, "document_id": doc.id,
        "version": doc.version, "content_sha256": doc.content_sha256,
        "issuance_receipt": unreserved_issuance_anchor(doc, owner.organization_id, issuance),
        "reserve_mode": "on_order", "reserve_status": "unreserved", "reservation_digest": None,
        "allocations": [], "operation": "cancellation", "fulfillment_allowed": False}
    observed = await session.run_sync(lambda sync: unreserved_snapshot(sync.connection(), owner.organization_id, source))
    assert observed["snapshot"]["remaining"]["reservation_absent"] is True
    assert await session.scalar(select(InvoiceLateReservationReceipt.document_id).where(
        InvoiceLateReservationReceipt.document_id == doc.id)) is None


async def _captured_cancellation(api, factory, ids, data):
    """Capture a real authorized complete package, then undo only that command."""
    from copy import deepcopy

    from sqlalchemy import select

    from core.services.auth import CurrentUser
    from modules.sales import accounting_ownership
    from modules.sales import invoice_cancellation as cancellation

    core = api._transport.app.state.core
    async with factory() as session:
        user = CurrentUser("issuer", ["director"])
        ctx = await accounting_ownership.context(ids["org"], session, core, user)
        await cancellation.cancel(ids["org"], 1, cancellation.CancellationInput.model_validate(data), ctx, core, user)
        row = await session.scalar(select(cancellation.InvoiceCancellationReceipt))
        values = {column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns}
        await session.rollback()
    return values


async def _insert_cancellation_package(session, core, values, *, changed_original=False):
    """Core SQL intentionally bypasses ORM hooks; every PostgreSQL guard stays on."""
    from sqlalchemy import update

    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
    from modules.sales.models import DealDocument

    if changed_original:
        await session.execute(update(DealDocument.__table__).where(DealDocument.id == values["document_id"])
                              .values(original_html="Synthetic forged original"))
    await session.execute(InvoiceCancellationReceipt.__table__.insert().values(**values))
    await session.execute(update(DealDocument.__table__).where(DealDocument.id == values["document_id"])
                          .values(status="cancelled", reserve_status="unreserved"))
    core.event_bus.emit(session, "sales.invoice.cancelled", {"organization_id": values["organization_id"],
        "document_id": values["document_id"], "document_version": values["document_version"],
        "content_sha256": values["content_sha256"], "cancellation_id": values["id"],
        "cancellation_digest": values["digest"], "release_id": values["release_id"],
        "customer_notification": "requires_authorized_send", "by": values["actor"]})
    await session.flush()


@pytest.mark.parametrize("fault", ["missing_tag", "null_release_reserved_tag", "release_present_no_stock_tag",
    "changed_original", "missing_fulfillment_review", "missing_withdrawal_package", "wrong_identity",
    "schema_float", "schema_string", "schema_bool", "schema_null"])
async def test_draft_no_stock_raw_sql_guards(registered_api, fault):
    from copy import deepcopy

    from sqlalchemy import func, select
    from sqlalchemy.exc import DBAPIError

    from core.domain.models import OutboxEvent
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt, cancellation_digest
    from modules.sales.models import DealDocument

    api, factory = registered_api
    async with factory() as session:
        ids, doc, _ = await _atomic_on_order(api, session)
        path, data = await _atomic_command(api, session, ids, doc)
        original = (doc.original_html, deepcopy(doc.snapshot_json), doc.content_sha256)
    core = api._transport.app.state.core
    captured = await _captured_cancellation(api, factory, ids, data)
    # Mandatory positive reconstruction: a broken common constructor must fail
    # this case rather than produce eleven spurious negative "successes".
    async with factory() as session:
        await _insert_cancellation_package(session, core, captured)
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await session.rollback()
    values = deepcopy(captured)
    snapshot = values["snapshot"]
    if fault == "missing_tag":
        snapshot.pop("stock_outcome")
    elif fault == "null_release_reserved_tag":
        snapshot["stock_outcome"] = "released"
    elif fault == "release_present_no_stock_tag":
        snapshot["release"] = None
    elif fault == "missing_fulfillment_review":
        values["fulfillment_review_id"] = str(uuid4())
    elif fault == "missing_withdrawal_package":
        snapshot.pop("withdrawal")
    elif fault == "wrong_identity":
        snapshot["no_stock_release"]["exact_invoice"]["expected_version"] += 1
    elif fault.startswith("schema_"):
        snapshot["no_stock_release"]["schema_version"] = {
            "schema_float": 1.0, "schema_string": "1", "schema_bool": True, "schema_null": None}[fault]
    values["digest"] = cancellation_digest(SimpleNamespace(**values))
    async with factory() as session:
        with pytest.raises(DBAPIError) as refused:
            await _insert_cancellation_package(session, core, values, changed_original=fault == "changed_original")
            await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            await session.commit()
        code = refused.value.orig.sqlstate
        if fault in {"missing_tag", "null_release_reserved_tag", "release_present_no_stock_tag"}:
            assert code == "23514" and "invoice_cancellation_stock_outcome" in str(refused.value.orig)
        elif fault == "missing_fulfillment_review":
            assert code == "23503"
        else:
            assert code == "P0001"
        await session.rollback()
    async with factory() as session:
        doc = await session.get(DealDocument, 1)
        assert (doc.status, doc.reserve_status) == ("issued", "unreserved")
        assert (doc.original_html, doc.snapshot_json, doc.content_sha256) == original
        assert await session.scalar(select(func.count()).select_from(InvoiceCancellationReceipt)) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "sales.invoice.cancelled")) == 0
        await _assert_no_warehouse_changes(session, doc.id)


@pytest.mark.parametrize("number", [1e-06, -0.0], ids=["exponent", "negative_zero"])
async def test_draft_original_json_parity(registered_api, number):
    from datetime import date, timedelta

    from core.domain.models import Counterparty
    from modules.sales.documents import digest
    from modules.sales.models import DealDocument
    from tests.test_invoice_issuance import create, seed

    api, factory = registered_api
    async with factory() as session:
        ids, base = await seed(api, session)
        buyer = await session.get(Counterparty, ids["buyer"])
        buyer.requisites = {**buyer.requisites, "Проверка": {"текст": "Синтетический пример", "число": number, "список": [number, "я"]}}
        await session.commit()
        base.update(reserve_mode="on_order", valid_until=(date.today() + timedelta(days=5)).isoformat())
        preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
        assert preview.status_code == 200, preview.text
        p = preview.json()
        issued = await create(api, ids, {**base, "request_key": "numeric-original",
            "expected_document_version": p["document_version"], "expected_basis_digest": p["basis_digest"],
            "allocations": [], "unreserved_confirmed": True})
        assert issued.status_code == 201, issued.text
        doc = await session.get(DealDocument, issued.json()["document"]["id"])
        sql_hash = await session.scalar(text("SELECT encode(sha256(convert_to(sales.invoice_original_json(snapshot_json),'UTF8')),'hex') FROM sales.deal_document WHERE id=:id"), {"id": doc.id})
        assert sql_hash == digest(doc.snapshot_json)
        path, data = await _atomic_command(api, session, ids, doc)
    cancelled = await api.post(path, json=data)
    assert cancelled.status_code == 201, cancelled.text
    assert cancelled.json()["stock_outcome"] == "no_stock_release"


@pytest.mark.parametrize("case", ["late_reserve_against_cancel", "two_cancellations",
                                "money_after_review_before_commit", "fulfillment_after_review_before_commit"])
async def test_draft_no_stock_races(registered_api, monkeypatch, case):
    import asyncio
    from copy import deepcopy

    from sqlalchemy import func, select
    from sqlalchemy.exc import DBAPIError

    from core.domain.models import OutboxEvent
    from core.services.auth import CurrentUser
    from modules.accounting import service as accounting_service
    from modules.accounting.documents import BankDocument
    from modules.accounting.models import Entry, Policy
    from modules.sales import accounting_ownership
    from modules.sales import invoice_cancellation as cancellation
    from modules.sales.models import DealDocument
    from modules.wms.invoice_reservations import InvoiceReservation
    from modules.wms.models import StockMovement, Task
    from tests.accounting.test_bank_documents import document

    api, factory = registered_api
    core = api._transport.app.state.core
    async with factory() as session:
        ids, doc, _ = await _atomic_on_order(api, session, refunded=case == "money_after_review_before_commit")
        original = (doc.original_html, deepcopy(doc.snapshot_json), doc.content_sha256)
        physical = (await session.execute(select(StockMovement.id, StockMovement.qty).order_by(StockMovement.id))).all()
        path, data = await _atomic_command(api, session, ids, doc)
    if case in {"late_reserve_against_cancel", "two_cancellations"}:
        original_lock = accounting_service.lock_organization
        both = asyncio.Event()
        entered = set()
        pids = set()

        async def overlapping(session, organization_id):
            if organization_id == ids["org"] and id(session) not in entered:
                entered.add(id(session))
                assert session.in_transaction()
                pids.add(await session.scalar(text("SELECT pg_backend_pid()")))
                if len(entered) == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), timeout=5)
            return await original_lock(session, organization_id)

        monkeypatch.setattr(accounting_service, "lock_organization", overlapping)
        if case == "late_reserve_against_cancel":
            second = api.post("/sales/deals/1/documents/1/reservation", json={"organization_id": ids["org"],
                "request_key": "concurrent-later-reservation", "expected_document_version": data["expected_version"],
                "expected_content_sha256": data["expected_content_sha256"],
                "allocations": [{"line_no": 1, "warehouse": "W", "qty": "2.00"}],
                "evidence": "Synthetic complete stock journal", "journal_complete": True})
        else:
            second = api.post(path, json={**data, "request_key": str(uuid4())})
        responses = await asyncio.gather(api.post(path, json=data), second)
        assert len(pids) == len(entered) == 2, "Two live PostgreSQL transactions must overlap before their actual book lock"
        assert sorted(r.status_code for r in responses) == [201, 409], [r.text for r in responses]
        async with factory() as session:
            doc = await session.get(DealDocument, 1)
            count = await session.scalar(select(func.count()).select_from(cancellation.InvoiceCancellationReceipt))
            reservations = await session.scalar(select(func.count()).select_from(InvoiceReservation))
            if doc.status == "cancelled":
                assert count == 1 and reservations == 0 and doc.reserve_status == "unreserved"
                await _assert_no_warehouse_changes(session, 1)
            else:
                assert case == "late_reserve_against_cancel" and count == 0 and reservations == 1 and doc.reserve_status == "reserved"
            assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.event_type == "sales.invoice.cancelled")) == count
            assert (doc.original_html, doc.snapshot_json, doc.content_sha256) == original
            assert (await session.execute(select(StockMovement.id, StockMovement.qty).order_by(StockMovement.id))).all() == physical
        return
    async with factory() as session:
        user = CurrentUser("issuer", ["director"])
        ctx = await accounting_ownership.context(ids["org"], session, core, user)
        await cancellation.cancel(ids["org"], 1, cancellation.CancellationInput.model_validate(data), ctx, core, user)
        if case == "money_after_review_before_commit":
            policy = await session.scalar(select(Policy))
            posting = BankDocument(**document(policy_id=policy.id, source="no-stock-after-review",
                statement_reference="no-stock-after-review", amount="1.00",
                settlement_dimensions={"settlement_document": "sales:document:1"})).posting()
            await accounting_service.post(session, ids["org"], posting, "issuer")
        else:
            await session.execute(Task.__table__.insert().values(organization_id=ids["org"], kind="pick", status="open",
                warehouse="W", sku_code=ids["code"], qty=1, doc_ref="sales:document:1"))
        with pytest.raises(DBAPIError) as refused:
            await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            await session.commit()
        assert refused.value.orig.sqlstate == "P0001"
        message = str(refused.value.orig)
        assert ("cancellation package" in message if case == "money_after_review_before_commit"
                else "Unreserved invoice has addressed WMS history" in message)
        await session.rollback()
    async with factory() as session:
        doc = await session.get(DealDocument, 1)
        assert (doc.status, doc.reserve_status) == ("issued", "unreserved")
        assert (doc.original_html, doc.snapshot_json, doc.content_sha256) == original
        assert await session.scalar(select(func.count()).select_from(cancellation.InvoiceCancellationReceipt)) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "sales.invoice.cancelled")) == 0
        assert await session.scalar(select(func.count()).select_from(Entry).where(Entry.source == "no-stock-after-review")) == 0
        await _assert_no_warehouse_changes(session, 1)
