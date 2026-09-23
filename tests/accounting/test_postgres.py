"""Real PostgreSQL evidence. Explicit URL required; fresh per-test databases only."""
from __future__ import annotations

import asyncio
import os
import runpy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.domain.reference import Currency
from modules.accounting import service
from modules.accounting.schemas import CloseInput

pytestmark = pytest.mark.integration


# ``migration-proposal.py`` freezes the shared 0130 accounting baseline for
# disposable PostgreSQL databases.  The ORM has since gained only registered
# additive accounting revisions, so a fixture must replay the same tail rather
# than silently creating current tables from metadata.  Keeping this list
# explicit makes a missing registration fail in the focused PostgreSQL tests.
ACCOUNTING_TAIL_MIGRATIONS = (
    "0140_zero_value_disposals.py",
    "0141_zero_value_output_cost.py",
    "0142_zero_value_command_dates.py",
    "0143_zero_value_sales.py",
    "0144_inventory_explicit_allocation_guards.py",
    "0145_inventory_allocation_cost_stream.py",
    "0146_zero_value_allocation_basis.py",
    "0147_zero_value_allocation_runtime.py",
    "0148_zero_value_allocated_sales.py",
    "0149_production_material_allocations.py",
    "0150_zero_material_allocations.py",
    "0151_late_material_output_cost.py",
    "0152_signed_prospective_wip.py",
    "0153_late_pool_atomic_package.py",
    "0154_late_pool_actual_output_evidence.py",
    "0155_late_pool_inventory_value_links.py",
    "0156_expense_article_attribution.py",
    "0157_statutory_requirement_catalog.py",
    "0158_catalog_adoption.py",
    "0159_shipment_document_policy.py",
    "0160_reconciliation_issue_queue.py",
    "0161_payroll_employment_binding.py",
    "0162_payroll_rule_set.py",
)


@pytest.mark.parametrize("direction", ["receipt", "refund"])
async def test_invoice_allocation_concurrency_caps_bank_and_refund(pg_factory, pg_book, direction):
    from datetime import datetime

    from fastapi import HTTPException
    from sqlalchemy import func, select

    from core.services.auth import CurrentUser
    from modules.accounting.documents import BankDocument
    from modules.accounting.gateway import AccountingService
    from modules.sales.access import DealAccess
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.invoice_settlements import AllocationInput, InvoiceSettlement, allocate
    from modules.sales.models import Deal, DealDocument
    from tests.accounting.test_bank_documents import document

    gateway = AccountingService()
    core = SimpleNamespace(services=SimpleNamespace(accounting=gateway))
    user = CurrentUser("tester", ["director"])

    async def allocation(session, bank_id, key, amount, refund_of=None):
        actor = await gateway.source_owner_authority(session, pg_book[0], user)
        return await allocate(pg_book[0], 1, AllocationInput(source_key=key, bank_entry_id=bank_id,
            amount=amount, refund_of=refund_of, evidence="Synthetic concurrency evidence"),
            (session, actor), DealAccess("all"), core, user)

    async with pg_factory() as session:
        session.add(Deal(id=1, number="SYN-ALLOC", title="Synthetic", counterparty="Synthetic"))
        await session.flush()
        session.add_all([
            DealOwnership(deal_id=1, organization_id=pg_book[0], snapshot={}, evidence="Synthetic", actor="tester"),
            DealDocument(id=1, deal_id=1, kind="invoice", number="SYN-ALLOC", status="posted", amount=100,
                original_html="Synthetic", content_sha256="a" * 64, issued_at=datetime(2026, 9, 1), snapshot_json={"currency": "BYN"}),
        ])
        await session.flush()
        bank_ids = []
        for index, bank_direction in enumerate(["receipt", "payment", "payment"]):
            data = BankDocument(**document(source=f"bank-{index}", statement_reference=f"bank-{index}",
                policy_id=pg_book[1], amount="100.00", direction=bank_direction,
                settlement_dimensions={"settlement_document": "sales:document:1"}))
            row = await service.post(session, pg_book[0], data.posting(), "tester")
            bank_ids.append(row.id)
        refund_of = None
        if direction == "refund":
            refund_of = (await allocation(session, bank_ids[0], "original", "100.00"))["id"]
        await session.commit()

    async def writer(index):
        async with pg_factory() as session:
            try:
                await allocation(session, bank_ids[0] if direction == "receipt" else bank_ids[index + 1],
                                 f"concurrent-{index}", "80.00", refund_of)
                await session.commit()
                return 201
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code

    assert sorted(await asyncio.gather(writer(0), writer(1))) == [201, 409]
    async with pg_factory() as session:
        assert await session.scalar(select(func.sum(InvoiceSettlement.amount)).where(
            InvoiceSettlement.direction == direction)) == 80


async def test_invoice_money_database_guards(pg_factory, pg_book):
    from sqlalchemy.exc import DBAPIError

    from modules.sales.invoice_settlements import InvoiceSettlement
    from modules.sales.models import Deal, DealDocument

    async with pg_factory() as session:
        session.add(Deal(id=1, number="SYN-MONEY", title="Synthetic", counterparty="Synthetic"))
        await session.flush()
        session.add_all([
            DealDocument(id=1, deal_id=1, kind="invoice", number="SYN-PAID", status="paid", amount=100),
            DealDocument(id=2, deal_id=1, kind="invoice", number="SYN-PARTIAL", status="posted", amount=100),
            DealDocument(id=3, deal_id=1, kind="invoice", number="SYN-UNPAID", status="posted", amount=100),
        ])
        await session.flush()
        # Synthetic row tests database immutability, not bank evidence acceptance.
        session.add(InvoiceSettlement(organization_id=pg_book[0], document_id=2,
            source_key="synthetic", bank_entry_id=999, direction="receipt", amount=10,
            evidence="Synthetic DB guard fixture", snapshot={}, actor="tester"))
        await session.commit()
    for sql in (
        "UPDATE sales.deal_document SET status='cancelled' WHERE id=1",
        "UPDATE sales.deal_document SET status='posted' WHERE id=1",
        "UPDATE sales.deal_document SET status='cancelled' WHERE id=2",
        "DELETE FROM sales.deal_document WHERE id=1",
        "DELETE FROM sales.deal_document WHERE id=2",
        "TRUNCATE sales.deal_document CASCADE",
        "UPDATE sales.invoice_settlement SET amount=0",
        "DELETE FROM sales.invoice_settlement",
        "TRUNCATE sales.invoice_settlement",
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text(sql))
            await session.rollback()
    async with pg_factory() as session:
        await session.execute(text("UPDATE sales.deal_document SET status='cancelled' WHERE id=3"))
        await session.commit()
        assert (await session.execute(text("SELECT status FROM sales.deal_document ORDER BY id"))).scalars().all() == ["paid", "posted", "cancelled"]


async def test_sales_ownership_database_guards(pg_factory, pg_book):
    from sqlalchemy.exc import DBAPIError

    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.models import Deal

    async with pg_factory() as session:
        session.add(Deal(id=1, number="SYN-OWN", title="Synthetic", counterparty="Synthetic"))
        await session.flush()
        session.add(DealOwnership(deal_id=1, organization_id=pg_book[0], snapshot={"deal_id": 1}, evidence="Synthetic", actor="tester"))
        await session.commit()
    for sql in ("UPDATE sales.deal_ownership SET organization_id=999", "DELETE FROM sales.deal_ownership", "TRUNCATE sales.deal_ownership"):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text(sql))
            await session.rollback()
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT organization_id FROM sales.deal_ownership WHERE deal_id=1")) == pg_book[0]


