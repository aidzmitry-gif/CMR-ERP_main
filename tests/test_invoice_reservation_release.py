"""Synthetic addressed release tests. PostgreSQL requires an explicit local URL."""
import asyncio
import copy
import hashlib
import json
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import JSON, Integer, String, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.db.base import Base
from modules.accounting.models import Organization
from modules.accounting.service import lock_organization
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.deal_loss import DealLossRequest, DealLossResolution
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
from modules.sales.models import Deal, DealDocument, Stage
from modules.sales.reservation_source import SalesReservationSource
from modules.wms.invoice_remainder import RemainderRelease, RemainderReleaseLine
from modules.wms.invoice_reservations import (
    EvidenceReference,
    InvoiceReservation,
    InvoiceReservationRelease,
    InvoiceReservationReleaseLine,
    ReleaseInput,
    ReserveInput,
    VerifiedNoShipment,
    no_shipment_review_digest,
    release,
    release_preview,
    reserve,
)
from modules.wms.invoice_reservations import _digest as package_digest
from modules.wms.invoice_shipments import PhysicalShipmentAct, PhysicalShipmentLine
from modules.wms.models import Location, ReservationVersion, StockMovement, Task
from modules.wms.reservation_events import ReservationEventState, ReservationPick, apply


class ProofBase(DeclarativeBase):
    pass


class Proof(ProofBase):
    """TEST-ONLY server-side reference registry, not a production table proposal."""
    __tablename__ = "release_test_proof"
    __table_args__ = {"schema": "wms"}
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    org: Mapped[int] = mapped_column(Integer)
    doc: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)


SCOPES = ("wms_issue", "wms_pick", "logistics_shipment", "accounting_issue", "legacy_fulfillment")
TABLES = [m.__table__ for m in (Organization, Deal, DealDocument, Stage, DealLossRequest, DealLossResolution,
    InvoiceIssuanceReceipt, DealOwnership, Location,
    StockMovement, Task, ReservationVersion, InvoiceReservation, ReservationEventState,
    ReservationPick, InvoiceReservationRelease, InvoiceReservationReleaseLine, PhysicalShipmentAct, PhysicalShipmentLine, RemainderRelease, RemainderReleaseLine, Proof)]


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class RegistryVerifier:
    """Test adapter actually dereferences stored scope records, not a boolean stub."""
    async def review(self, session, org, source):
        refs = []
        for scope in SCOPES:
            key = f"{source['document_id']}:{scope}"
            row = await session.scalar(select(Proof).where(Proof.key == key)
                .execution_options(populate_existing=True))
            if (row is None or row.org != org or row.doc != source["document_id"]
                    or row.content.get("decision") != "no_shipment"
                    or row.content.get("coverage") != "complete"
                    or row.content.get("observed_issue_ids") != []):
                raise HTTPException(409, "fulfillment_reference_unresolved")
            refs.append(EvidenceReference(scope, key, "1", digest(row.content)))
        reservation = await session.get(InvoiceReservation, source["document_id"])
        review = VerifiedNoShipment(org, source["document_id"], source["version"],
            source["content_sha256"], reservation.digest, f"review:{source['document_id']}", "",
            "synthetic-authorized-reviewer", tuple(refs))
        return replace(review, review_digest=no_shipment_review_digest(review))

    async def verify_no_shipment(self, session, org, source, review_id, expected_review_digest):
        review = await self.review(session, org, source)
        if (review.review_id, review.review_digest) != (review_id, expected_review_digest):
            raise HTTPException(409, "fulfillment_reference_changed")
        return review


