from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import delete, func, select, update

from core.domain.models import Counterparty, OutboxEvent, Sku
from modules.accounting.models import AccessGrant, Organization
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.client_document_register import DealClientBinding, preview_snapshot
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt, verified_receipt
from modules.sales.models import Deal, DealDocument, DealItem
from modules.sales.reservation_source import SalesReservationSource
from modules.sales.reserve import tick_invoice_reserve
from modules.wms.invoice_reservations import InvoiceReservation
from modules.wms.models import ReservationVersion, StockMovement


async def seed(api, session, *, qty="2", physical="10", suffix=""):
    api.headers["X-User"] = "issuer"
    serial = int(sha256(suffix.encode()).hexdigest()[:8], 16) % 400000000
    org = Organization(name="Bound seller" + suffix, unp=str(100000000 + serial))
    buyer = Counterparty(
        name="Exact buyer" + suffix,
        unp=str(500000000 + serial),
        requisites={"address": "Buyer address"},
    )
    sku = Sku(code="ERP" + suffix, title="Exact goods", unit="шт")
    deal = Deal(
        number="ERP" + suffix, title="ERP issue", counterparty="WRONG DISPLAY NAME", amount=999
    )
    session.add_all([org, buyer, sku, deal])
    await session.flush()
    item = DealItem(deal_id=deal.id, sku_id=sku.id, qty=Decimal(qty))
    session.add(item)
    session.add(AccessGrant(organization_id=org.id, subject="issuer", role="chief"))
    session.add(
        DealOwnership(
            deal_id=deal.id,
            organization_id=org.id,
            snapshot={},
            evidence="Synthetic ownership",
            actor="issuer",
        )
    )
    await session.flush()
    session.add(
        DealClientBinding(
            deal_id=deal.id,
            organization_id=org.id,
            counterparty_id=buyer.id,
            snapshot=await preview_snapshot(session, org.id, deal, buyer.id),
            evidence="Synthetic exact binding",
            actor="issuer",
        )
    )
    session.add(
        StockMovement(
            organization_id=org.id,
            sku_code=sku.code,
            warehouse="W",
            kind="in",
            qty=Decimal(physical),
            reason="receipt",
        )
    )
    await session.commit()
    ids = {
        "org": org.id,
        "buyer": buyer.id,
        "sku": sku.id,
        "deal": deal.id,
        "item": item.id,
        "code": sku.code,
    }
    response = await api.post(
        f"/accounting/organizations/{org.id}/seller-profiles",
        json={
            "source_key": "synthetic-seller",
            "expected_revision": 0,
            "effective_from": "2026-01-01",
            "currency": "BYN",
            "address": "Bound address",
            "account": "TEST ACCOUNT",
            "bank": "TEST BANK",
            "bik": "TEST BIK",
            "director": "Synthetic director",
            "evidence": "Approved synthetic seller",
            "confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    base = {
        "organization_id": ids["org"],
        "currency": "BYN",
        "document_date": "2026-09-01",
        "valid_until": "2026-09-06",
        "pricing": [{"item_id": ids["item"], "unit_price_net": "100.00", "vat_rate": "20.00"}],
        "pricing_evidence": "Explicit negotiated synthetic price and rate",
    }
    return ids, base


async def command(api, ids, base, *, doc_id=None, key="issue-key-original"):
    request = {**base, **({"document_id": doc_id} if doc_id else {})}
    response = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=request)
    assert response.status_code == 200, response.text
    p = response.json()
    assert p["availability"]["organization_id"] == ids["org"]
    assert p["availability"]["source"] == "wms_physical"
    return {
        **base,
        "request_key": key,
        "expected_document_version": p["document_version"],
        "expected_basis_digest": p["basis_digest"],
        "allocations": [
            {"line_no": line["line_no"], "warehouse": "W", "qty": line["qty"]}
            for line in p["lines"]
        ],
        "evidence": "Synthetic complete physical journal",
        "journal_complete": True,
    }, p