async def test_inventory_issue_concurrent_confirm_cannot_overdraw(pg_factory, pg_book, posting):
    from datetime import date

    from modules.accounting import inventory_issues
    from modules.accounting.models import Account
    from modules.accounting.schemas import InventoryIssueDocument
    from tests.accounting.test_inventory_cost import issue_document, move

    async with pg_factory() as session:
        session.add(Account(id=1000, organization_id=pg_book[0], code="41.2", title="Synthetic goods", category="asset", valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False, quantity_tracking=True, cash=False, normative_ref="Synthetic"))
        await session.commit()
        await move(session, pg_book, posting, "receipt", "3", "10.00")
    requests = []
    for source in ("issue-A", "issue-B"):
        document = InventoryIssueDocument(**issue_document(pg_book, source=source, quantity="2"))
        async with pg_factory() as session:
            cost, prepared = await inventory_issues.prepare(session, pg_book[0], document)
            requests.append((document, cost["basis_digest"], service.digest(prepared)))
            await session.commit()

    async def writer(data):
        async with pg_factory() as session:
            try:
                row = await inventory_issues.confirm(session, pg_book[0], *data, "tester")
                await session.commit()
                return row.id
            except service.AccountingError:
                await session.rollback()
                return None

    results = await asyncio.gather(*(writer(data) for data in requests))
    assert sum(result is not None for result in results) == 1
    winner = next(index for index, result in enumerate(results) if result is not None)
    assert await writer(requests[winner]) == results[winner]
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM accounting.entry")) == 2
        assert str(await session.scalar(text("SELECT sum(CASE WHEN side='debit' THEN quantity ELSE -quantity END) FROM accounting.line WHERE account_code='41.2'"))) == "1.000000"


async def test_sale_concurrent_confirm_is_one_atomic_package(pg_factory, pg_book, posting):
    from datetime import date

    from core.services.eventbus import OutboxEventBus
    from modules.accounting import sales
    from modules.accounting.models import Account
    from tests.accounting.test_sales import setup_sale

    async with pg_factory() as session:
        session.add(Account(id=1000, organization_id=pg_book[0], code="41.2", title="Synthetic goods", category="asset", valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False, quantity_tracking=True, cash=False, normative_ref="Synthetic"))
        await session.commit()
        # pg_book seeds explicit account IDs; advance only this disposable fixture's sequence.
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account', 'id'), (SELECT max(id) FROM accounting.account))"))
        data = await setup_sale(session, pg_book, posting, quantity="2")
    requests = []
    for source in ("sale-A", "sale-B"):
        document = sales.SaleDocument(**{**data, "source": source})
        async with pg_factory() as session:
            prepared = await sales.prepare(session, pg_book[0], document)
            requests.append((document, prepared["cost"]["basis_digest"], prepared["digest"]))
            await session.commit()

    async def writer(data):
        async with pg_factory() as session:
            try:
                row = await sales.confirm(session, pg_book[0], *data, "tester", OutboxEventBus())
                await session.commit()
                return row.id
            except service.AccountingError:
                await session.rollback()
                return None

    results = await asyncio.gather(*(writer(data) for data in requests))
    assert sum(result is not None for result in results) == 1
    winner = next(index for index, result in enumerate(results) if result is not None)
    assert await writer(requests[winner]) == results[winner]
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM accounting.entry")) == 2
        assert await session.scalar(text("SELECT count(*) FROM accounting.line WHERE entry_id=:id"), {"id": results[winner]}) == 6
        assert await session.scalar(text("SELECT count(*) FROM outbox_event WHERE event_type='accounting.entry.posted'")) == 1
        assert str(await session.scalar(text("SELECT sum(CASE WHEN side='debit' THEN quantity ELSE -quantity END) FROM accounting.line WHERE account_code='41.2'"))) == "1.000000"


async def test_primary_receipt_http_concurrent_replay_and_snapshot(pg_factory, pg_book):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from core.runtime.deps import get_session
    from core.services.auth import CurrentUser, get_current_user
    from modules.accounting.gateway import AccountingService
    from modules.procurement.receipt_documents import ReceiptDocument, output, router
    from tests.accounting.test_procurement_receipt_drafts import document

    app = FastAPI()
    app.include_router(router, prefix="/procurement")
    app.state.core = SimpleNamespace(services=SimpleNamespace(accounting=AccountingService(), event_bus=None))

    async def session_dependency():
        async with pg_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["director"])
    path = f"/procurement/organizations/{pg_book[0]}/receipt-documents"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {"key": "concurrent-primary", "document": document()}
        responses = await asyncio.gather(*(client.post(path, json=payload) for _ in range(2)))
        assert [response.status_code for response in responses] == [201, 201]
        receipt_id = responses[0].json()["id"]
        assert responses[1].json()["id"] == receipt_id
        async with pg_factory() as reader:
            header = await reader.scalar(select(ReceiptDocument).where(ReceiptDocument.id == receipt_id))
            assert header.current_version == 1
            changed = await client.put(path + f"/{receipt_id}", json={
                "expected_version": 1,
                "document": {**document(), "invoice_reference": "INV2"},
            })
            assert changed.status_code == 200
            snapshot = await output(reader, header)
            assert snapshot["version"] == 1
            assert [revision["version"] for revision in snapshot["revisions"]] == [1]
        listed = (await client.get(path)).json()
        assert len(listed) == 1
        assert listed[0]["version"] == 2
        from datetime import date

        from modules.accounting.models import Account
        from modules.procurement.ownership import PurchaseOwnership

        async with pg_factory() as session:
            session.add(PurchaseOwnership(organization_id=pg_book[0], kind="order", source_id=44,
                                          snapshot={}, evidence="Synthetic source ownership", actor="tester"))
            session.add(Account(id=1009, organization_id=pg_book[0], code="41.2", title="Synthetic goods",
                                category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
                                currency_tracking=False, quantity_tracking=True, cash=False,
                                normative_ref="synthetic"))
            await session.commit()
        facts = document()
        facts["items"][0].update(vat_rate="0", vat_amount="0.00", order_id=44)
        assert (await client.put(path + f"/{receipt_id}", json={"expected_version": 2, "document": facts})).status_code == 200
        options = {"expected_version": 3, "posting_date": "2026-09-03", "policy_id": pg_book[1],
                   "settlement_account": "60", "vat_account": None, "inventory_accounts": ["41.2"]}
        preview = await client.post(path + f"/{receipt_id}/preview", json=options)
        assert preview.status_code == 200, preview.text
        assert preview.json()["lines"][0]["dimensions"]["order"] == "44"
        confirmation = {**options, "digest": preview.json()["digest"]}
        results = await asyncio.gather(*(client.post(path + f"/{receipt_id}/confirm", json=confirmation) for _ in range(2)))
        assert [result.status_code for result in results] == [201, 201]
        assert results[0].json()["entry_id"] == results[1].json()["entry_id"]
        async with pg_factory() as session:
            assert await session.scalar(text("SELECT count(*) FROM accounting.entry")) == 1
            assert await session.scalar(text("SELECT count(*) FROM procurement.receipt_posting")) == 1
            with pytest.raises(Exception, match="immutable"):
                await session.execute(text("UPDATE procurement.receipt_document SET current_version=current_version+1"))
            await session.rollback()
            with pytest.raises(Exception, match="immutable"):
                await session.execute(text("DELETE FROM procurement.receipt_posting"))
            await session.rollback()
            with pytest.raises(Exception, match="cannot be deleted"):
                await session.execute(text("DELETE FROM accounting.source_control"))
            await session.rollback()