@asynccontextmanager
async def database(postgres=False):
    admin = None
    if postgres:
        raw = os.getenv("RELEASE_TEST_POSTGRES_URL") or os.getenv("ACCOUNTING_TEST_POSTGRES_URL")
        if not raw:
            pytest.skip("Explicit isolated PostgreSQL URL required")
        url = make_url(raw)
        if url.host != "127.0.0.1" or url.port != 15436 or url.database != "accounting_test":
            pytest.fail("Refusing any target other than 127.0.0.1:15436/accounting_test")
        name = "acc_release_" + uuid4().hex
        admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_async_engine(url.set(database=name))
    else:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", execution_options={
            "schema_translate_map": {"wms": None, "sales": None, "accounting": None}})

        @event.listens_for(engine.sync_engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
    try:
        async with engine.begin() as conn:
            if postgres:
                for schema in ("wms", "sales", "accounting"):
                    await conn.execute(text(f"CREATE SCHEMA {schema}"))
            selected = TABLES if not postgres else [table for table in TABLES if table.name not in {
                "invoice_reservation_release", "invoice_reservation_release_line"}]
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=selected))
            if postgres:
                checkout = Path(__file__).resolve().parents[1]
                for path in (checkout / "docs/accounting/release-tables-proposal.sql",
                             checkout / "modules/wms/reservation_guards.sql",
                             checkout / "modules/wms/invoice_reservation_release_guards.sql"):
                    await conn.execute(text(path.read_text(encoding="utf-8")))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        if admin is not None:
            # Only this fixture's freshly generated DB, after closing its sessions.
            async with admin.connect() as conn:
                await conn.execute(text(f'DROP DATABASE "{name}"'))
            await admin.dispose()


@pytest_asyncio.fixture
async def factory():
    async with database() as factory:
        yield factory


async def source_lock(session, doc=1):
    await lock_organization(session, 1)
    return await SalesReservationSource().invoice_reservation(session, doc)


async def seed(factory, picks=True):
    async with factory() as session:
        session.add(Organization(id=1, name="Synthetic", unp="999999971"))
        await session.flush()
        for doc_id in (1, 2):
            session.add(Deal(id=doc_id, number=f"SYN-{doc_id}", title="Synthetic", counterparty="Synthetic"))
        await session.flush()
        for doc_id in (1, 2):
            html = f"<p>Synthetic original {doc_id}</p>"
            session.add(DealDocument(id=doc_id, deal_id=doc_id, number=f"SYN-{doc_id}", kind="invoice",
                status="paid", reserve_status="reserved", version=1, amount=100,
                content_sha256=hashlib.sha256(html.encode()).hexdigest(), original_html=html,
                issued_at=datetime(2026, 9, 9), snapshot_json={"currency": "BYN", "amount": "100.00",
                    "items": [{"sku_code": "A", "qty": "2"}, {"sku_code": "A", "qty": "3"}]}))
            session.add(DealOwnership(deal_id=doc_id, organization_id=1, snapshot={}, evidence="Synthetic", actor="tester"))
            for scope in SCOPES:
                session.add(Proof(key=f"{doc_id}:{scope}", org=1, doc=doc_id,
                    content={"decision": "no_shipment", "coverage": "complete", "observed_issue_ids": [],
                             "source_record": f"synthetic-reviewed-{scope}"}))
        for place in ("W", "X"):
            session.add(StockMovement(organization_id=1, sku_code="A", warehouse=place, kind="in", qty=20, reason="receipt"))
        await session.flush()
        for doc_id in (1, 2):
            source = await source_lock(session, doc_id)
            await reserve(session, 1, source, ReserveInput(allocations=[
                {"line_no": 1, "warehouse": "W", "qty": "2"},
                {"line_no": 2, "warehouse": "X", "qty": "3"}], journal_complete=True, evidence="Synthetic"), "tester")
            if picks:
                await apply(session, doc_id, [("A", "W", Decimal("2")), ("A", "X", Decimal("3"))],
                            organization_id=1, release=False)
        session.add(Task(organization_id=999, kind="pick", status="open", sku_code="MANUAL",
                         warehouse="Other", qty=1, doc_ref="sales:document:1"))
        await session.commit()


async def request(session):
    source = await source_lock(session)
    preview = await release_preview(session, 1, source)
    review = await RegistryVerifier().review(session, 1, source)
    data = ReleaseInput(source_key="cancel:1", expected_reservation_digest=preview["reservation_digest"],
        expected_remaining_digest=preview["remaining_digest"], fulfillment_review_id=review.review_id,
        fulfillment_review_digest=review.review_digest, evidence="Full-refund cancellation authorized by caller")
    return source, data