async def create(api, ids, cmd):
    return await api.post(f"/sales/deals/{ids['deal']}/documents", json={"kind": "invoice", **cmd})


async def erp_money_flow(api, session, reserve_mode="stock"):
    """Actual issued invoice, posted bank entries and accountant allocations."""
    from datetime import date

    from modules.accounting.models import Account, Policy
    from tests.accounting.test_invoice_settlements import bank

    ids, base = await seed(api, session)
    if reserve_mode == "stock":
        cmd, _ = await command(api, ids, base)
    else:
        base["reserve_mode"] = reserve_mode
        preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
        assert preview.status_code == 200, preview.text
        p = preview.json()
        cmd = {**base, "request_key": "on-order-money", "expected_document_version": p["document_version"],
               "expected_basis_digest": p["basis_digest"], "allocations": [], "unreserved_confirmed": True}
    issued = await create(api, ids, cmd)
    assert issued.status_code == 201, issued.text
    doc_id = issued.json()["document"]["id"]
    prefix = f"/sales/organizations/{ids['org']}/invoices"
    listed = await api.get(prefix)
    assert listed.status_code == 200, listed.text
    row = next(row for row in listed.json()["items"] if row["id"] == doc_id)
    assert row["available_for_settlement"] and row["counterparty"] == "Exact buyer"
    policy = Policy(organization_id=ids["org"], effective_from=date(2026, 1, 1),
        reference="TEST ONLY", inventory_method="specific", allocation_basis="direct_cost",
        depreciation_method="straight_line", normative_reference="synthetic fixture",
        normative_verified=True, approved_by="issuer")
    session.add(policy)
    for code, cash in [("51", True), ("62", False)]:
        session.add(Account(organization_id=ids["org"], code=code, title="Synthetic",
            category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
            currency_tracking=True, quantity_tracking=False, cash=cash, normative_ref="synthetic"))
    await session.commit()
    book = (ids["org"], policy.id)
    entry = await bank(api, book, doc_id, "erp-in", amount="240.00")
    url = f"{prefix}/{doc_id}"
    data = {"bank_entry_id": entry, "source_key": "erp-in", "amount": "240.00", "evidence": "Synthetic bank review"}
    allocated = await api.post(url + "/settlements", json=data)
    assert allocated.status_code == 201, allocated.text
    assert (await api.post(url + "/settlements", json=data)).json() == allocated.json()
    held = await api.get(url + "/money-basis")
    assert held.status_code == 200, held.text
    assert held.json()["money_state"] == "funds_held"
    assert "funds_not_fully_refunded" in held.json()["blockers"]
    refund = await bank(api, book, doc_id, "erp-refund", amount="240.00", direction="payment")
    refunded = await api.post(url + "/settlements", json={**data, "bank_entry_id": refund,
        "source_key": "erp-refund", "refund_of": allocated.json()["id"]})
    assert refunded.status_code == 201, refunded.text
    basis = await api.get(url + "/money-basis")
    assert basis.status_code == 200 and basis.json()["money_state"] == "fully_refunded", basis.text
    review = await api.get(url + "/money-reconciliation")
    assert review.status_code == 200, review.text
    assert review.json()["can_confirm_money_history"]
    status = (await api.get(url + "/settlements")).json()
    assert status["net_received"] == "0.00" and status["cancellation_authorized"] is False


async def test_erp_issued_invoice_accepts_bank_allocations_and_money_review(api, session):
    await erp_money_flow(api, session)