@pytest_asyncio.fixture
async def pg_factory():
    from sqlalchemy.engine import make_url

    url = os.getenv("ACCOUNTING_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set ACCOUNTING_TEST_POSTGRES_URL for isolated PostgreSQL acceptance")
    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost"} or parsed.database != "accounting_test":
        pytest.fail("Refusing a non-local/non-test PostgreSQL target")
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    database = "acc_test_" + uuid4().hex
    engine = None
    created = False
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{database}"'))
            created = True
            await conn.execute(text(f'COMMENT ON DATABASE "{database}" IS \'crm-acc-fixture:{database}\''))
        engine = create_async_engine(parsed.set(database=database))
        async with engine.begin() as conn:
            # Exercise the frozen proposal via real Alembic Operations, not create_all.
            # Revision registration remains subject to the shared allocator/operator.
            from alembic.migration import MigrationContext
            from alembic.operations import Operations

            migration = runpy.run_path(str(Path("docs/accounting/migration-proposal.py")))

            def upgrade(connection):
                from sqlalchemy import MetaData

                from core.domain.models import (
                    AuditLog,
                    Counterparty,
                    IdentityInvitationRequest,
                    OutboxEvent,
                    User,
                )
                from modules.hr.models import Employee
                from modules.logistics.models import CarrierRfq, ImportShipment, Shipment
                from modules.office.models import OfficeDoc
                from modules.procurement.models import (
                    PurchaseOrder,
                    PurchaseOrderLine,
                    PurchaseRequest,
                )
                from modules.production.models import ProductionOrder
                from modules.sales.models import (
                    CrmClient,
                    CrmClientContact,
                    Deal,
                    DealDocument,
                    DealStageEvent,
                    LossReason,
                    Stage,
                )
                from modules.wms import models as wms_models

                # Existing WMS schema before this additive ownership migration.
                baseline = MetaData()
                for table in wms_models.Base.metadata.sorted_tables:
                    if table.schema == "wms" and table.name in {"invoice_remainder_release", "invoice_remainder_release_line"}:
                        continue  # Added by registered migration 0131 after the accounting baseline.
                    if table.schema == "wms" and table.name == "production_arrival":
                        continue  # Added by the shared unallocated proposal, not the legacy baseline.
                    if table.schema == "wms" and table.name not in {"primary_receipt_binding", "reservation_version", "reservation_event_state", "reservation_pick", "invoice_reservation", "invoice_reservation_release", "invoice_reservation_release_line", "physical_shipment_act", "physical_shipment_line", "production_material_issue"}:
                        copied = table.to_metadata(baseline)
                        for constraint in list(copied.constraints):
                            if "source_event_id" in constraint.columns or "organization_id" in str(getattr(constraint, "sqltext", "")):
                                copied.constraints.remove(constraint)
                        for name in ("organization_id", "source_event_id", "expected_source", "source_evidence",
                                     "journal_confirmed_by", "journal_confirmed_at", "snapshot_version",
                                     "snapshot_cutoff", "snapshot_at"):
                            if name in copied.c:
                                copied._columns.remove(copied.c[name])
                connection.execute(text("CREATE SCHEMA wms"))
                baseline.create_all(connection)
                User.__table__.create(connection)
                IdentityInvitationRequest.__table__.create(connection)
                Counterparty.__table__.create(connection)
                connection.execute(text("CREATE SCHEMA sales"))
                CrmClient.__table__.create(connection)
                CrmClientContact.__table__.create(connection)
                Deal.__table__.create(connection)
                DealDocument.__table__.create(connection)
                Stage.__table__.create(connection)
                DealStageEvent.__table__.create(connection)
                LossReason.__table__.create(connection)

                # Bank-source completeness is part of month closing; these
                # existing finance tables precede the accounting migration.
                from modules.finance.models import (
                    BankAccount,
                    BankTransaction,
                    Payment,
                    PaymentAllocation,
                )

                connection.execute(text("CREATE SCHEMA finance"))
                for table in (BankAccount.__table__, Payment.__table__, PaymentAllocation.__table__, BankTransaction.__table__):
                    table.create(connection)

                connection.execute(text("CREATE SCHEMA logistics"))
                Shipment.__table__.create(connection)
                CarrierRfq.__table__.create(connection)
                # Already registered in migration 0023; the proposal must preserve it.
                ImportShipment.__table__.create(connection)
                connection.execute(text("CREATE SCHEMA office"))
                OfficeDoc.__table__.create(connection)
                # The global HR identity is a legacy FK target of the new
                # accounting-owned employment evidence in revision 0161.
                connection.execute(text("CREATE SCHEMA hr"))
                Employee.__table__.create(connection)
                # Existing request table is an FK target of the additive
                # request-creation receipt; never create that receipt via ORM.
                connection.execute(text("CREATE SCHEMA procurement"))
                PurchaseRequest.__table__.create(connection)
                PurchaseOrder.__table__.create(connection)
                PurchaseOrderLine.__table__.create(connection)
                # Existing production order is the target of additive ownership.
                connection.execute(text("CREATE SCHEMA production"))
                ProductionOrder.__table__.create(connection)

                Currency.__table__.create(connection)
                OutboxEvent.__table__.create(connection)
                AuditLog.__table__.create(connection)
                # Reproduce pre-issuance widths; the proposal must perform the
                # actual 128 -> 200 upgrade, not merely accept current ORM widths.
                connection.execute(text("ALTER TABLE sales.deal_document ALTER COLUMN issued_by TYPE varchar(128)"))
                connection.execute(text("ALTER TABLE public.audit_log ALTER COLUMN actor TYPE varchar(128)"))
                with Operations.context(MigrationContext.configure(connection)):
                    migration["upgrade"]()
                    remainder = runpy.run_path("migrations/versions/0131_invoice_remainder.py")
                    remainder["upgrade"]()
                    runpy.run_path("migrations/versions/0132_expense_approval_digest.py")["upgrade"]()
                    for migration_name in (
                        "0139_production_output_cost_revision.py",
                        *ACCOUNTING_TAIL_MIGRATIONS,
                    ):
                        runpy.run_path(f"migrations/versions/{migration_name}")["upgrade"]()

            await conn.run_sync(upgrade)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        try:
            if engine is not None:
                await engine.dispose()
            if created:
                # Only this invocation's generated name; refuse an altered marker
                # or live connections instead of terminating another process.
                async with admin.connect() as conn:
                    marker = await conn.scalar(text("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=:name"), {"name": database})
                    if marker != f"crm-acc-fixture:{database}":
                        raise RuntimeError(f"Fixture database marker changed: {database}")
                    # Server-side disconnect visibility can lag pool disposal.
                    # Observe boundedly; never terminate a remaining connection.
                    for attempt in range(20):
                        active = await conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=:name"), {"name": database})
                        if not active:
                            break
                        await asyncio.sleep(0.1)
                    if active:
                        raise RuntimeError(f"Fixture database still has connections: {database}")
                    await conn.execute(text(f'DROP DATABASE "{database}"'))
        finally:
            await admin.dispose()



@pytest_asyncio.fixture
async def pg_book(pg_factory, db, book):
    from sqlalchemy import select

    from modules.accounting.models import AccessGrant, Account, Organization, Policy

    async with pg_factory() as session:
        for model in (Organization, AccessGrant, Account, Policy):
            rows = (await db.scalars(select(model))).all()
            for row in rows:
                session.add(model(**{c.key: getattr(row, c.key) for c in model.__table__.columns}))
            await session.flush()
        await session.commit()
    return book


