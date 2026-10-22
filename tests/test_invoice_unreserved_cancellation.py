"""Registered-schema acceptance prerequisites for unreserved cancellation.

The original reserved-invoice oracles run unchanged on the registered schema.
Also exercises genuine unreserved cancellation without fabricated WMS records.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Column, Integer, MetaData, Table, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from core.runtime.app import create_app
from core.runtime.deps import get_session
from tests.accounting import test_postgres as pg_tests
from tests.accounting.test_postgres import pg_factory as pg_factory  # noqa: F401
from tests.test_invoice_cancellation import (
    test_pg_atomic_cancellation_and_deferred_package as _atomic_package,
)
from tests.test_invoice_cancellation import (
    test_pg_cancellation_package_rechecks_bank_written_after_application_review as _later_bank,
)
from tests.test_invoice_cancellation import (
    test_pg_cancellation_rejects_direct_status_and_incomplete_package as _incomplete_package,
)
from tests.test_invoice_cancellation import (
    test_pg_cancellation_rejects_malformed_saved_sections_even_with_faulty_verifier as _malformed_sections,
)
from tests.test_invoice_cancellation import (
    test_pg_cancellation_requires_actual_withdrawal_of_bound_targets as _actual_withdrawal,
)
from tests.test_invoice_cancellation import (
    test_pg_cancelled_invoice_replacement_preserves_original_and_new_reserve as _replacement,
)
from tests.test_invoice_cancellation import (
    test_pg_fulfillment_review_concurrent_replay_and_database_guards as _review_replay,
)


@pytest_asyncio.fixture
async def registered_api(pg_factory):  # noqa: F811
    app = create_app()
    app.state.core.services.db.session_factory = pg_factory

    async def sessions():
        async with pg_factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://isolated-test",
        headers={"X-User": "issuer", "X-User-Roles": "director"},
    ) as api:
        yield api, pg_factory


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_registered_review_replay_and_no_orm_repair(registered_api):
    await _review_replay(registered_api)
    _, factory = registered_api
    async with factory() as session:
        connection = await session.connection()
        forbidden = Table("forbidden_fixture_repair", MetaData(), Column("id", Integer), schema="public")
        with pytest.raises(AssertionError, match="must not repair schema"):
            await connection.run_sync(forbidden.create)
        await session.rollback()
        assert await session.scalar(text("SELECT to_regclass('public.forbidden_fixture_repair')")) is None


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_registered_replacement_preserves_original(registered_api):
    await _replacement(registered_api)


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
@pytest.mark.parametrize("paid_refunded", [False, True])
async def test_registered_atomic_package(registered_api, paid_refunded):
    await _atomic_package(registered_api, paid_refunded)


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_registered_rejects_incomplete_package(registered_api, monkeypatch):
    await _incomplete_package(registered_api, monkeypatch)


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
@pytest.mark.parametrize("correction", [False, True])
async def test_registered_rechecks_later_bank(registered_api, monkeypatch, correction):
    await _later_bank(registered_api, monkeypatch, correction)


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_registered_rejects_malformed_sections(registered_api, monkeypatch):
    await _malformed_sections(registered_api, monkeypatch)


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_registered_requires_actual_withdrawal(registered_api, monkeypatch):
    await _actual_withdrawal(registered_api, monkeypatch)


def _request(request):
    return SimpleNamespace(param="registered_head", getfixturevalue=request.getfixturevalue)


@pytest.mark.parametrize("target", [
    "postgresql+psycopg://remote.invalid/accounting_test",
    "postgresql+psycopg://127.0.0.1/not_a_test_database",
    "postgresql+psycopg:///accounting_test",
    "postgresql+psycopg://127.0.0.1/accounting_test?host=remote.invalid",
    "postgresql+psycopg://127.0.0.1/accounting_test?hostaddr=192.0.2.1",
    "postgresql+psycopg://127.0.0.1/accounting_test?service=unapproved",
    "postgresql+psycopg://127.0.0.1/accounting_test?dbname=not_a_test_database",
    "postgresql+asyncpg://127.0.0.1/accounting_test",
])
async def test_registered_refuses_foreign_target(monkeypatch, request, target):
    monkeypatch.setenv("ACCOUNTING_TEST_POSTGRES_URL", target)

    def no_engine(*args, **kwargs):
        raise AssertionError("A refused target must not create an engine")

    monkeypatch.setattr(pg_tests, "create_async_engine", no_engine)
    generator = pg_tests.pg_factory.__wrapped__(_request(request))
    try:
        with pytest.raises(pytest.fail.Exception, match="PostgreSQL target"):
            await anext(generator)
    finally:
        await generator.aclose()


async def test_registered_refuses_unpinned_head(monkeypatch, request):
    from alembic.script import ScriptDirectory

    monkeypatch.setenv("ACCOUNTING_TEST_POSTGRES_URL", "postgresql+psycopg://127.0.0.1/accounting_test")
    monkeypatch.setenv("REGISTERED_HEAD_TEST_OWNER", "0" * 32)
    monkeypatch.setattr(ScriptDirectory, "from_config", lambda config: SimpleNamespace(get_heads=lambda: ["unapproved"]))

    def no_engine(*args, **kwargs):
        raise AssertionError("An unpinned schema must not create an engine")

    monkeypatch.setattr(pg_tests, "create_async_engine", no_engine)
    generator = pg_tests.pg_factory.__wrapped__(_request(request))
    try:
        with pytest.raises(pytest.fail.Exception, match="pinned revision"):
            await anext(generator)
    finally:
        await generator.aclose()


async def _database_names(url, owner):
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database == "accounting_test"
    assert parsed.drivername == "postgresql+psycopg" and not parsed.query
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            marker = await connection.scalar(text(
                "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()"
            ))
            assert marker == f"crm-registered-head:{owner}"
            return set((await connection.scalars(text(
                "SELECT datname FROM pg_database WHERE datname LIKE 'acc_test_%'"
            ))).all())
    finally:
        await admin.dispose()


@pytest.mark.parametrize("failure", ["bootstrap", "master_owner"])
async def test_registered_failed_admission_leaves_no_database(monkeypatch, request, tmp_path, failure):
    url = os.getenv("ACCOUNTING_TEST_POSTGRES_URL")
    owner = os.getenv("REGISTERED_HEAD_TEST_OWNER")
    if not url or not owner:
        pytest.skip("Requires the isolated registered-head master")
    before = await _database_names(url, owner)
    if failure == "bootstrap":
        root = Path(pg_tests.__file__).resolve().parents[2]
        master = make_url(url)
        monkeypatch.setenv("ALEMBIC_CONFIG", "not-the-reviewed-config.ini")

        def failed_migration(argv, **kwargs):
            assert argv == [pg_tests.sys.executable, "-B", "-m", "alembic", "-c",
                            str(root / "alembic.ini"), "upgrade", "head"]
            assert kwargs["cwd"] == root
            child = make_url(kwargs["env"]["AIOS_DATABASE_URL"])
            assert child.database.startswith("acc_test_") and len(child.database) == 41
            assert all(c in "0123456789abcdef" for c in child.database[9:])
            assert child == master.set(database=child.database)
            assert kwargs["env"]["AIOS_ENVIRONMENT"] == "dev"
            assert kwargs["env"]["AIOS_AUTH_MODE"] == "dev"
            assert "ALEMBIC_CONFIG" not in kwargs["env"]
            return SimpleNamespace(returncode=1)

        monkeypatch.setattr(pg_tests.subprocess, "run", failed_migration)
        error, message = AssertionError, "Registered-head migration failed"
    else:
        monkeypatch.setenv("REGISTERED_HEAD_TEST_OWNER", uuid4().hex)
        error, message = pytest.fail.Exception, "master is not owned"
    generator = pg_tests.pg_factory.__wrapped__(_request(request))
    try:
        with pytest.raises(error, match=message):
            await anext(generator)
    finally:
        await generator.aclose()
    assert await _database_names(url, owner) == before


async def _issued_on_order(api, session):
    from modules.sales.models import DealDocument
    from tests.test_invoice_issuance import create, seed

    ids, base = await seed(api, session)
    base["reserve_mode"] = "on_order"
    preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()
    issued = await create(api, ids, {**base, "request_key": "unreserved-cancellation-source",
        "expected_document_version": prepared["document_version"],
        "expected_basis_digest": prepared["basis_digest"], "allocations": [], "unreserved_confirmed": True})
    assert issued.status_code == 201, issued.text
    session.expire_all()
    doc = await session.get(DealDocument, issued.json()["document"]["id"])
    return ids, doc


async def _cancellation_source(session, ids, doc, **changes):
    from modules.sales.reservation_source import SalesReservationSource

    exact = {"organization_id": ids["org"], "expected_version": doc.version,
             "expected_content_sha256": doc.content_sha256, **changes}
    return await SalesReservationSource().invoice_shipping_source(
        session, doc.id, operation="cancellation", **exact,
    )


@pytest.mark.parametrize("case", [
    "genuine_on_order", "foreign_organization", "wrong_version", "wrong_original_hash",
    "legacy_on_order", "marker_without_receipt", "corrupt_original", "corrupt_issuance_receipt",
    "stock_invoice_mislabelled_unreserved",
])
async def test_cancellation_source_exact_initial_on_order(api, session, case):
    from copy import deepcopy

    from sqlalchemy import delete, update

    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
    from modules.sales.models import DealDocument
    from modules.sales.reservation_source import SalesReservationSource
    from modules.wms.invoice_fulfillment import invoice_fulfillment_snapshot
    from modules.wms.invoice_reservations import _digest
    from tests.test_invoice_issuance import command, create, seed

    if case == "stock_invoice_mislabelled_unreserved":
        ids, base = await seed(api, session)
        body, _ = await command(api, ids, base)
        result = await create(api, ids, body)
        assert result.status_code == 201, result.text
        doc = await session.get(DealDocument, result.json()["document"]["id"])
        await session.execute(update(DealDocument).where(DealDocument.id == doc.id).values(reserve_status="unreserved"))
    else:
        ids, doc = await _issued_on_order(api, session)
    original = (doc.original_html, deepcopy(doc.snapshot_json), doc.content_sha256, doc.status, doc.reserve_status)
    changes = {}
    if case in {"legacy_on_order", "marker_without_receipt"}:
        await session.execute(delete(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc.id))
        if case == "legacy_on_order":
            snapshot = deepcopy(doc.snapshot_json)
            snapshot.pop("issuance_mode")
            await session.execute(update(DealDocument).where(DealDocument.id == doc.id)
                                  .values(status="posted", snapshot_json=snapshot))
    elif case == "corrupt_original":
        await session.execute(update(DealDocument).where(DealDocument.id == doc.id)
                              .values(original_html=doc.original_html + "corrupt"))
    elif case == "corrupt_issuance_receipt":
        receipt = await session.get(InvoiceIssuanceReceipt, doc.id)
        response = deepcopy(receipt.response)
        response["document"]["reserve_status"] = "reserved"
        await session.execute(update(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc.id)
                              .values(response=response))
    elif case == "foreign_organization":
        changes["organization_id"] = ids["org"] + 1
    elif case == "wrong_version":
        changes["expected_version"] = doc.version + 1
    elif case == "wrong_original_hash":
        changes["expected_content_sha256"] = "0" * 64
    await session.commit()
    if case != "genuine_on_order":
        with pytest.raises(ValueError):
            await _cancellation_source(session, ids, doc, **changes)
        return
    source = await _cancellation_source(session, ids, doc)
    assert source["reserve_status"] == "unreserved" and source["reservation_digest"] is None
    assert source["allocations"] == [] and source["fulfillment_allowed"] is False
    observed = await invoice_fulfillment_snapshot(session, ids["org"], source)
    assert observed["observed_state"] == "no_shipment" and observed["coverage_complete"] is False
    assert observed["snapshot"]["reservation"] is None and observed["snapshot"]["physical_basis"] is None
    assert observed["digest"] == _digest({k: v for k, v in observed.items() if k != "digest"})
    for operation in ["fulfill", "historical_claim"]:
        with pytest.raises(ValueError):
            await SalesReservationSource().invoice_shipping_source(session, doc.id, operation=operation,
                organization_id=ids["org"], expected_version=doc.version, expected_content_sha256=doc.content_sha256)
    await session.refresh(doc)
    assert (doc.original_html, doc.snapshot_json, doc.content_sha256, doc.status, doc.reserve_status) == original
    assert not session.new and not session.dirty and not session.deleted


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


@pytest.mark.parametrize("changed", ["issued_at", "issuance_anchor", "document_id"])
async def test_unreserved_prepared_source_binding(api, session, monkeypatch, changed):
    from datetime import timedelta

    from sqlalchemy import func, select

    from modules.sales import invoice_cancellation as cancellation

    ids, doc, _ = await _atomic_on_order(api, session)
    path, data = await _atomic_command(api, session, ids, doc)
    original = cancellation.prepare_fulfillment_verifier

    async def mutate_after_binding(db, services, org_id, basis, current, review_id, expected_digest):
        verifier = await original(db, services, org_id, basis, current, review_id, expected_digest)
        if changed == "issued_at":
            current["source"]["issued_at"] += timedelta(microseconds=1)
        elif changed == "issuance_anchor":
            current["source"]["issuance_receipt"] = {**current["source"]["issuance_receipt"], "request_key": "changed"}
        else:
            current["source"]["document_id"] += 1
        return verifier

    monkeypatch.setattr(cancellation, "prepare_fulfillment_verifier", mutate_after_binding)
    refused = await api.post(path, json=data)
    assert refused.status_code == 409, refused.text
    assert "original transaction and source" in refused.json()["detail"]
    await session.refresh(doc)
    assert (doc.status, doc.reserve_status) == ("issued", "unreserved")
    assert await session.scalar(select(func.count()).select_from(cancellation.InvoiceCancellationReceipt)) == 0


@pytest.mark.parametrize("case", ["no_receipts_unrelated_document_decoy", "fully_refunded",
    "on_order_later_reserved_uses_real_release", "replacement_after_no_stock_cancel",
    "owner_reader_same_deal_loss_finalize", "money_changed_after_cancel_blocks_loss"])
async def test_unreserved_atomic_workflow(api, session, case):
    from copy import deepcopy

    from sqlalchemy import func, select

    from core.domain.models import OutboxEvent, User
    from modules.accounting.models import AccessGrant, Policy
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
    from modules.sales.models import Deal, LossReason
    from modules.sales.reservation_source import SalesReservationSource
    from modules.wms.invoice_reservations import InvoiceReservationRelease
    from modules.wms.models import Task
    from tests.accounting.test_invoice_settlements import bank

    late = case == "on_order_later_reserved_uses_real_release"
    refunded = case in {"fully_refunded", "money_changed_after_cancel_blocks_loss"}
    ids, doc, base = await _atomic_on_order(api, session, refunded=refunded, later=late)
    original = (doc.original_html, deepcopy(doc.snapshot_json), doc.content_sha256, doc.version, doc.amount)
    child = None
    if case == "replacement_after_no_stock_cancel":
        revision = await api.post(f"/sales/documents/{doc.id}/revision", json={
            "reason": "Synthetic corrected invoice", "request_key": "atomic-replacement"})
        assert revision.status_code == 201, revision.text
        child = revision.json()["id"]
    if case == "no_receipts_unrelated_document_decoy":
        session.add(Task(organization_id=ids["org"], kind="pick", status="open", warehouse="W",
                         sku_code=ids["code"], qty=1, doc_ref="sales:document:999999"))
    loss = None
    if case == "owner_reader_same_deal_loss_finalize":
        # Human exception call_40659121: this isolated synthetic reader only.
        session.add_all([User(username="e2e_owner", full_name="Synthetic owner", role="sales", status="active",
                              employee_id=777, deal_visibility="own"),
                         AccessGrant(organization_id=ids["org"], subject="e2e_owner", role="reader"),
                         LossReason(code="atomic-price", title="Synthetic loss", active=True)])
        (await session.get(Deal, ids["deal"])).owner_id = 777
        await session.commit()
        api.headers.update({"X-User": "e2e_owner", "X-User-Roles": "sales", "X-Expected-Principal": "e2e_owner"})
        preview = await api.get(f"/sales/organizations/{ids['org']}/deals/{ids['deal']}/loss-preview")
        assert preview.status_code == 200, preview.text
        requested = await api.post(f"/sales/deals/{ids['deal']}/lose", json={"organization_id": ids["org"],
            "request_key": str(uuid4()), "reason_code": "atomic-price",
            "expected_composition_digest": preview.json()["composition_digest"]})
        assert requested.status_code == 200, requested.text
        loss = requested.json()
        api.headers.update({"X-User": "issuer", "X-User-Roles": "director", "X-Expected-Principal": "issuer"})
    path, data = await _atomic_command(api, session, ids, doc)
    response = await api.post(path, json=data)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["release_id"] is not None if late else result["release_id"] is None
    assert result["reserve_status"] == ("released" if late else "unreserved")
    assert ("stock_outcome" not in result) if late else result["stock_outcome"] == "no_stock_release"
    await session.refresh(doc)
    assert (doc.original_html, doc.snapshot_json, doc.content_sha256, doc.version, doc.amount) == original
    assert doc.status == "cancelled"
    assert await session.scalar(select(func.count()).select_from(InvoiceCancellationReceipt)) == 1
    assert await session.scalar(select(func.count()).select_from(InvoiceReservationRelease)) == int(late)
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.event_type == "sales.invoice.cancelled")) == 1
    if not late:
        await _assert_no_warehouse_changes(session, doc.id)
        row = await session.get(InvoiceCancellationReceipt, result["cancellation_id"])
        assert "release" not in row.snapshot
        assert row.snapshot["no_stock_release"]["issuance_receipt"]["document_id"] == doc.id
    if child is not None:
        preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json={**base, "document_id": child})
        assert preview.status_code == 200, preview.text
        p = preview.json()
        replacement = await api.post(f"/sales/documents/{child}/issue", json={**base,
            "organization_id": ids["org"], "request_key": "atomic-replacement-issue",
            "expected_document_version": p["document_version"], "expected_basis_digest": p["basis_digest"],
            "allocations": [], "unreserved_confirmed": True})
        assert replacement.status_code == 200, replacement.text
        lifecycle = await SalesReservationSource().invoice_financial_lifecycle(
            session, child, organization_id=ids["org"], expected_version=2,
            expected_content_sha256=replacement.json()["document"]["content_sha256"])
        assert lifecycle["predecessor"]["cancellation"]["release_id"] is None
    if loss is not None:
        api.headers.update({"X-User": "e2e_owner", "X-User-Roles": "sales", "X-Expected-Principal": "e2e_owner"})
        finished = await api.post(f"/sales/organizations/{ids['org']}/deals/{ids['deal']}/loss-requests/{loss['request_id']}/finalize",
            json={"request_key": str(uuid4()), "expected_request_digest": loss["request_digest"],
                  "evidence": "Synthetic owner closes the same reconciled invoice"})
        assert finished.status_code == 200, finished.text
        assert finished.json()["action"] == "finalized"
        assert finished.json()["snapshot"]["invoices"][0]["cancellation_receipt"]["cancellation_id"] == result["cancellation_id"]
        await session.refresh(await session.get(Deal, ids["deal"]))
        assert (await session.get(Deal, ids["deal"])).stage == "lost"
        await session.refresh(doc)
        assert doc.reserve_status == "unreserved"
    if case == "money_changed_after_cancel_blocks_loss":
        policy = await session.scalar(select(Policy))
        await bank(api, (ids["org"], policy.id), doc.id, "atomic-later-bank", amount="20.00")
        observed = await api.get(f"/sales/organizations/{ids['org']}/deals/{ids['deal']}/loss-preview")
        assert observed.status_code == 200, observed.text
        progress = next(row for row in observed.json()["invoices"] if row["document_id"] == doc.id)
        assert progress["ready"] is False and progress["blockers"]


@pytest.mark.parametrize("case", ["lost_response_exact_command", "exact_replay_no_extra_effects",
    "changed_body_same_key", "different_key_same_invoice", "revoked_chief", "foreign_organization",
    "foreign_deal_owner", "mixed_or_corrupt_saved_outcome"])
async def test_unreserved_atomic_replay_access(api, session, case):
    from copy import deepcopy

    from sqlalchemy import delete, func, select, update

    from core.domain.models import OutboxEvent, User
    from modules.accounting.models import AccessGrant
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt, cancellation_digest
    from modules.sales.models import Deal

    ids, doc, _ = await _atomic_on_order(api, session)
    path, data = await _atomic_command(api, session, ids, doc)
    saved_body = deepcopy(data)
    response = await api.post(path, json=data)
    assert response.status_code == 201, response.text
    first = response.json()
    expected = 201
    if case == "changed_body_same_key":
        data = {**data, "evidence": "Different evidence"}
        expected = 409
    elif case == "different_key_same_invoice":
        data = {**data, "request_key": str(uuid4())}
        expected = 409
    elif case == "revoked_chief":
        await session.execute(delete(AccessGrant).where(AccessGrant.subject == "issuer"))
        await session.commit()
        expected = 403
    elif case == "foreign_organization":
        path = path.replace(f"/organizations/{ids['org']}/", f"/organizations/{ids['org']+100}/")
        expected = 403
    elif case == "foreign_deal_owner":
        session.add(User(username="issuer", full_name="Synthetic chief", role="sales", status="active",
                         employee_id=777, deal_visibility="own"))
        (await session.get(Deal, ids["deal"])).owner_id = 888
        await session.commit()
        api.headers["X-User-Roles"] = "sales"
        expected = 404
    elif case == "mixed_or_corrupt_saved_outcome":
        row = await session.get(InvoiceCancellationReceipt, first["cancellation_id"])
        bad = deepcopy(row.snapshot)
        bad["release"] = None
        values = dict(row.__dict__)
        values.pop("_sa_instance_state", None)
        forged = SimpleNamespace(**{**values, "snapshot": bad})
        await session.execute(update(InvoiceCancellationReceipt).where(InvoiceCancellationReceipt.id == row.id)
            .values(snapshot=bad, digest=cancellation_digest(forged)).execution_options(synchronize_session=False))
        await session.commit()
        expected = 409
    if case == "lost_response_exact_command":
        # The response is deliberately discarded; only the saved command is retried.
        data = saved_body
    repeated = await api.post(path, json=data)
    assert repeated.status_code == expected, repeated.text
    if expected == 201:
        assert repeated.json() == first
    assert await session.scalar(select(func.count()).select_from(InvoiceCancellationReceipt)) == 1
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.event_type == "sales.invoice.cancelled")) == 1
    await _assert_no_warehouse_changes(session, first["document_id"])


@pytest.mark.parametrize("boundary", ["after_withdrawal", "after_receipt", "outbox"])
async def test_unreserved_atomic_rollback(api, session, monkeypatch, boundary):
    from fastapi import HTTPException
    from sqlalchemy import event, func, select

    from core.domain.models import OutboxEvent
    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt

    ids, doc, _ = await _atomic_on_order(api, session)
    # A genuine unreserved invoice cannot acquire shipment bindings through the
    # fulfillment API. Exercise its real empty withdrawal, never fabricate plans.
    path, data = await _atomic_command(api, session, ids, doc)
    core = api._transport.app.state.core
    if boundary == "after_withdrawal":
        original = core.services.logistics.withdraw_unexecuted_invoice

        async def fail(*args, **kwargs):
            await original(*args, **kwargs)
            raise HTTPException(409, "Synthetic fault after withdrawal")

        monkeypatch.setattr(core.services.logistics, "withdraw_unexecuted_invoice", fail)
    elif boundary == "after_receipt":
        def after_insert(*args):
            raise HTTPException(409, "Synthetic fault after receipt")

        event.listen(InvoiceCancellationReceipt, "after_insert", after_insert)
    else:
        original = core.event_bus.emit

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise HTTPException(409, "Synthetic fault after outbox")

        monkeypatch.setattr(core.event_bus, "emit", fail)
    try:
        failed = await api.post(path, json=data)
        assert failed.status_code == 409, failed.text
    finally:
        if boundary == "after_receipt":
            event.remove(InvoiceCancellationReceipt, "after_insert", after_insert)
    await session.rollback()
    await session.refresh(doc)
    assert (doc.status, doc.reserve_status) == ("issued", "unreserved")
    for model in (InvoiceCancellationReceipt,):
        assert await session.scalar(select(func.count()).select_from(model)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.event_type == "sales.invoice.cancelled")) == 0
    from modules.logistics.models import CarrierRfq, Shipment

    assert await session.scalar(select(func.count()).select_from(Shipment)) == 0
    assert await session.scalar(select(func.count()).select_from(CarrierRfq)) == 0
    await _assert_no_warehouse_changes(session, doc.id)


async def test_cancellation_source_refuses_orphan_late_receipt(api, session):
    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt, InvoiceLateReservationReceipt

    ids, doc = await _issued_on_order(api, session)
    initial = await session.get(InvoiceIssuanceReceipt, doc.id)
    session.add(InvoiceLateReservationReceipt(document_id=doc.id, organization_id=ids["org"],
        document_version=doc.version, content_sha256=doc.content_sha256,
        issuance_snapshot_digest=initial.snapshot_digest, request_key="orphan-late", request_hash="a" * 64,
        reservation_digest="", response={}, actor="issuer"))
    await session.commit()
    with pytest.raises(ValueError, match="genuine unreserved"):
        await _cancellation_source(session, ids, doc)


@pytest.mark.parametrize("corruption", ["float_id", "bool_version", "status", "kind"])
async def test_cancellation_source_refuses_initial_response_type_confusion(api, session, corruption):
    from copy import deepcopy

    from sqlalchemy import update

    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt

    ids, doc = await _issued_on_order(api, session)
    receipt = await session.get(InvoiceIssuanceReceipt, doc.id)
    response = deepcopy(receipt.response)
    if corruption == "float_id":
        response["organization_id"] = float(response["organization_id"])
        response["document"]["id"] = float(response["document"]["id"])
    elif corruption == "bool_version":
        assert response["document_version"] == response["document"]["version"] == 1
        response["document_version"] = response["document"]["version"] = True
    elif corruption == "status":
        response["document"]["status"] = "cancelled"
    else:
        response["document"]["kind"] = "contract"
    await session.execute(update(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc.id)
                          .values(response=response))
    await session.commit()
    with pytest.raises(ValueError, match="Initial unreserved issuance response"):
        await _cancellation_source(session, ids, doc)


@pytest.mark.parametrize("kind", ["legacy_stock", "later_reserved_on_order"])
async def test_cancellation_source_preserves_reserved_history(api, session, kind):
    from copy import deepcopy
    from datetime import date, timedelta

    from sqlalchemy import delete, update

    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
    from modules.sales.models import DealDocument
    from modules.sales.reservation_source import SalesReservationSource
    from tests.test_invoice_issuance import command, create, seed

    if kind == "later_reserved_on_order":
        ids, base = await seed(api, session)
        base.update(reserve_mode="on_order", valid_until=(date.today() + timedelta(days=5)).isoformat())
        preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
        assert preview.status_code == 200, preview.text
        facts = preview.json()
        issued = await create(api, ids, {**base, "request_key": "compat-initial-on-order",
            "expected_document_version": facts["document_version"], "expected_basis_digest": facts["basis_digest"],
            "allocations": [], "unreserved_confirmed": True})
        assert issued.status_code == 201, issued.text
        doc = await session.get(DealDocument, issued.json()["document"]["id"])
        original = (doc.original_html, deepcopy(doc.snapshot_json), doc.content_sha256)
        reserved = await api.post(f"/sales/deals/{ids['deal']}/documents/{doc.id}/reservation", json={
            "organization_id": ids["org"], "request_key": "compat-later-reserve", "expected_document_version": doc.version,
            "expected_content_sha256": doc.content_sha256, "allocations": [{"line_no": 1, "warehouse": "W", "qty": "2.00"}],
            "evidence": "Confirmed synthetic stock and complete journal", "journal_complete": True})
        assert reserved.status_code == 201, reserved.text
        await session.refresh(doc)
        assert (doc.original_html, doc.snapshot_json, doc.content_sha256) == original
        assert doc.reserve_mode == "on_order" and doc.reserve_status == "reserved"
    else:
        ids, base = await seed(api, session)
        body, _ = await command(api, ids, base)
        result = await create(api, ids, body)
        assert result.status_code == 201, result.text
        doc = await session.get(DealDocument, result.json()["document"]["id"])
        snapshot = deepcopy(doc.snapshot_json)
        snapshot.pop("issuance_mode")
        await session.execute(delete(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc.id))
        await session.execute(update(DealDocument).where(DealDocument.id == doc.id)
                              .values(status="posted", snapshot_json=snapshot))
        await session.commit()
    expected = await SalesReservationSource().invoice_shipping_source(session, doc.id,
        organization_id=ids["org"], expected_version=doc.version,
        expected_content_sha256=doc.content_sha256, operation="historical_claim")
    assert await _cancellation_source(session, ids, doc) == expected
    assert expected["reserve_status"] == "reserved" and expected["fulfillment_allowed"] is False


@pytest.mark.parametrize("trace", [
    "reservation", "versions", "event_state", "pick_links", "picks", "acts", "releases", "movements",
])
async def test_unreserved_wms_rejects_each_addressed_trace(api, session, trace):
    from datetime import date
    from decimal import Decimal

    from fastapi import HTTPException
    from sqlalchemy import func, select

    from modules.wms.invoice_fulfillment import invoice_fulfillment_snapshot
    from modules.wms.invoice_reservations import InvoiceReservation, InvoiceReservationRelease
    from modules.wms.invoice_shipments import PhysicalShipmentAct
    from modules.wms.models import ReservationVersion, StockMovement, Task
    from modules.wms.reservation_events import ReservationEventState, ReservationPick

    ids, doc = await _issued_on_order(api, session)
    source = await _cancellation_source(session, ids, doc)
    # Deliberately foreign/orphaned synthetic records prove each independent
    # boundary. They are not fabricated evidence for a successful cancellation.
    foreign = ids["org"] + 100
    rows = {
        "reservation": lambda: InvoiceReservation(document_id=doc.id, organization_id=foreign,
            digest="a" * 64, snapshot={}, actor="issuer"),
        "versions": lambda: ReservationVersion(organization_id=foreign, source=f"invoice:{doc.id}:1:orphan",
            version=1, sku_code=ids["code"], warehouse="W", qty=Decimal("0"), evidence="Synthetic orphan", actor="issuer"),
        "event_state": lambda: ReservationEventState(document_id=doc.id, state="released", quantities={}, reserved_items=[]),
        "pick_links": lambda: ReservationPick(document_id=doc.id, task_id=999),
        "picks": lambda: Task(organization_id=foreign, kind="pick", sku_code=ids["code"],
            warehouse="W", qty=Decimal("1"), doc_ref=f"sales:document:{doc.id}", status="canceled"),
        "acts": lambda: PhysicalShipmentAct(organization_id=foreign, document_id=doc.id, document_version=1,
            content_sha256=doc.content_sha256, reservation_digest="a" * 64, source_key=str(uuid4()),
            request_hash="b" * 64, operation_date=date(2026, 9, 1), actor="issuer", snapshot={}, digest="c" * 64),
        "releases": lambda: InvoiceReservationRelease(document_id=doc.id, organization_id=foreign,
            source_key="orphan-release", request_hash="b" * 64, digest="c" * 64, snapshot={}, actor="issuer"),
        "movements": lambda: StockMovement(organization_id=foreign, sku_code=ids["code"], warehouse="W",
            kind="out", qty=Decimal("1"), reason="shipment", doc_ref=f"sales:document:{doc.id}"),
    }
    session.add(rows[trace]())
    await session.commit()
    models = (InvoiceReservation, ReservationVersion, ReservationEventState, ReservationPick,
              Task, PhysicalShipmentAct, InvoiceReservationRelease, StockMovement)
    before = [await session.scalar(select(func.count()).select_from(model)) for model in models]
    with pytest.raises(HTTPException) as refused:
        await invoice_fulfillment_snapshot(session, ids["org"], source)
    assert refused.value.status_code == 409
    assert refused.value.detail == {"code": "unreserved_invoice_has_wms_history", "scope": trace}
    assert before == [await session.scalar(select(func.count()).select_from(model)) for model in models]
    assert not session.new and not session.dirty and not session.deleted


async def _registered_revision(factory, tmp_path, action, revision, *, succeeds=True, refusal="no_stock"):
    """Real CLI on this fixture's marked child database, never its master."""
    import asyncio
    import re
    import subprocess
    import sys

    engine = factory.kw["bind"]
    url = engine.url
    assert url.drivername == "postgresql+psycopg" and url.host in {"127.0.0.1", "localhost"} and not url.query
    assert re.fullmatch(r"acc_test_[a-f0-9]{32}", url.database or "")
    assert (action, revision) in {("downgrade", "0196"), ("downgrade", "0197"), ("upgrade", "0197"), ("upgrade", "0198")}
    async with factory() as session:
        assert await session.scalar(text("SELECT current_database()")) == url.database
        assert 160000 <= int(await session.scalar(text("SHOW server_version_num"))) < 170000
        assert await session.scalar(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()")) == f"crm-acc-fixture:{url.database}"
        before = await session.scalar(text("SELECT version_num FROM alembic_version"))
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, AIOS_ENVIRONMENT="dev", AIOS_AUTH_MODE="dev", AIOS_DATABASE_URL=url.render_as_string(hide_password=False))
    env.pop("ALEMBIC_CONFIG", None)
    log_path = tmp_path / (action + "-" + uuid4().hex + ".private.log")
    with log_path.open("xb") as log:
        result = await asyncio.to_thread(subprocess.run, [sys.executable, "-B", "-m", "alembic", "-c",
            str(root / "alembic.ini"), action, revision], cwd=root, env=env,
            stdout=log, stderr=subprocess.STDOUT, timeout=150)
    assert (result.returncode == 0) is succeeds, "Isolated migration CLI result mismatch; private log retained"
    if not succeeds:
        patterns = {
            "no_stock": r"(?:psycopg\.errors\.RaiseException:|\(psycopg\.errors\.RaiseException\))\s+No-stock cancellation history prevents downgrade",
            "approval_evidence": r"RuntimeError: Durable approval evidence cannot be discarded; use the verified release restore",
            "approval_partial": r"RuntimeError: Unexpected durable approval columns; inspect the migration baseline",
        }
        assert re.search(patterns[refusal], log_path.read_text(encoding="utf-8", errors="replace")), (
            "CLI must refuse the exact known guard, not an unrelated SQL or runtime failure")
    async with factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == (revision if succeeds else before)


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


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
@pytest.mark.parametrize("fault", ["missing_tag", "null_release_reserved_tag", "release_present_no_stock_tag",
    "changed_original", "missing_fulfillment_review", "missing_withdrawal_package", "wrong_identity",
    "schema_float", "schema_string", "schema_bool", "schema_null"])