@pytest.mark.parametrize("change", ["missing_receipt", "changed_receipt", "changed_original", "buyer_null", "buyer_list", "snapshot_list"])
async def test_erp_money_rejects_unqualified_or_corrupted_original(api, session, change):
    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    issued = await create(api, ids, cmd)
    assert issued.status_code == 201, issued.text
    doc_id = issued.json()["document"]["id"]
    # Direct SQLite corruption models invalid persisted evidence; production PG
    # guards reject these changes. HTTP must still refuse the corrupted source.
    if change == "missing_receipt":
        await session.execute(delete(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc_id))
    elif change == "changed_receipt":
        await session.execute(update(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc_id).values(snapshot_digest="f" * 64))
    elif change == "changed_original":
        await session.execute(update(DealDocument).where(DealDocument.id == doc_id).values(original_html="wrong"))
    else:
        from datetime import datetime
        doc = await session.get(DealDocument, doc_id)
        snapshot = [] if change == "snapshot_list" else {**doc.snapshot_json, "buyer": None if change == "buyer_null" else []}
        await session.execute(update(DealDocument).where(DealDocument.id == doc_id).values(snapshot_json=snapshot))
        session.add(DealDocument(deal_id=ids["deal"], kind="invoice", number="LEGACY-OK", version=2,
            status="posted", amount="1.00", original_html="valid", content_sha256=sha256(b"valid").hexdigest(),
            issued_at=datetime(2026, 9, 1), snapshot_json={"currency": "BYN", "amount": "1.00", "deal": {"counterparty": "Valid buyer"}}))
    await session.commit()
    prefix = f"/sales/organizations/{ids['org']}/invoices"
    listing = await api.get(prefix)
    assert listing.status_code == 200, listing.text
    assert not listing.json()["items"][0]["available_for_settlement"]
    if change in {"buyer_null", "buyer_list", "snapshot_list"}:
        assert listing.json()["items"][1]["available_for_settlement"]
        assert listing.json()["items"][1]["counterparty"] == "Valid buyer"
    for path in ("settlements", "money-basis", "money-reconciliation"):
        response = await api.get(f"{prefix}/{doc_id}/{path}")
        assert response.status_code == 409, response.text


async def no_issue(session):
    assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt)) == 0
    assert await session.scalar(select(func.count()).select_from(InvoiceReservation)) == 0
    assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 0
    assert await session.scalar(select(func.count()).select_from(DealDocument)) == 0
    assert (
        await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.event_type.in_(["sales.invoice.issued", "sales.stock.reserved"]))
        )
        == 0
    )


async def test_local_issue_exact_original_receipt_and_events_without_legacy_gateways(api, session):
    ids, base = await seed(api, session)
    core = api._transport.app.state.core
    core.services.onec = None
    core.services.stock = None
    cmd, p = await command(api, ids, base)
    assert p["seller"]["name"] == "Bound seller" and p["buyer"]["name"] == "Exact buyer"
    assert p["buyer"]["counterparty_id"] == ids["buyer"] and p["amount"] == "240.00"
    await no_issue(session)
    response = await create(api, ids, cmd)
    assert response.status_code == 201, response.text
    result = response.json()
    doc = await session.get(DealDocument, result["document"]["id"])
    assert doc.status == "issued" and doc.onec_ref is None and doc.reserve_status == "reserved"
    receipt = await verified_receipt(session, doc, ids["org"])
    assert receipt is not None
    assert (await api.get(f"/sales/documents/{doc.id}/render")).status_code == 200
    original = doc.original_html
    assert "Exact buyer" in original and "WRONG DISPLAY NAME" not in original
    assert "20.00" in original and "2026-09-01" in original and "TEST ACCOUNT" in original
    events = (
        await session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type.in_(
                    ["sales.stock.reserved", "sales.invoice.issued", "sales.document.posted"]
                )
            )
        )
    ).all()
    assert {e.event_type for e in events} == {"sales.stock.reserved", "sales.invoice.issued"}
    for event in events:
        assert event.payload["issuance_receipt"]["document_id"] == doc.id
        assert event.payload["content_sha256"] == doc.content_sha256
        assert (
            event.payload["items"][0]["warehouse"] == "W"
            and event.payload["items"][0]["qty"] == "2.00"
        )
        assert (
            event.payload["items"][0]["line_no"] == 1
            and event.payload["reservation_digest"] == receipt.reservation_digest
        )
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == 1
    assert await session.scalar(select(ReservationVersion.qty)) == Decimal("2")
    facts = await SalesReservationSource().invoice_shipping_source(
        session,
        doc.id,
        organization_id=ids["org"],
        expected_version=doc.version,
        expected_content_sha256=doc.content_sha256,
    )
    assert (
        facts["fulfillment_allowed"]
        and facts["issuance_receipt"]["request_key"] == cmd["request_key"]
    )