async def test_opening_import_receipt_is_bound_and_immutable_in_postgres(pg_factory, pg_book, posting):
    from decimal import Decimal

    from sqlalchemy.exc import DBAPIError

    from modules.accounting.models import OpeningImportReceipt

    data = posting("opening-receipt", "51", "80", "100.00", opening=True)
    async with pg_factory() as session:
        entry = await service.post(session, pg_book[0], data, "tester")
        receipt = OpeningImportReceipt(
            organization_id=pg_book[0], request_key="00000000-0000-0000-0000-000000000001",
            batch="pg-opening", protocol_version="opening-balance-v1", source_system="1c-export",
            source_digest="a" * 64, cutover_date=data.posting_date, entry_count=1, line_count=2,
            debit_total=Decimal("100.00"), credit_total=Decimal("100.00"), command_digest="b" * 64,
            evidence="Synthetic PostgreSQL opening reconciliation", entry_ids=[entry.id],
            snapshot={"entries": [{"entry_id": entry.id}]}, digest="c" * 64, actor="tester",
        )
        session.add(receipt)
        await session.commit()
    async with pg_factory() as session:
        for statement in [
            "UPDATE accounting.opening_import_receipt SET evidence='changed'",
            "DELETE FROM accounting.opening_import_receipt",
        ]:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement))
            await session.rollback()
        forged = dict(
            organization_id=pg_book[0], request_key="00000000-0000-0000-0000-000000000002",
            batch="pg-forged", protocol_version="opening-balance-v1", source_system="1c-export",
            source_digest="d" * 64, cutover_date=data.posting_date, entry_count=1, line_count=2,
            debit_total=Decimal("100.00"), credit_total=Decimal("100.00"), command_digest="e" * 64,
            evidence="Synthetic forged receipt", entry_ids=[999999], snapshot={"entries": []}, digest="f" * 64,
            actor="tester",
        )
        session.add(OpeningImportReceipt(**forged))
        with pytest.raises(DBAPIError, match="same-organization opening entries"):
            await session.commit()
        await session.rollback()


async def test_source_ownership_is_unique_and_immutable_in_postgres(pg_factory, pg_book):
    from sqlalchemy.exc import DBAPIError, IntegrityError

    from modules.accounting.models import SourceBinding

    async def writer(ownership):
        async with pg_factory() as session:
            session.add(SourceBinding(organization_id=pg_book[0], source_type="wms_receipt",
                                      source_id=42, ownership=ownership,
                                      evidence="Synthetic ownership decision", actor="tester"))
            try:
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
                return False

    assert sorted(await asyncio.gather(writer("own"), writer("customer"))) == [False, True]
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM accounting.source_binding")) == 1
        for statement in ["UPDATE accounting.source_binding SET evidence='changed'",
                          "DELETE FROM accounting.source_binding"]:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement))
            await session.rollback()


async def test_logistics_import_source_binding_is_supported_and_type_guarded(pg_factory, pg_book):
    from sqlalchemy.exc import DBAPIError

    from modules.accounting.models import SourceBinding
    from modules.logistics.models import ImportShipment

    async with pg_factory() as session:
        source = ImportShipment(supplier="Synthetic supplier", number="IMP-PG-1", cargo="SKU-1", po_ref="purchase:pg-1")
        session.add(source)
        await session.flush()
        session.add(SourceBinding(organization_id=pg_book[0], source_type="logistics_import",
                                  source_id=source.id, ownership="own",
                                  evidence="Synthetic logistics ownership decision", actor="tester"))
        await session.commit()
        assert await session.scalar(text("SELECT count(*) FROM accounting.source_binding WHERE source_type='logistics_import'")) == 1
    async with pg_factory() as session:
        session.add(SourceBinding(organization_id=pg_book[0], source_type="unknown_source",
                                  source_id=999, ownership="own",
                                  evidence="Synthetic invalid source type", actor="tester"))
        with pytest.raises(DBAPIError, match="source_binding_type"):
            await session.commit()
        await session.rollback()


async def test_procurement_draft_versions_serialize_and_cannot_be_truncated(pg_factory, pg_book):
    from fastapi import HTTPException
    from sqlalchemy.exc import DBAPIError

    from core.services.auth import CurrentUser
    from modules.accounting.gateway import AccountingService
    from modules.procurement.receipt_documents import (
        ReceiptCreate,
        ReceiptEdit,
        create_document,
        edit_document,
    )
    from tests.accounting.test_procurement_receipt_drafts import document

    async with pg_factory() as session:
        saved = await create_document(pg_book[0], ReceiptCreate(key="primary1", document=document()), (session, "tester"), (session, AccountingService(), CurrentUser("tester", ["director"])))
        await session.commit()

    async def editor(reference):
        async with pg_factory() as session:
            try:
                result = await edit_document(pg_book[0], saved["id"], ReceiptEdit(
                    expected_version=1, document={**document(), "invoice_reference": reference},
                ), (session, "tester"), (session, AccountingService(), CurrentUser("tester", ["director"])))
                await session.commit()
                return result["version"]
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code

    assert sorted(await asyncio.gather(editor("second-A"), editor("second-B"))) == [2, 409]
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM procurement.receipt_revision")) == 2
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text("UPDATE procurement.receipt_revision SET actor='other'"))
        await session.rollback()
        with pytest.raises(DBAPIError, match="incomplete"):
            await session.execute(text("UPDATE procurement.receipt_document SET current_version=3"))
            await session.commit()
        await session.rollback()
        assert await session.scalar(text("SELECT current_version FROM procurement.receipt_document")) == 2


async def test_concurrent_replay_one_entry(pg_factory, pg_book, posting):
    async def writer():
        async with pg_factory() as session:
            entry = await service.post(session, pg_book[0], posting(), "tester")
            await session.commit()
            return entry.id
    results = await asyncio.gather(writer(), writer(), writer())
    assert len(set(results)) == 1


async def test_primary_creation_and_month_close_are_serialized(pg_factory, pg_book):
    from fastapi import HTTPException

    from core.services.auth import CurrentUser
    from modules.accounting.gateway import AccountingService
    from modules.procurement.receipt_documents import ReceiptCreate, create_document
    from tests.accounting.test_procurement_receipt_drafts import document

    async def creator():
        async with pg_factory() as session:
            gateway, user = AccountingService(), CurrentUser("tester", ["director"])
            try:
                actor = await gateway.source_member(session, pg_book[0], user)
                await create_document(pg_book[0], ReceiptCreate(key="close-race", document=document()),
                                      (session, actor), (session, gateway, user))
                await session.commit()
                return "created"
            except HTTPException as exc:
                assert exc.status_code == 409
                await session.rollback()
                return "blocked"

    async def closer():
        async with pg_factory() as session:
            try:
                await service.close_period(session, pg_book[0], "2026-09", CloseInput(
                    expected_generation=0, evidence={k: "checked" for k in service.CLOSE_STEPS}), "tester")
                await session.commit()
                return "closed"
            except service.AccountingError:
                await session.rollback()
                return "blocked"

    results = await asyncio.gather(creator(), closer())
    assert tuple(results) in {("created", "blocked"), ("blocked", "closed")}


async def test_outbox_survives_subscriber_crash_without_duplicate_posting(pg_factory, pg_book, posting):
    from sqlalchemy import func, select

    from core.domain.models import OutboxEvent
    from core.services.eventbus import EventContext, OutboxEventBus
    from modules.accounting.models import Entry, Inbox
    from modules.accounting.module import on_posting_requested

    bus = OutboxEventBus()
    bus.subscribe("accounting.posting.requested", on_posting_requested)
    async with pg_factory() as session:
        bus.emit(session, "accounting.posting.requested", dict(
            organization_id=pg_book[0], month="2026-09", event_key="source-event",
            posting=posting().model_dump(mode="json"),
        ))
        await session.commit()

    async def crash_after_handler(payload, ctx):
        raise RuntimeError("simulated subscriber crash before commit")

    broken_bus = OutboxEventBus()
    broken_bus.subscribe("accounting.posting.requested", on_posting_requested)
    broken_bus.subscribe("accounting.posting.requested", crash_after_handler)
    async with pg_factory() as session:
        with pytest.raises(RuntimeError, match="simulated"):
            await broken_bus.relay_once(session, EventContext(session, SimpleNamespace()))
        await session.rollback()
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Inbox)) == 0
        assert await session.scalar(select(OutboxEvent.processed_at)) is None
        assert await bus.relay_once(session, EventContext(session, SimpleNamespace())) == 1
    async with pg_factory() as session:
        inbox_id = await session.scalar(select(Inbox.id))
        first = await service.confirm_inbox(session, pg_book[0], inbox_id, "tester", bus)
        await session.commit()
        second = await service.confirm_inbox(session, pg_book[0], inbox_id, "tester", bus)
        await session.commit()
        assert second.id == first.id
        assert await session.scalar(select(func.count()).select_from(Entry)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "accounting.entry.posted")) == 1