async def test_registered_no_stock_raw_sql_guards(registered_api, fault):
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


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
@pytest.mark.parametrize("number", [1e-06, -0.0], ids=["exponent", "negative_zero"])
async def test_registered_original_json_parity(registered_api, number):
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


async def _registered_package_state(factory):
    """Read the actual related rows/constraints/guard definitions, no DDL."""
    state = {}
    tables = ("approval", "sales.deal_document", "sales.invoice_issuance_receipt", "sales.invoice_cancellation_receipt",
              "sales.invoice_fulfillment_review", "sales.invoice_money_reconciliation",
              "wms.invoice_reservation_release", "wms.invoice_reservation_release_line")
    async with factory() as session:
        for table in tables:
            state[table] = (await session.execute(text(f"SELECT row_to_json(t)::text FROM {table} t ORDER BY row_to_json(t)::text"))).scalars().all()
        state["approval_columns"] = (await session.execute(text("""SELECT column_name,data_type,is_nullable
            FROM information_schema.columns WHERE table_schema='public' AND table_name='approval'
            ORDER BY ordinal_position"""))).all()
        state["guards"] = dict((await session.execute(text("""SELECT p.proname,p.prosrc FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='sales' AND p.proname IN
            ('check_cancellation_package','check_loss_cancelled_invoice','check_no_stock_cancellation','invoice_original_json')
            ORDER BY p.proname"""))).all())
        state["constraints"] = (await session.execute(text("""SELECT conname,pg_get_constraintdef(oid),convalidated
            FROM pg_constraint WHERE conrelid='sales.invoice_cancellation_receipt'::regclass ORDER BY conname"""))).all()
        state["nullable"] = await session.scalar(text("SELECT is_nullable FROM information_schema.columns WHERE table_schema='sales' AND table_name='invoice_cancellation_receipt' AND column_name='release_id'"))
    return state