async def state(session):
    return {
        "versions": [(r.id, r.source, r.version, str(r.qty)) for r in (await session.scalars(select(ReservationVersion).order_by(ReservationVersion.id))).all()],
        "picks": [(t.id, t.status, t.organization_id) for t in (await session.scalars(select(Task).order_by(Task.id).execution_options(populate_existing=True))).all()],
        "movements": [(m.id, m.kind, str(m.qty)) for m in (await session.scalars(select(StockMovement).order_by(StockMovement.id))).all()],
        "releases": (await session.scalars(select(InvoiceReservationRelease.id))).all(),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("picks", [True, False])
async def test_release_paid_no_shipment_exact_lines_replay_and_foreign_untouched(factory, picks):
    await seed(factory, picks)
    async with factory() as session:
        source, data = await request(session)
        before = await state(session)
        original = copy.deepcopy((await session.get(InvoiceReservation, 1)).snapshot)
        from modules.wms.reservation_gateway import WmsReservationService

        gateway = WmsReservationService()
        assert (await gateway.invoice_release_preview(session, 1, source))["remaining_digest"] == data.expected_remaining_digest
        first = await gateway.release_invoice(session, 1, source, data.model_dump(mode="json"), "tester", RegistryVerifier())
        assert await release(session, 1, source, data, "tester", None) == first
        source["reserve_status"] = "released"  # committed-result replay need not reauthorize money
        assert await release(session, 1, source, data, "tester", None) == first
        await session.commit()
        after = await state(session)
        assert after["movements"] == before["movements"]
        assert len(after["versions"]) == len(before["versions"]) + 2
        assert (await session.get(InvoiceReservation, 1)).snapshot == original
        assert (await session.get(DealDocument, 1)).status == "paid"
        assert [line["released_qty"] for line in sorted(first["snapshot"]["lines"], key=lambda x: x["line_no"])] == ["2.00", "3.00"]
        assert all(t[1] == "open" for t in after["picks"] if t[2] == 999)
        doc2_tasks = (await session.scalars(select(Task).join(ReservationPick).where(ReservationPick.document_id == 2))).all()
        assert all(t.status == "open" for t in doc2_tasks)
        assert (await session.get(ReservationEventState, 1)).state == "released"
        # Terminal event state prevents delayed legacy reserve from recreating picks.
        await apply(session, 1, [("A", "W", Decimal("2")), ("A", "X", Decimal("3"))], organization_id=1, release=False)
        assert await state(session) == after


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["foreign_org", "version", "line", "warehouse", "started", "done", "canceled_done",
    "pick_org", "pick_qty", "missing_review", "changed_review", "stale_preview"])
async def test_rejection_is_atomic(factory, change):
    await seed(factory)
    async with factory() as session:
        source, data = await request(session)
        org = 1
        if change == "foreign_org":
            org = 2
        elif change == "version":
            source["version"] = 2
        elif change == "line":
            source["lines"][0]["qty"], source["lines"][1]["qty"] = "3", "2"
        elif change == "warehouse":
            row = await session.scalar(select(ReservationVersion).where(ReservationVersion.source.like("invoice:1:%")))
            row.warehouse = "Other"  # fixture corruption before test boundary
        elif change in {"started", "done", "canceled_done", "pick_org", "pick_qty", "stale_preview"}:
            task = await session.scalar(select(Task).join(ReservationPick).where(ReservationPick.document_id == 1))
            if change == "started":
                task.status = "in_progress"
            elif change == "done":
                task.status = "done"
            elif change == "canceled_done":
                task.status, task.done_at = "canceled", datetime(2026, 9, 9)
            elif change == "pick_org":
                task.organization_id = 2
            elif change == "pick_qty":
                task.qty = 99
            else:
                task.status = "canceled"
        elif change == "missing_review":
            await session.execute(text("DELETE FROM wms.release_test_proof WHERE key='1:legacy_fulfillment'")) if session.bind.dialect.name == "postgresql" else await session.execute(text("DELETE FROM release_test_proof WHERE key='1:legacy_fulfillment'"))
        elif change == "changed_review":
            row = await session.get(Proof, "1:legacy_fulfillment")
            row.content = {**row.content, "source_record": "different"}
        await session.flush()
        before = await state(session)
        with pytest.raises(HTTPException):
            await release(session, org, source, data, "tester", RegistryVerifier())
        assert await state(session) == before