async def test_posting_and_outbound_event_rollback_together(pg_factory, pg_book, posting):
    from sqlalchemy import func, select

    from core.domain.models import OutboxEvent
    from core.services.eventbus import OutboxEventBus
    from modules.accounting.models import Entry

    async with pg_factory() as session:
        await service.post(session, pg_book[0], posting(), "tester", OutboxEventBus())
        await session.rollback()  # Failure before the caller's atomic commit.
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


async def test_database_immutable_and_balanced(pg_factory, pg_book, posting):
    async with pg_factory() as session:
        entry = await service.post(session, pg_book[0], posting(), "tester")
        entry_id = entry.id
        await session.commit()
    async with pg_factory() as session:
        with pytest.raises(Exception, match="immutable"):
            await session.execute(text("UPDATE accounting.line SET amount=0 WHERE entry_id=:id"),
                                  {"id": entry_id})
        await session.rollback()
    async with pg_factory() as session:
        with pytest.raises(Exception, match="committed entry"):
            await session.execute(text("""INSERT INTO accounting.line
              (entry_id,account_id,account_code,account_title,category,cash,side,amount,dimensions,currency)
              SELECT entry_id,account_id,account_code,account_title,category,cash,side,amount,dimensions,currency
              FROM accounting.line WHERE entry_id=:id LIMIT 1"""), {"id": entry_id})
        await session.rollback()
    async with pg_factory() as session:
        with pytest.raises(Exception, match="unbalanced"):
            await session.execute(text("""INSERT INTO accounting.entry
            (organization_id,source,source_version,operation,document_date,operation_date,posting_date,
             policy_id,rule_version,explanation,opening,digest,actor)
            VALUES (:org,'raw-empty',1,'manual','2026-09-01','2026-09-01','2026-09-01',
                    :policy,'test','test',false,'test','tester')"""),
                                  {"org": pg_book[0], "policy": pg_book[1]})
            await session.commit()
        await session.rollback()


async def test_close_and_post_are_serialized(pg_factory, pg_book, posting):
    async with pg_factory() as session:
        await service.post(session, pg_book[0], posting(), "tester")
        await session.commit()
    async def closer():
        async with pg_factory() as session:
            try:
                await service.close_period(session, pg_book[0], "2026-09", CloseInput(
                    expected_generation=1, evidence={k: "checked" for k in service.CLOSE_STEPS}
                ), "tester")
                await session.commit()
                return "closed"
            except service.AccountingError:
                await session.rollback()
                return "stale"
    async def writer():
        async with pg_factory() as session:
            try:
                await service.post(session, pg_book[0], posting("racing"), "tester")
                await session.commit()
                return "posted"
            except service.AccountingError:
                await session.rollback()
                return "blocked"
    close_result, post_result = await asyncio.gather(closer(), writer())
    assert (close_result, post_result) in {("closed", "blocked"), ("stale", "posted")}


async def test_report_snapshot_serializes_concurrent_post_and_close(pg_factory, pg_book, posting):
    from datetime import date

    from modules.accounting import reports

    async with pg_factory() as session:
        await service.post(session, pg_book[0], posting("sale-1", "62", "90.1"), "tester")
        await session.commit()
    rows_read, release_reader, writer_started = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class PausedReader:
        def __init__(self, session):
            self.session = session

        def __getattr__(self, name):
            return getattr(self.session, name)

        async def execute(self, statement):
            result = await self.session.execute(statement)
            rows_read.set()
            await release_reader.wait()
            return result

    async def reader():
        async with pg_factory() as session:
            result = await reports.report(PausedReader(session), pg_book[0],
                                          date(2026, 9, 1), date(2026, 9, 30))
            await session.commit()
            return result

    async def writer():
        await rows_read.wait()
        async with pg_factory() as session:
            writer_started.set()
            await service.post(session, pg_book[0], posting("sale-2", "62", "90.1"), "tester")
            await service.close_period(session, pg_book[0], "2026-09", CloseInput(
                expected_generation=2, evidence={k: "checked" for k in service.CLOSE_STEPS}), "tester")
            await session.commit()

    read_task, write_task = asyncio.create_task(reader()), asyncio.create_task(writer())
    await writer_started.wait()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(write_task), timeout=0.2)
    finally:
        release_reader.set()
    first, _ = await asyncio.gather(read_task, write_task)
    assert first["pnl"]["profit"] == "100.00"
    assert first["status"] == "preliminary"
    async with pg_factory() as session:
        final = await reports.report(session, pg_book[0], date(2026, 9, 1), date(2026, 9, 30))
        assert final["pnl"]["profit"] == "200.00"
        assert final["status"] == "closed_periods"

async def test_completeness_bootstrap_covers_preexisting_receipt_versions(pg_factory, pg_book, posting):
    from core.services.auth import CurrentUser
    from modules.accounting.gateway import AccountingService
    from modules.procurement.receipt_documents import (
        ReceiptCreate,
        ReceiptEdit,
        create_document,
        edit_document,
    )
    from tests.accounting.test_procurement_receipt_drafts import document

    class LegacyGateway(AccountingService):
        async def source_changed(self, *args):
            pass  # Previous primary API predates the completeness registry.

    async with pg_factory() as session:
        access = (session, LegacyGateway(), CurrentUser("tester", ["director"]))
        receipt = await create_document(pg_book[0], ReceiptCreate(key="legacy", document=document()), (session, "tester"), access)
        await session.commit()
        await edit_document(pg_book[0], receipt["id"], ReceiptEdit(expected_version=1, document={**document(), "invoice_reference": "legacy-v2"}), (session, "tester"), access)
        await session.commit()
        assert await session.scalar(text("SELECT count(*) FROM accounting.source_control")) == 0
        # Bootstrap is installed before its guard in the frozen migration.
        # Reproduce that boundary only inside this disposable test database.
        await session.execute(text("DROP TRIGGER guard_source_control ON accounting.source_control"))
        await session.execute(text(Path("modules/accounting/source_control_bootstrap.sql").read_text(encoding="utf-8")))
        await session.execute(text("CREATE TRIGGER guard_source_control BEFORE INSERT OR UPDATE OR DELETE ON accounting.source_control FOR EACH ROW EXECUTE FUNCTION accounting.guard_source_control()"))
        await session.commit()
        assert await session.scalar(text("SELECT version FROM accounting.source_control")) == 2
        with pytest.raises(service.AccountingError, match="Unposted primary"):
            await service.close_period(session, pg_book[0], "2026-09", CloseInput(expected_generation=0, evidence={k: "checked" for k in service.CLOSE_STEPS}), "tester")
        from modules.procurement.receipt_documents import ReceiptPosting

        unrelated = await service.post(session, pg_book[0], posting("unrelated-source"), "tester")
        session.add(ReceiptPosting(receipt_id=receipt["id"], version=2, entry_id=unrelated.id,
                                   options={}, digest=unrelated.digest, actor="tester"))
        await session.flush()
        with pytest.raises(Exception, match="must be reconciled"):
            await session.execute(text(Path("modules/accounting/source_control_bootstrap.sql").read_text(encoding="utf-8")))
        await session.rollback()