async def _registered_cancel_replay(api, factory):
    from copy import deepcopy

    from sqlalchemy import select

    from modules.sales.invoice_cancellation import InvoiceCancellationReceipt

    async with factory() as session:
        row = await session.scalar(select(InvoiceCancellationReceipt))
        org, doc_id, body = row.organization_id, row.document_id, deepcopy(row.request)
    response = await api.post(f"/sales/organizations/{org}/invoices/{doc_id}/cancel", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["release_id"] > 0 and "stock_outcome" not in response.json()
    return response.json()


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
@pytest.mark.parametrize("case", [
    "populated_0197", "downgrade_before_history", "downgrade_refuses_new_history",
    "approval_request_payload_prevents_0197_downgrade",
    "approval_request_sha256_prevents_0197_downgrade",
    "approval_applied_receipt_prevents_0197_downgrade",
    "partial_approval_column_prevents_0197_upgrade",
])
async def test_registered_no_stock_migration(registered_api, tmp_path, case):
    import ast
    import re

    api, factory = registered_api
    if case.startswith("approval_") or case == "partial_approval_column_prevents_0197_upgrade":
        from core.domain.models import Approval

        await _registered_revision(factory, tmp_path, "downgrade", "0197")
        if case == "partial_approval_column_prevents_0197_upgrade":
            await _registered_revision(factory, tmp_path, "downgrade", "0196")
        async with factory() as session:
            legacy = Approval(kind="synthetic", entity_ref="synthetic:1", subject="Migration guard fixture",
                              route="director", requested_by="synthetic")
            session.add(legacy)
            await session.commit()
            if case == "partial_approval_column_prevents_0197_upgrade":
                await session.execute(text("ALTER TABLE approval ADD COLUMN request_payload JSON NULL"))
            else:
                field = {
                    "approval_request_payload_prevents_0197_downgrade": "request_payload",
                    "approval_request_sha256_prevents_0197_downgrade": "request_sha256",
                    "approval_applied_receipt_prevents_0197_downgrade": "applied_receipt",
                }[case]
                value = "'" + "a" * 64 + "'" if field == "request_sha256" else "'{}'::json"
                await session.execute(text(f"UPDATE approval SET {field}={value} WHERE id=:id"), {"id": legacy.id})
            await session.commit()
        before = await _registered_package_state(factory)
        partial = case == "partial_approval_column_prevents_0197_upgrade"
        await _registered_revision(factory, tmp_path, "upgrade" if partial else "downgrade",
                                   "0197" if partial else "0196", succeeds=False,
                                   refusal="approval_partial" if partial else "approval_evidence")
        assert await _registered_package_state(factory) == before
        return
    if case == "downgrade_refuses_new_history":
        async with factory() as session:
            ids, doc, _ = await _atomic_on_order(api, session)
            path, data = await _atomic_command(api, session, ids, doc)
        result = await api.post(path, json=data)
        assert result.status_code == 201, result.text
        before = await _registered_package_state(factory)
        await _registered_revision(factory, tmp_path, "downgrade", "0197", succeeds=False)
        assert await _registered_package_state(factory) == before
        return
    await _registered_revision(factory, tmp_path, "downgrade", "0197")
    restored = await _registered_package_state(factory)
    assert restored["nullable"] == "NO"
    assert not any(row[0] == "invoice_cancellation_stock_outcome" for row in restored["constraints"])
    migration = Path(__file__).resolve().parents[1] / "migrations/versions/0198_invoice_no_stock_cancellation.py"
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    frozen = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "DOWNGRADE_FUNCTIONS" for t in n.targets))
    expected_guards = dict(re.findall(r"CREATE OR REPLACE FUNCTION sales\.(\w+)\([^$]+?AS \$\$(.*?)\$\$;", frozen, re.S))
    assert set(expected_guards) == {"check_cancellation_package", "check_loss_cancelled_invoice"}
    assert restored["guards"] == expected_guards
    # Exercise the entire registered chain with a genuine pre-0197 approval.
    from core.domain.models import Approval

    await _registered_revision(factory, tmp_path, "downgrade", "0196")
    async with factory() as session:
        legacy = Approval(kind="synthetic", entity_ref="synthetic:1", subject="Legacy approval preserved",
                          route="director", requested_by="synthetic")
        session.add(legacy)
        await session.commit()
    legacy_196 = await _registered_package_state(factory)
    before, old_response = None, None
    if case == "populated_0197":
        # The package predates both migrations, not merely 0198.
        await _atomic_package(registered_api, False)
        before = await _registered_package_state(factory)
        old_response = await _registered_cancel_replay(api, factory)
        assert before["sales.invoice_cancellation_receipt"] and before["wms.invoice_reservation_release"]
    source_196 = await _registered_package_state(factory)
    await _registered_revision(factory, tmp_path, "upgrade", "0197")
    approval_fields = {"request_payload", "request_sha256", "applied_receipt"}

    def legacy_approval_rows(state):
        import json

        return [{k: v for k, v in json.loads(row).items() if k not in approval_fields}
                for row in state["approval"]]

    upgraded_197 = await _registered_package_state(factory)
    assert legacy_approval_rows(upgraded_197) == legacy_approval_rows(legacy_196)
    assert {row[0] for row in upgraded_197["approval_columns"]} == {
        row[0] for row in legacy_196["approval_columns"]} | approval_fields
    assert {k: v for k, v in upgraded_197.items() if k not in {"approval", "approval_columns"}} == {
        k: v for k, v in source_196.items() if k not in {"approval", "approval_columns"}}
    if old_response is not None:
        before = upgraded_197
        assert await _registered_cancel_replay(api, factory) == old_response
    await _registered_revision(factory, tmp_path, "upgrade", "0198")
    after = await _registered_package_state(factory)
    assert after["nullable"] == "YES"
    if before is not None:
        assert {k: v for k, v in after.items() if k not in {"guards", "constraints", "nullable"}} == {
            k: v for k, v in before.items() if k not in {"guards", "constraints", "nullable"}}
        assert await _registered_cancel_replay(api, factory) == old_response
    await _registered_revision(factory, tmp_path, "downgrade", "0197")
    rolled_197 = await _registered_package_state(factory)
    assert rolled_197["nullable"] == "NO" and rolled_197["guards"] == expected_guards
    assert {k: v for k, v in rolled_197.items() if k not in {"guards", "constraints", "nullable"}} == {
        k: v for k, v in after.items() if k not in {"guards", "constraints", "nullable"}}
    assert rolled_197 == upgraded_197
    if old_response is not None:
        assert await _registered_cancel_replay(api, factory) == old_response
    await _registered_revision(factory, tmp_path, "downgrade", "0196")
    rolled_196 = await _registered_package_state(factory)
    assert rolled_196["approval_columns"] == legacy_196["approval_columns"]
    assert legacy_approval_rows(rolled_196) == legacy_approval_rows(legacy_196)
    assert {k: v for k, v in rolled_196.items() if k not in {"approval", "approval_columns"}} == {
        k: v for k, v in rolled_197.items() if k not in {"approval", "approval_columns"}}
    if old_response is not None:
        assert await _registered_cancel_replay(api, factory) == old_response


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
@pytest.mark.parametrize("case", ["late_reserve_against_cancel", "two_cancellations",
                                "money_after_review_before_commit", "fulfillment_after_review_before_commit"])
async def test_registered_no_stock_races(registered_api, monkeypatch, case):
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