async def test_replay_survives_changed_sources_without_new_events_or_stock(api, session):
    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    first = await create(api, ids, cmd)
    assert first.status_code == 201, first.text
    row = await session.get(DealItem, ids["item"])
    row.qty = 99
    buyer = await session.get(Counterparty, ids["buyer"])
    buyer.requisites = {"address": "Later"}
    await session.commit()
    second = await create(api, ids, cmd)
    assert second.status_code == 200, second.text
    assert second.json() == {**first.json(), "replayed": True}
    assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt)) == 1
    assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence", "different"),
        ("currency", "USD"),
        ("organization_id", 999),
        ("request_key", "other-issue-key"),
        ("pricing_evidence", "new price basis"),
        ("journal_complete", False),
    ],
)
async def test_changed_payload_does_not_reissue(api, session, field, value):
    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    first = await create(api, ids, cmd)
    assert first.status_code == 201
    r = await create(api, ids, {**cmd, field: value})
    assert r.status_code in {403, 404, 409}, r.text
    assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt)) == 1


@pytest.mark.parametrize(
    "change", ["buyer", "seller", "item", "sku", "ownership", "binding", "inactive", "merged"]
)
async def test_current_source_change_rejects_stale_basis(api, session, change):
    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    if change == "buyer":
        (await session.get(Counterparty, ids["buyer"])).requisites = {"address": "Changed"}
    elif change == "item":
        (await session.get(DealItem, ids["item"])).qty = 3
    elif change == "sku":
        (await session.get(Sku, ids["sku"])).title = "Changed goods"
    elif change == "inactive":
        (await session.get(Counterparty, ids["buyer"])).is_active = False
    elif change == "merged":
        (await session.get(Counterparty, ids["buyer"])).merged_into_id = 99
    elif change == "ownership":
        await session.execute(update(DealOwnership).values(organization_id=99))
    elif change == "binding":
        await session.execute(update(DealClientBinding).values(organization_id=99))
    elif change == "seller":
        r = await api.post(
            f"/accounting/organizations/{ids['org']}/seller-profiles",
            json={
                "source_key": "second-seller",
                "expected_revision": 1,
                "effective_from": "2026-01-02",
                "currency": "BYN",
                "address": "New address",
                "account": "NEW ACCOUNT",
                "bank": "TEST BANK",
                "bik": "TEST BIK",
                "director": "Director",
                "evidence": "New synthetic profile",
                "confirmed": True,
            },
        )
        assert r.status_code == 201, r.text
    await session.commit()
    r = await create(api, ids, cmd)
    assert r.status_code == 409, r.text
    await no_issue(session)


@pytest.mark.parametrize(
    "change",
    [
        "price_float",
        "rate_float",
        "qty_float",
        "missing_payload",
        "warehouse",
        "incomplete",
        "wrong_line",
        "split_wrong_qty",
    ],
)
async def test_strict_payload_no_fallback(api, session, change):
    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    if change == "price_float":
        cmd["pricing"][0]["unit_price_net"] = 100.0
    elif change == "rate_float":
        cmd["pricing"][0]["vat_rate"] = 20.0
    elif change == "qty_float":
        cmd["allocations"][0]["qty"] = 2.0
    elif change == "warehouse":
        del cmd["allocations"][0]["warehouse"]
    elif change == "incomplete":
        cmd["journal_complete"] = False
    elif change == "wrong_line":
        cmd["allocations"][0]["line_no"] = 9
    elif change == "split_wrong_qty":
        cmd["allocations"][0]["qty"] = "1"
    elif change == "missing_payload":
        cmd = {}
    r = await create(api, ids, cmd)
    assert r.status_code in {409, 422}, r.text
    await no_issue(session)