async def test_procurement_ownership_unique_and_links_scoped_in_postgres(pg_factory, pg_book):
    from sqlalchemy.exc import DBAPIError, IntegrityError

    from modules.procurement.ownership import OrderRequestLink, PurchaseOwnership

    async def claimant(organization_id):
        async with pg_factory() as session:
            session.add(PurchaseOwnership(organization_id=organization_id, kind="order", source_id=44, snapshot={"number": "PO44"}, evidence="Synthetic decision", actor="tester"))
            try:
                await session.commit()
                return organization_id
            except IntegrityError:
                await session.rollback()
                return None

    outcomes = await asyncio.gather(claimant(pg_book[0]), claimant(pg_book[0] + 100))
    assert outcomes.count(None) == 1
    owner = next(value for value in outcomes if value is not None)
    async with pg_factory() as session:
        order_id = await session.scalar(text("SELECT id FROM procurement.purchase_ownership WHERE kind='order'"))
        request = PurchaseOwnership(organization_id=owner + 1, kind="request", source_id=45, snapshot={}, evidence="Other owner", actor="tester")
        session.add(request)
        await session.commit()
        request_id = request.id
        session.add(OrderRequestLink(organization_id=owner, order_ownership_id=order_id, request_ownership_id=request_id, evidence="Invalid cross-book link", actor="tester"))
        with pytest.raises(DBAPIError, match="same organization"):
            await session.commit()
        await session.rollback()
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text("UPDATE procurement.purchase_ownership SET evidence='changed'"))
        await session.rollback()
        from modules.procurement.receipt_documents import ReceiptDocument, ReceiptRevision
        from tests.accounting.test_procurement_receipt_drafts import document

        header = ReceiptDocument(organization_id=owner + 1, source_key="foreign-order", current_version=1, status="draft", created_by="tester")
        session.add(header)
        await session.flush()
        facts = document()
        facts["items"][0]["order_id"] = 44
        session.add(ReceiptRevision(receipt_id=header.id, version=1, document=facts, actor="tester"))
        with pytest.raises(DBAPIError, match="Receipt orders must belong"):
            await session.flush()
        await session.rollback()

async def test_ownership_preview_rechecks_after_other_company_claim(pg_factory, pg_book, monkeypatch):
    from fastapi import HTTPException

    from core.services.auth import CurrentUser
    from modules.accounting.gateway import AccountingService
    from modules.accounting.models import AccessGrant, Organization
    from modules.procurement import ownership
    from modules.procurement.models import PurchaseOrder

    async with pg_factory() as setup:
        connection = await setup.connection()
        await connection.run_sync(lambda sync: PurchaseOrder.__table__.create(sync, checkfirst=True))
        setup.add(Organization(id=1009, name="Other synthetic book", unp="999999998"))
        await setup.flush()
        setup.add(AccessGrant(id=1009, organization_id=1009, subject="tester", role="chief"))
        setup.add(PurchaseOrder(id=44, number="Race source", supplier="Synthetic"))
        await setup.commit()
    entered, release = asyncio.Event(), asyncio.Event()
    original = ownership.source_snapshot
    async with pg_factory() as reader:
        async def pause_before_source_lock(session, kind, source_id):
            if session is reader:
                entered.set()
                await release.wait()
            return await original(session, kind, source_id)
        monkeypatch.setattr(ownership, "source_snapshot", pause_before_source_lock)
        data = ownership.OwnershipInput(kind="order", source_id=44, evidence="Synthetic proof")
        async def preview():
            with pytest.raises(HTTPException) as error:
                await ownership.preview_ownership(pg_book[0], data, (reader, AccountingService(), CurrentUser("tester", ["director"])))
            assert error.value.status_code == 409
            await reader.rollback()
        pending = asyncio.create_task(preview())
        await entered.wait()
        try:
            async with pg_factory() as writer:
                await ownership.assign_ownership(1009, data, (writer, AccountingService(), CurrentUser("tester", ["director"])))
                await writer.commit()
        finally:
            release.set()
        await pending

@pytest.mark.parametrize("competitor", ["complete", "adjustment"])
async def test_inventory_posting_serializes_with_competing_writer(pg_factory, pg_book, competitor):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from core.domain.models import Sku
    from core.runtime.deps import get_session
    from core.services.auth import CurrentUser, get_current_user
    from modules.accounting.gateway import AccountingService
    from modules.wms.models import StockMovement
    from modules.wms.routes import router

    async with pg_factory() as session:
        connection = await session.connection()
        def catalog(sync):
            Sku.metadata.tables["ref_nomenclature_category"].create(sync)
            Sku.__table__.create(sync)
        await connection.run_sync(catalog)
        session.add(StockMovement(organization_id=pg_book[0], sku_code="A", warehouse="Test",
                                  kind="in", qty="30", reason="receipt"))
        await session.commit()
    app = FastAPI()
    app.include_router(router, prefix="/wms")
    app.state.core = SimpleNamespace(services=SimpleNamespace(accounting=AccountingService()))
    async def sessions():
        async with pg_factory() as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["director"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/wms/inventory", json={"organization_id": pg_book[0],
            "warehouse": "Test", "expected_source": "wms_physical", "journal_complete": True,
            "source_evidence": "Synthetic PostgreSQL physical journal"})
        assert created.status_code == 201, created.text
        count_id = created.json()["id"]
        populated = await client.post(f"/wms/inventory/{count_id}/populate")
        assert populated.status_code == 200, populated.text
        line_id = populated.json()["lines"][0]["id"]
        edited = await client.patch(f"/wms/inventory/lines/{line_id}", json={"counted_qty": 27})
        assert edited.status_code == 200, edited.text
        competing = (client.post(f"/wms/inventory/{count_id}/complete") if competitor == "complete"
                     else client.post("/wms/adjustment", json={"organization_id": pg_book[0],
                          "warehouse": "Test", "sku_code": "A", "qty": "5"}))
        posted, other = await asyncio.gather(client.post(f"/wms/inventory/{count_id}/complete"), competing)
        if competitor == "complete":
            assert [posted.status_code, other.status_code] == [200, 200], [posted.text, other.text]
        else:
            assert other.status_code == 201, other.text
            assert posted.status_code in {200, 409}, posted.text
    async with pg_factory() as session:
        movements = (await session.scalars(select(StockMovement))).all()
        adjustments = [m for m in movements if m.reason == "adjustment"]
        assert len(adjustments) == (1 if posted.status_code == 200 else 0)
        assert all(m.organization_id == pg_book[0] for m in movements)
        if adjustments:
            assert adjustments[0].kind == "out" and adjustments[0].qty == 3
        total = sum(m.qty if m.kind == "in" else -m.qty for m in movements)
        assert total == (27 if competitor == "complete" else 32 if adjustments else 35)


async def test_invoice_reservation_concurrent_replay_and_stale_completed_pick(pg_factory, pg_book):
    from sqlalchemy import select

    from modules.sales.models import DealDocument
    from modules.wms.events import on_stock_released, on_stock_reserved
    from modules.wms.models import StockMovement, Task
    from modules.wms.reservation_events import ReservationEventState, ReservationPick
    from tests.reservation_source import event_context, invoice

    items = [{"sku_code": "PG-RESERVE", "warehouse": "Test", "qty": "2"}]
    payload = {"document_id": 1, "organization_id": pg_book[0], "items": items}
    async with pg_factory() as session:
        await invoice(session, 1, items, pg_book[0])
        await session.commit()
    async def deliver():
        async with pg_factory() as session:
            await on_stock_reserved(payload, event_context(session))
            await session.commit()
    await asyncio.gather(deliver(), deliver())
    async with pg_factory() as stale:
        tasks = (await stale.scalars(select(Task).join(ReservationPick))).all()
        assert len(tasks) == 1 and tasks[0].organization_id == pg_book[0]
        assert tasks[0].status == "open"
        await stale.commit()  # Keep cached object, release transaction before the competing writer.
        async with pg_factory() as writer:
            task = await writer.get(Task, tasks[0].id)
            task.status = "done"
            doc = await writer.get(DealDocument, 1)
            doc.reserve_status = "released"
            await writer.commit()
        assert tasks[0].status == "open"
        with pytest.raises(ValueError, match="picking already started"):
            await on_stock_released(payload, event_context(stale))
        await stale.rollback()
    async with pg_factory() as session:
        assert await session.scalar(select(Task.status)) == "done"
        assert (await session.get(ReservationEventState, 1)).state == "reserved"
        assert await session.scalar(select(StockMovement.id)) is None