@pytest.mark.asyncio
async def test_failure_after_versions_rolls_back_entire_package(factory, monkeypatch):
    await seed(factory)
    async with factory() as session:
        source, data = await request(session)
        before = await state(session)
        real_flush = session.flush

        async def fail(*args, **kwargs):
            await real_flush(*args, **kwargs)
            raise RuntimeError("Injected after version writes")

        monkeypatch.setattr(session, "flush", fail)
        with pytest.raises(RuntimeError, match="Injected"):
            await release(session, 1, source, data, "tester", RegistryVerifier())
        await session.rollback()
        monkeypatch.setattr(session, "flush", real_flush)
        assert await state(session) == before
        source = await source_lock(session)
        await release(session, 1, source, data, "tester", RegistryVerifier())
        await session.commit()


@pytest.mark.asyncio
async def test_replay_conflict_and_immutable_child_evidence(factory):
    await seed(factory)
    async with factory() as session:
        source, data = await request(session)
        await release(session, 1, source, data, "tester", RegistryVerifier())
        await session.commit()
        source = await source_lock(session)
        for changes in ({"source_key": "other"}, {"evidence": "different"}):
            with pytest.raises(HTTPException, match="release_request_conflict"):
                await release(session, 1, source, data.model_copy(update=changes), "tester", RegistryVerifier())
        line = await session.scalar(select(InvoiceReservationReleaseLine))
        line.released_qty = 99
        with pytest.raises(ValueError, match="immutable"):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_stale_cached_open_pick_is_refreshed_and_physical_out_is_rejected(factory):
    await seed(factory)
    async with factory() as stale:
        source, data = await request(stale)
        cached = await stale.scalar(select(Task).join(ReservationPick).where(ReservationPick.document_id == 1))
        key = cached.id
        await stale.commit()
        async with factory() as writer:
            task = await writer.get(Task, key)
            task.status = "done"
            await writer.commit()
        assert cached.status == "open"
        await source_lock(stale)
        with pytest.raises(HTTPException, match="pick_execution"):
            await release(stale, 1, source, data, "tester", RegistryVerifier())
        assert cached.status == "done"
        await stale.rollback()


@pytest.mark.asyncio
async def test_known_physical_issue_and_incomplete_review_cannot_be_approved(factory):
    await seed(factory, picks=False)
    async with factory() as session:
        source, data = await request(session)
        proof = await session.get(Proof, "1:legacy_fulfillment")
        proof.content = {**proof.content, "coverage": "unknown"}
        await session.flush()
        with pytest.raises(HTTPException, match="unresolved"):
            await release(session, 1, source, data, "tester", RegistryVerifier())
        await session.rollback()
        source = await source_lock(session)
        session.add(StockMovement(organization_id=1, sku_code="A", warehouse="W", kind="out", qty=1,
                                 reason="shipment", doc_ref="sales:document:1"))
        await session.flush()
        with pytest.raises(HTTPException, match="physical_issue"):
            await release(session, 1, source, data, "tester", RegistryVerifier())
        assert await session.scalar(select(InvoiceReservationRelease.id)) is None


@pytest.mark.asyncio
async def test_ui_boolean_is_not_verified_fulfillment(factory):
    await seed(factory, picks=False)

    class BooleanVerifier:
        async def verify_no_shipment(self, *args):
            return True

    async with factory() as session:
        source, data = await request(session)
        before = await state(session)
        with pytest.raises(HTTPException, match="verified_fulfillment_required"):
            await release(session, 1, source, data, "tester", BooleanVerifier())
        assert await state(session) == before