@pytest.mark.parametrize("failure", ["reserve", "render", "outbox", "missing_gateway", "shortage"])
async def test_failed_issue_rolls_back_every_component(api, session, monkeypatch, failure):
    ids, base = await seed(api, session, physical="1" if failure == "shortage" else "10")
    cmd, _ = await command(api, ids, base)
    core = api._transport.app.state.core

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic failure")

    if failure == "reserve":
        original = core.services.wms_reservations.reserve_invoice

        async def reserve_fail(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError("Synthetic failure after reserve flush")

        monkeypatch.setattr(core.services.wms_reservations, "reserve_invoice", reserve_fail)
    elif failure == "render":
        from modules.sales import documents

        monkeypatch.setattr(documents, "render_erp_invoice", fail)
    elif failure == "outbox":
        original = core.event_bus.emit

        def outbox_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("Synthetic failure after event add")

        monkeypatch.setattr(core.event_bus, "emit", outbox_fail)
    elif failure == "missing_gateway":
        core.services.wms_reservations = None
    if failure in {"reserve", "render", "outbox"}:
        with pytest.raises(RuntimeError, match="Synthetic failure"):
            await create(api, ids, cmd)
    else:
        r = await create(api, ids, cmd)
        assert r.status_code == (503 if failure == "missing_gateway" else 409), r.text
    await no_issue(session)
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == 1


async def test_bound_org_and_actual_actor_permissions(api, session):
    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    api.headers["X-User"] = "foreign"
    assert (await create(api, ids, cmd)).status_code == 403
    api.headers["X-User"] = "issuer"
    api.headers["X-User-Roles"] = "guest"
    assert (await create(api, ids, cmd)).status_code == 403
    await no_issue(session)


async def test_receipt_not_marker_qualifies_source_and_terminal_never_fulfills(api, session):
    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    r = await create(api, ids, cmd)
    assert r.status_code == 201
    doc_id = r.json()["document"]["id"]
    source = SalesReservationSource()
    receipt = await session.get(InvoiceIssuanceReceipt, doc_id)
    receipt.actor = "forged"
    with pytest.raises(ValueError, match="immutable"):
        await session.flush()
    await session.rollback()
    await session.execute(update(InvoiceIssuanceReceipt).values(content_sha256="0" * 64))
    await session.commit()
    with pytest.raises(ValueError, match="receipt"):
        await source.invoice_reservation(session, doc_id)
    await session.rollback()
    await session.execute(
        update(InvoiceIssuanceReceipt).values(content_sha256=r.json()["content_sha256"])
    )
    await session.execute(
        update(DealDocument)
        .where(DealDocument.id == doc_id)
        .values(status="cancelled", reserve_status="released")
    )
    await session.commit()
    with pytest.raises(ValueError, match="terminal"):
        await source.invoice_shipping_source(
            session,
            doc_id,
            organization_id=ids["org"],
            expected_version=1,
            expected_content_sha256=r.json()["content_sha256"],
        )
    historical = await source.invoice_shipping_source(
        session,
        doc_id,
        organization_id=ids["org"],
        expected_version=1,
        expected_content_sha256=r.json()["content_sha256"],
        operation="historical_claim",
    )
    assert not historical["fulfillment_allowed"]


async def test_local_invoice_expiry_and_replacement_cannot_use_legacy_stock(api, session):
    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    r = await create(api, ids, cmd)
    assert r.status_code == 201
    doc_id = r.json()["document"]["id"]
    core = api._transport.app.state.core
    await tick_invoice_reserve(session, core.services)
    await session.commit()
    doc = await session.get(DealDocument, doc_id)
    assert doc.status == "issued" and doc.reserve_status == "reserved"
    revision = await api.post(
        f"/sales/documents/{doc_id}/revision",
        json={"reason": "New conditions", "request_key": "revision-erp-key"},
    )
    assert revision.status_code == 201, revision.text
    issued = await api.post(f"/sales/documents/{revision.json()['id']}/issue", json=cmd)
    assert issued.status_code == 409, issued.text
    assert (await session.get(DealDocument, doc_id)).superseded_by_id is None
    assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 1


async def test_issue_existing_first_draft_and_replay(api, session):
    ids, base = await seed(api, session)
    doc = DealDocument(deal_id=ids["deal"], kind="invoice", number="DRAFT", status="draft")
    session.add(doc)
    await session.commit()
    doc_id = doc.id
    cmd, _ = await command(api, ids, base, doc_id=doc_id)
    r = await api.post(f"/sales/documents/{doc_id}/issue", json=cmd)
    assert r.status_code == 200, r.text
    assert r.json()["document"]["id"] == doc_id
    again = await api.post(f"/sales/documents/{doc_id}/issue", json=cmd)
    assert again.status_code == 200 and again.json()["replayed"]
    assert (await api.post(f"/sales/documents/{doc_id}/issue")).status_code == 422


async def test_marker_without_persisted_receipt_is_never_authority(api, session):
    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    result = await create(api, ids, cmd)
    assert result.status_code == 201
    doc_id = result.json()["document"]["id"]
    # SQLite deliberately bypasses the ORM, simulating an incomplete restored DB.
    await session.execute(delete(InvoiceIssuanceReceipt))
    await session.commit()
    with pytest.raises(ValueError, match="persisted issuance receipt"):
        await SalesReservationSource().invoice_reservation(session, doc_id)


async def test_same_sku_lines_preserve_separate_allocation_matrix(api, session):
    ids, base = await seed(api, session)
    line = DealItem(deal_id=ids["deal"], sku_id=ids["sku"], qty=1)
    session.add(line)
    session.add(
        StockMovement(
            organization_id=ids["org"],
            sku_code=ids["code"],
            warehouse="SECOND",
            kind="in",
            qty=1,
            reason="receipt",
        )
    )
    await session.commit()
    base["pricing"].append({"item_id": line.id, "unit_price_net": "3.33", "vat_rate": "0.00"})
    cmd, _ = await command(api, ids, base)
    cmd["allocations"][1]["warehouse"] = "SECOND"
    result = await create(api, ids, cmd)
    assert result.status_code == 201, result.text
    event = await session.scalar(
        select(OutboxEvent).where(OutboxEvent.event_type == "sales.invoice.issued")
    )
    assert event.payload["amount"] == "243.33"
    assert {(r["line_no"], r["warehouse"], r["qty"]) for r in event.payload["items"]} == {
        (1, "W", "2.00"),
        (2, "SECOND", "1.00"),
    }
    doc_id = result.json()["document"]["id"]
    original = (await api.get(f"/sales/documents/{doc_id}/render")).content
    (await session.get(Counterparty, ids["buyer"])).name = "Later buyer"
    (await session.get(Sku, ids["sku"])).title = "Later goods"
    await session.commit()
    assert (await api.get(f"/sales/documents/{doc_id}/render")).content == original


async def test_parallel_file_sqlite_invoices_cannot_overissue(tmp_path):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from core.db.base import Base
    from core.runtime.app import create_app
    from core.runtime.deps import get_session
    from tests.conftest import SCHEMA_TRANSLATE
    from tests.integration.test_invoice_issuance_postgres import (
        test_pg_parallel_invoices_cannot_overissue_same_org_stock,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite:///" + (tmp_path / "parallel.db").as_posix(), connect_args={"timeout": 30}
    ).execution_options(schema_translate_map=SCHEMA_TRANSLATE)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()

    async def request_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = request_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-User": "issuer", "X-User-Roles": "director"},
        ) as client:
            # Reuse the identical assertion, with file SQLite and separate sessions.
            # No PostgreSQL fixture or connection is invoked here.
            await test_pg_parallel_invoices_cannot_overissue_same_org_stock((client, factory))
    finally:
        await engine.dispose()