async def test_reservation_event_waits_for_organization_before_locking_deal(pg_factory, pg_book):
    from sqlalchemy import select

    from modules.sales.models import Deal
    from modules.wms.events import on_stock_reserved
    from modules.wms.models import Task
    from tests.reservation_source import event_context, invoice

    items = [{"sku_code": "ORG-FIRST", "warehouse": "Test", "qty": "2"}]
    async with pg_factory() as session:
        doc = await invoice(session, 1, items, pg_book[0])
        deal_id = doc.deal_id
        await session.commit()
    ready = asyncio.Event()
    consumer_pid = []

    async def consume():
        async with pg_factory() as session:
            consumer_pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
            ready.set()
            await on_stock_reserved({"document_id": 1, "items": items}, event_context(session))
            await session.commit()

    task = None
    try:
        async with pg_factory() as holder:
            await service.lock_organization(holder, pg_book[0])
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            task = asyncio.create_task(consume())
            await asyncio.wait_for(ready.wait(), 5)

            async def blocked():
                while holder_pid not in await holder.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": consumer_pid[0]},
                ):
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(blocked(), 5)
            # If the consumer locked deal first, this NOWAIT would fail and the
            # opposing org->deal writer could deadlock. Do not infer from sleeps.
            async with pg_factory() as probe:
                assert await probe.scalar(select(Deal.id).where(Deal.id == deal_id)
                                          .with_for_update(nowait=True)) == deal_id
            await holder.commit()
        await asyncio.wait_for(task, 5)
        async with pg_factory() as session:
            assert await session.scalar(select(Task.organization_id)) == pg_book[0]
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_addressed_invoice_allocations_cannot_overbook_concurrently(pg_factory, pg_book):
    from fastapi import HTTPException
    from sqlalchemy import select

    from core.services.auth import CurrentUser
    from modules.accounting.gateway import AccountingService
    from modules.sales.reservation_source import SalesReservationSource
    from modules.wms.invoice_reservations import InvoiceReservation, ReserveInput, reserve
    from modules.wms.models import ReservationVersion, StockMovement
    from tests.reservation_source import invoice

    async with pg_factory() as session:
        for document_id in (1, 2):
            await invoice(session, document_id, [{"sku_code": "A", "qty": "5"}], pg_book[0])
        session.add(StockMovement(organization_id=pg_book[0], sku_code="A", warehouse="W",
                                  kind="in", qty="6", reason="receipt"))
        await session.commit()
    async def allocate(document_id):
        async with pg_factory() as session:
            actor = await AccountingService().source_member(session, pg_book[0], CurrentUser("tester", ["director"]))
            source = await SalesReservationSource().invoice_reservation(session, document_id)
            try:
                await reserve(session, pg_book[0], source, ReserveInput(allocations=[
                    {"line_no": 1, "warehouse": "W", "qty": "5"}], journal_complete=True,
                    evidence="Synthetic physical journal"), actor)
                await session.commit()
                return 201
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code
    assert sorted(await asyncio.gather(allocate(1), allocate(2))) == [201, 409]
    async with pg_factory() as session:
        assert len((await session.scalars(select(InvoiceReservation))).all()) == 1
        rows = (await session.scalars(select(ReservationVersion))).all()
        assert len(rows) == 1 and rows[0].qty == 5 and rows[0].organization_id == pg_book[0]
        physical = (await session.scalars(select(StockMovement))).all()
        assert len(physical) == 1 and physical[0].qty == 6


async def test_wms_concurrent_accept_preserves_owner_without_duplicate_moves(pg_factory, pg_book):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from core.runtime.deps import get_session
    from core.services.auth import CurrentUser, get_current_user
    from modules.accounting.gateway import AccountingService
    from modules.wms.models import Receipt, ReceiptLine, StockMovement, Task
    from modules.wms.routes import router
    async with pg_factory() as session:
        receipt = Receipt(organization_id=pg_book[0], number="PG-WMS", source="procurement", entity_ref="purchase_order:1:1", warehouse="Test")
        session.add(receipt)
        await session.flush()
        receipt_id = receipt.id
        session.add(ReceiptLine(receipt_id=receipt.id, sku_code="A", expected_qty="1.25"))
        await session.commit()
    app = FastAPI()
    app.include_router(router, prefix="/wms")
    app.state.core = SimpleNamespace(services=SimpleNamespace(accounting=AccountingService()))
    async def sessions():
        async with pg_factory() as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["director"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(*(client.post(f"/wms/receipts/{receipt_id}/accept") for _ in range(2)))
        assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
        assert all(r.json()["organization_id"] == pg_book[0] for r in responses)
    async with pg_factory() as session:
        moves = (await session.scalars(select(StockMovement))).all()
        tasks = (await session.scalars(select(Task))).all()
        assert len(moves) == len(tasks) == 1
        assert moves[0].organization_id == tasks[0].organization_id == pg_book[0]


async def test_wms_event_retry_after_rollback_and_concurrent_replay(pg_factory, pg_book):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent, Sku
    from core.services.eventbus import EventContext, OutboxEventBus
    from modules.wms.events import on_goods_received
    from modules.wms.models import Receipt, ReceiptLine

    async with pg_factory() as session:
        conn = await session.connection()
        def catalog(sync):
            Sku.metadata.tables["ref_nomenclature_category"].create(sync)
            Sku.__table__.create(sync)
        await conn.run_sync(catalog)
        event = OutboxEvent(event_type="procurement.received", payload={"organization_id": pg_book[0], "item": "A", "qty": "1.25", "entity_ref": "purchase_order:1:1"})
        session.add(event)
        await session.commit()
        event_id, payload = event.id, event.payload
    bus = OutboxEventBus()
    bus.subscribe("procurement.received", on_goods_received)
    async def fail_after_receipt(payload, ctx):
        await ctx.session.flush()
        raise RuntimeError("synthetic downstream failure")
    bus.subscribe("procurement.received", fail_after_receipt)
    async with pg_factory() as session:
        with pytest.raises(RuntimeError, match="synthetic downstream"):
            await bus.relay_once(session, EventContext(session, None))
        await session.rollback()
    async with pg_factory() as session:
        assert await session.scalar(select(Receipt.id)) is None
        assert (await session.get(OutboxEvent, event_id)).processed_at is None
    async def replay():
        async with pg_factory() as session:
            await on_goods_received(payload, EventContext(session, None, event_id=event_id))
            await session.commit()
    await asyncio.gather(replay(), replay())
    async with pg_factory() as session:
        receipts = (await session.scalars(select(Receipt))).all()
        lines = (await session.scalars(select(ReceiptLine))).all()
        assert len(receipts) == len(lines) == 1
        assert receipts[0].source_event_id == event_id
        assert receipts[0].organization_id == pg_book[0]
        assert str(lines[0].expected_qty) == "1.25"


async def test_wms_qc_concurrent_stale_snapshot_cannot_overwrite(pg_factory, pg_book):
    from fastapi import HTTPException

    from core.services.auth import CurrentUser
    from modules.accounting.gateway import AccountingService
    from modules.wms.models import Receipt, ReceiptLine
    from modules.wms.organization import qc_revision
    from modules.wms.routes import qc_receipt
    from modules.wms.schemas import QcDecisionIn

    async with pg_factory() as session:
        receipt = Receipt(organization_id=pg_book[0], status="pending_qc")
        session.add(receipt)
        await session.flush()
        line = ReceiptLine(receipt_id=receipt.id, sku_code="A", expected_qty="10")
        session.add(line)
        await session.commit()
        await session.refresh(line)
        receipt_id, line_id = receipt.id, line.id
        revision = qc_revision(receipt, [line])
    async def write(amount):
        async with pg_factory() as session:
            try:
                await qc_receipt(receipt_id, QcDecisionIn(expected_revision=revision, decisions=[{"line_id": line_id, "accepted_qty": amount}]),
                                 session=session, core=SimpleNamespace(services=SimpleNamespace(accounting=AccountingService())), _=CurrentUser("tester", ["director"]))
                return 200, amount
            except HTTPException as error:
                await session.rollback()
                return error.status_code, amount
    results = await asyncio.gather(write("7.50"), write("6.25"))
    assert sorted(status for status, _ in results) == [200, 409]
    async with pg_factory() as session:
        line = await session.get(ReceiptLine, line_id)
        assert str(line.accepted_qty) == next(amount for status, amount in results if status == 200)


async def test_wms_location_guard_holds_lock_and_rejects_stale_cached_location(pg_factory):
    from fastapi import HTTPException
    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError

    from modules.wms.models import Location
    from modules.wms.routes import _validate_movement_locations

    async with pg_factory() as session:
        location = Location(warehouse="Own", code="GUARD", is_active=True)
        session.add(location)
        await session.commit()
        location_id = location.id
    async with pg_factory() as reader, pg_factory() as writer:
        cached = await reader.get(Location, location_id)
        await _validate_movement_locations(reader, "Own", location_id)
        # A second transaction cannot deactivate the cell while a movement's
        # validation transaction holds its row lock.
        await writer.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(DBAPIError) as blocked:
            await writer.execute(update(Location).where(Location.id == location_id).values(is_active=False))
        assert getattr(blocked.value.orig, "sqlstate", None) == "55P03"
        await writer.rollback()
        await reader.commit()
        await writer.execute(update(Location).where(Location.id == location_id).values(is_active=False))
        await writer.commit()
        # expire_on_commit=False deliberately leaves reader's ORM identity stale.
        assert cached.is_active is True
        with pytest.raises(HTTPException) as rejected:
            await _validate_movement_locations(reader, "Own", location_id)
        assert rejected.value.status_code == 422
        assert cached.is_active is False
        await reader.rollback()


@pytest.mark.parametrize("actor", ["tester", "x" * 129])
async def test_reservation_concurrent_replay_and_immutable_history(pg_factory, pg_book, actor):
    from sqlalchemy import select
    from sqlalchemy.exc import DBAPIError

    from core.services.auth import CurrentUser
    from core.services.eventbus import OutboxEventBus
    from modules.accounting.gateway import AccountingService
    from modules.wms.models import ReservationVersion, StockMovement
    from modules.wms.reservations import ReservationInput, record_reservation

    if actor != "tester":
        from modules.accounting.models import AccessGrant
        async with pg_factory() as session:
            grant = await session.scalar(select(AccessGrant).where(AccessGrant.organization_id == pg_book[0], AccessGrant.subject == "tester"))
            grant.subject = actor
            await session.commit()
    core = SimpleNamespace(services=SimpleNamespace(accounting=AccountingService()), event_bus=OutboxEventBus())
    payload = ReservationInput(organization_id=pg_book[0], source="synthetic:line:1", version=1, sku_code="A", warehouse="Own", qty="3.25", evidence="Synthetic proof")
    async def write():
        async with pg_factory() as session:
            return await record_reservation(payload, session=session, core=core, user=CurrentUser(actor, ["director"]))
    results = await asyncio.gather(write(), write())
    assert results[0]["id"] == results[1]["id"]
    assert results[0]["actor"] == actor
    async with pg_factory() as session:
        assert len((await session.scalars(select(ReservationVersion))).all()) == 1
        assert await session.scalar(select(StockMovement.id)) is None
    for sql in ["UPDATE wms.reservation_version SET qty = 99", "DELETE FROM wms.reservation_version", "TRUNCATE wms.reservation_version CASCADE"]:
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="Reservation versions are immutable"):
                await session.execute(text(sql))
            await session.rollback()