@pytest.mark.asyncio
async def test_replay_does_not_hide_changed_closed_pick_identity(factory):
    await seed(factory)
    async with factory() as session:
        source, data = await request(session)
        await release(session, 1, source, data, "tester", RegistryVerifier())
        await session.commit()
        task = await session.scalar(select(Task).join(ReservationPick).where(ReservationPick.document_id == 1))
        task.warehouse = "tampered"
        await session.flush()
        with pytest.raises(HTTPException, match="released_pick_identity_changed"):
            await release(session, 1, source, data, "tester", None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_concurrent_replay_is_one_linked_package():
    async with database(postgres=True) as factory:
        await seed(factory)
        async with factory() as session:
            _, data = await request(session)
            await session.commit()

        async def run():
            async with factory() as session:
                source = await source_lock(session)
                result = await release(session, 1, source, data, "tester", RegistryVerifier())
                await session.commit()
                return result

        results = await asyncio.gather(run(), run())
        assert results[0] == results[1]
        async with factory() as session:
            result = await state(session)
            assert len(result["releases"]) == 1 and len(result["versions"]) == 6
            assert len((await session.scalars(select(InvoiceReservationReleaseLine))).all()) == 2
            assert len(result["movements"]) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_namespace_guards_and_immutable_evidence():
    from sqlalchemy.exc import DBAPIError

    async with database(postgres=True) as factory:
        await seed(factory)
        async with factory() as session:
            source, data = await request(session)
            for org in (1, 2):
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(text("""INSERT INTO wms.reservation_version
                            (organization_id, source, version, sku_code, warehouse, qty, evidence, actor)
                            SELECT :org, source, 2, sku_code, warehouse, 0, 'forged', 'test'
                            FROM wms.reservation_version WHERE source LIKE 'invoice:1:%' LIMIT 1"""), {"org": org})
                        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                await session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            await release(session, 1, source, data, "tester", RegistryVerifier())
            await session.commit()
            for table in ("invoice_reservation_release", "invoice_reservation_release_line"):
                for sql in (f"DELETE FROM wms.{table}", f"TRUNCATE wms.{table} CASCADE"):
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(text(sql))
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.execute(text("UPDATE wms.invoice_reservation_release_line SET released_qty=99"))
            assert len((await state(session))["releases"]) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_current_event_consumer_waits_and_does_not_resurrect():
    from modules.accounting.gateway import AccountingService
    from modules.wms.events import on_stock_reserved

    async with database(postgres=True) as factory:
        await seed(factory, picks=False)
        ready, pid = asyncio.Event(), []

        async def consumer():
            async with factory() as session:
                pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
                ready.set()
                ctx = SimpleNamespace(session=session, services=SimpleNamespace(
                    accounting=AccountingService(), sales_source=SalesReservationSource()))
                await on_stock_reserved({"document_id": 1, "items": [
                    {"sku_code": "A", "warehouse": "W", "qty": "2"},
                    {"sku_code": "A", "warehouse": "X", "qty": "3"}]}, ctx)
                await session.commit()

        async with factory() as leader:
            source, data = await request(leader)
            leader_pid = await leader.scalar(text("SELECT pg_backend_pid()"))
            await release(leader, 1, source, data, "tester", RegistryVerifier())
            task = asyncio.create_task(consumer())
            try:
                await asyncio.wait_for(ready.wait(), 5)

                async def blocked():
                    while leader_pid not in await leader.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid[0]}):
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(blocked(), 5)
                await leader.commit()
                await asyncio.wait_for(task, 5)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        async with factory() as session:
            assert await session.scalar(select(ReservationPick.task_id).where(ReservationPick.document_id == 1)) is None
            assert (await session.get(ReservationEventState, 1)).state == "released"
            assert len((await state(session))["movements"]) == 2


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["release", "done"])
async def test_postgres_release_vs_pick_done_locks(first):
    async with database(postgres=True) as factory:
        await seed(factory)
        async with factory() as cached:
            source, data = await request(cached)
            task = await cached.scalar(select(Task).join(ReservationPick).where(ReservationPick.document_id == 1))
            task_id = task.id
            await cached.commit()
            ready, writer_pid = asyncio.Event(), []

            async def follower():
                async with factory() as session:
                    writer_pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
                    ready.set()
                    try:
                        await lock_organization(session, 1)
                        if first == "release":
                            fresh = await session.scalar(select(Task).where(Task.id == task_id).with_for_update().execution_options(populate_existing=True))
                            assert fresh.status == "canceled"
                            return "task-refused"
                        source = await source_lock(session)
                        await release(session, 1, source, data, "tester", RegistryVerifier())
                    except HTTPException as exc:
                        await session.rollback()
                        return exc.detail

            source = await source_lock(cached)
            leader_pid = await cached.scalar(text("SELECT pg_backend_pid()"))
            if first == "release":
                await release(cached, 1, source, data, "tester", RegistryVerifier())
            else:
                task.status, task.done_at = "done", datetime(2026, 9, 9)
                cached.add(StockMovement(organization_id=1, sku_code=task.sku_code, warehouse=task.warehouse,
                    kind="out", qty=task.qty, reason="pick", doc_ref="sales:document:1"))
                await cached.flush()
            contender = asyncio.create_task(follower())
            try:
                await asyncio.wait_for(ready.wait(), 5)

                async def blocked():
                    while leader_pid not in await cached.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": writer_pid[0]}):
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(blocked(), 5)
                await cached.commit()
                outcome = await asyncio.wait_for(contender, 5)
                assert outcome == ("task-refused" if first == "release" else "pick_execution_requires_reconciliation")
            finally:
                if not contender.done():
                    contender.cancel()
                    await asyncio.gather(contender, return_exceptions=True)
        async with factory() as session:
            result = await state(session)
            assert len(result["releases"]) == (1 if first == "release" else 0)
            assert len(result["movements"]) == (2 if first == "release" else 3)