@pytest.mark.parametrize("days_from_expiry,expected", [(-2, 0), (-1, 1), (2, 1)])
async def test_erp_expiry_reminder_preserves_invoice_and_reserve(api, session, monkeypatch, days_from_expiry, expected):
    from datetime import datetime, time, timedelta, timezone

    from core.domain.models import OutboxEvent

    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    result = await create(api, ids, cmd)
    assert result.status_code == 201, result.text
    doc = await session.get(DealDocument, result.json()["document"]["id"])
    original = doc.original_html
    moment = datetime.combine(doc.valid_until + timedelta(days=days_from_expiry), time(12), timezone.utc)
    monkeypatch.setattr("modules.sales.reserve._utcnow", lambda: moment)
    services = api._transport.app.state.core.services
    for _ in range(2):
        await tick_invoice_reserve(session, services)
        await session.commit()
    events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "sales.invoice.expiring"))).all()
    assert len(events) == expected
    await session.refresh(doc)
    assert doc.status == "issued" and doc.reserve_status == "reserved"
    assert doc.original_html == original
    if expected:
        event = events[0]
        assert event.payload["organization_id"] == ids["org"]
        assert event.payload["document_id"] == doc.id
        assert event.payload["content_sha256"] == result.json()["content_sha256"]
        assert event.payload["customer_notification"] == "requires_authorized_send"
        assert event.payload["expiry_state"] == ("review_required" if days_from_expiry > 0 else "expiring")
    assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 1