async def test_fx_revaluation_receipt_is_immutable_and_matches_posting(pg_factory, pg_book):
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import select
    from sqlalchemy.exc import DBAPIError

    from modules.accounting import fx_revaluation
    from modules.accounting.models import Account, Entry, FxRevaluationReceipt, Policy
    from modules.accounting.schemas import (
        FxRevaluationConfirmInput,
        FxRevaluationInput,
        LineInput,
        PostingInput,
    )

    async with pg_factory() as session:
        session.add_all([
            Account(id=2001, organization_id=pg_book[0], code="91.1", title="Synthetic FX gain", category="income",
                    valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
            Account(id=2002, organization_id=pg_book[0], code="91.2", title="Synthetic FX loss", category="expense",
                    valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
        ])
        fx_policy_id = 2001
        session.add(Policy(
            id=fx_policy_id, organization_id=pg_book[0], effective_from=date(2026, 2, 1),
            reference="Synthetic FX policy", inventory_method="specific", allocation_basis="direct_cost",
            depreciation_method="straight_line", normative_reference="Synthetic FX policy",
            normative_verified=True, approved_by="tester", currency_revaluation={
                "monetary_accounts": ["60", "62"], "gain_account": "91.1", "loss_account": "91.2",
                "gain_dimensions": {}, "loss_dimensions": {}, "reference": "Synthetic reviewed FX instruction",
            },
        ))
        session.add(Currency(code="USD", title="Synthetic USD"))
        await session.flush()
        posting = PostingInput(
            source="pg-fx-source", source_version=1, operation="manual",
            document_date=date(2026, 9, 30), operation_date=date(2026, 9, 30), posting_date=date(2026, 9, 30),
            policy_id=fx_policy_id, rule_version="synthetic-v1", explanation="Synthetic foreign transaction",
            lines=[
                LineInput(account="62", side="debit", amount=Decimal("300.00"), currency="USD",
                          original_amount=Decimal("100.00"), rate=Decimal("3.00"), rate_scale=1,
                          rate_date=date(2026, 9, 30), rate_source="Synthetic source rate"),
                LineInput(account="60", side="credit", amount=Decimal("300.00"), currency="USD",
                          original_amount=Decimal("100.00"), rate=Decimal("3.00"), rate_scale=1,
                          rate_date=date(2026, 9, 30), rate_source="Synthetic source rate"),
            ],
        )
        await service.post(session, pg_book[0], posting, "tester")
        await session.commit()

    command = FxRevaluationInput(
        request_key=uuid4(), policy_id=fx_policy_id, posting_date=date(2026, 9, 30), expected_generation=1,
        rates=[{"currency": "USD", "rate": "3.20", "rate_scale": 1,
                "rate_date": "2026-09-30", "rate_source": "Synthetic central-bank evidence"}],
        evidence="Synthetic reviewed rate evidence",
    )
    async with pg_factory() as session:
        plan = await fx_revaluation.preview(session, pg_book[0], "2026-09", command)
        receipt = await fx_revaluation.confirm(session, pg_book[0], "2026-09", FxRevaluationConfirmInput(
            **command.model_dump(), basis_digest=plan["basis_digest"], digest=plan["digest"],
        ), "tester")
        await session.commit()
        assert receipt.entry_id is not None
        assert await session.scalar(select(Entry.operation).where(Entry.id == receipt.entry_id)) == "fx_revaluation"
        assert await session.scalar(select(FxRevaluationReceipt.digest).where(
            FxRevaluationReceipt.id == receipt.id)) == receipt.digest

    for statement in (
        "UPDATE accounting.fx_revaluation_receipt SET actor='forged' WHERE request_key=:key",
        "DELETE FROM accounting.fx_revaluation_receipt WHERE request_key=:key",
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement), {"key": str(command.request_key)})
            await session.rollback()