async def forged_manual_package(session):
    """Initial malformed INSERT evidence; never disable installed guards."""
    source, data = await request(session)
    valid = await release(session, 1, source, data, "tester", RegistryVerifier())
    record = await session.get(InvoiceReservationRelease, valid["release_id"])
    snapshot, request_hash = copy.deepcopy(record.snapshot), record.request_hash
    await session.rollback()
    session.expunge_all()
    source = await source_lock(session)
    for index, line in enumerate(snapshot["lines"]):
        source_key = f"manual-other-{index}"
        before = ReservationVersion(organization_id=1, source=source_key, version=1,
            sku_code=line["sku_code"], warehouse=line["warehouse"], qty=Decimal(line["released_qty"]),
            evidence="Synthetic malformed history", actor="tester")
        after = ReservationVersion(organization_id=1, source=source_key, version=2,
            sku_code=line["sku_code"], warehouse=line["warehouse"], qty=Decimal("0"),
            evidence="Synthetic malformed history", actor="tester")
        session.add_all([before, after])
        await session.flush()
        line.update(source=source_key, before_id=before.id, after_id=after.id)
    event_state = await session.get(ReservationEventState, 1)
    event_state.state = "released"
    tasks = (await session.scalars(select(Task).join(ReservationPick)
             .where(ReservationPick.document_id == 1))).all()
    for task in tasks:
        task.status = "canceled"
    forged = InvoiceReservationRelease(document_id=1, organization_id=1, source_key=data.source_key,
        request_hash=request_hash, digest=package_digest(snapshot), snapshot=snapshot, actor="tester")
    session.add(forged)
    await session.flush()
    for line in snapshot["lines"]:
        session.add(InvoiceReservationReleaseLine(release_id=forged.id, source=line["source"],
            before_id=line["before_id"], after_id=line["after_id"], line_no=line["line_no"],
            released_qty=Decimal(line["released_qty"])))
    await session.flush()
    return source, data


@pytest.mark.asyncio
async def test_replay_rejects_manual_sources_in_forged_package(factory):
    await seed(factory)
    async with factory() as session:
        source, data = await forged_manual_package(session)
        await session.commit()  # SQLite fixture has no PG structural insert trigger.
        await source_lock(session)
        with pytest.raises(HTTPException, match="release_original_allocation_mismatch"):
            await release(session, 1, source, data, "tester", None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_rejects_package_using_unrelated_manual_reserves():
    from sqlalchemy.exc import DBAPIError

    async with database(postgres=True) as factory:
        await seed(factory)
        async with factory() as session:
            await forged_manual_package(session)
            with pytest.raises(DBAPIError, match="Invalid invoice release links"):
                await session.commit()
            await session.rollback()
            assert await session.scalar(select(InvoiceReservationRelease.id)) is None