async def test_erp_expiry_reminder_rolls_back_with_outbox_failure(api, session, monkeypatch):
    from datetime import datetime, time, timezone

    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    result = await create(api, ids, cmd)
    doc_id = result.json()["document"]["id"]
    doc = await session.get(DealDocument, doc_id)
    moment = datetime.combine(doc.valid_until, time(12), timezone.utc)
    monkeypatch.setattr("modules.sales.reserve._utcnow", lambda: moment)
    services = api._transport.app.state.core.services
    original_emit = services.event_bus.emit
    def fail_emit(*args, **kwargs):
        raise RuntimeError("synthetic outbox failure")
    monkeypatch.setattr(services.event_bus, "emit", fail_emit)
    with pytest.raises(RuntimeError, match="synthetic outbox"):
        await tick_invoice_reserve(session, services)
    await session.rollback()
    await session.refresh(doc)
    assert doc.reminded_at is None
    assert doc.status == "issued" and doc.reserve_status == "reserved"
    monkeypatch.setattr(services.event_bus, "emit", original_emit)
    await tick_invoice_reserve(session, services)
    await session.commit()
    await session.refresh(doc)
    assert doc.reminded_at is not None


async def test_paid_erp_invoice_is_not_warned_or_cancelled(api, session, monkeypatch):
    from datetime import datetime, time, timedelta, timezone

    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    result = await create(api, ids, cmd)
    doc = await session.get(DealDocument, result.json()["document"]["id"])
    doc.status = "paid"
    await session.commit()
    moment = datetime.combine(doc.valid_until + timedelta(days=1), time(12), timezone.utc)
    monkeypatch.setattr("modules.sales.reserve._utcnow", lambda: moment)
    await tick_invoice_reserve(session, api._transport.app.state.core.services)
    await session.commit()
    await session.refresh(doc)
    assert doc.reminded_at is None
    assert doc.status == "paid" and doc.reserve_status == "reserved"
