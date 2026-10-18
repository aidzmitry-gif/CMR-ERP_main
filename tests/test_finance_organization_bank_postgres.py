"""Real PostgreSQL bank locks in disposable, synthetic-only databases.

This exercises current ORM constraints, not the production migration path.
"""
import asyncio
import os
import runpy
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.settings import get_settings
from core.db.base import Base
from core.domain.models import IdentityInvitationRequest, OutboxEvent, User
from core.runtime.deps import get_core, get_session
from core.services.auth import CurrentUser, get_current_user
from core.services.eventbus import OutboxEventBus
from modules.accounting.gateway import AccountingService
from modules.accounting.models import AccessGrant, Organization, SourceBinding
from modules.finance.models import BankAccount, BankTransaction, Payment, PaymentAllocation
from modules.finance.routes import router


@pytest_asyncio.fixture
async def native_bank_factory(request):
    url = os.getenv("ACCOUNTING_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Isolated PostgreSQL acceptance requires ACCOUNTING_TEST_POSTGRES_URL")
    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost"} or parsed.database != "accounting_test":
        pytest.fail("Refusing a non-local/non-test PostgreSQL target")
    assert get_settings().auth_mode == "dev", "Persisted development identity must be rechecked"
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    database = "acc_test_" + uuid4().hex
    marker = f"crm-acc-fixture:{database}"
    engine = None
    created = False
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{database}"'))
            created = True
            await conn.execute(text(f"COMMENT ON DATABASE \"{database}\" IS '{marker}'"))
        engine = create_async_engine(
            parsed.set(database=database),
            connect_args={"options": "-c statement_timeout=15000 -c lock_timeout=12000"},
        )
        async with engine.begin() as conn:
            version = int(await conn.scalar(text("SHOW server_version_num")))
            assert 160000 <= version < 170000, "PostgreSQL 16 acceptance is required"
            await conn.execute(text("CREATE SCHEMA accounting"))
            await conn.execute(text("CREATE SCHEMA finance"))

            def create_tables(connection):
                # Explicit FK order; the old accounting bootstrap creates Finance
                # before its new organization FK target and is not applicable.
                for model in (
                    User, IdentityInvitationRequest, OutboxEvent,
                    Organization, AccessGrant, SourceBinding,
                    BankAccount, Payment, PaymentAllocation, BankTransaction,
                ):
                    model.__table__.create(connection)

            def create_legacy_tables(connection):
                for model in (User, IdentityInvitationRequest, OutboxEvent, Organization, AccessGrant, SourceBinding):
                    model.__table__.create(connection)
                # Start from the existing Payment columns, then use actual 0075
                # to build its historical account reference and account table.
                legacy = Payment.__table__.to_metadata(MetaData(naming_convention=Base.metadata.naming_convention))
                assert {"organization_id", "account_id"} <= set(legacy.c.keys())
                for constraint in list(legacy.constraints):
                    if {"organization_id", "account_id"} & set(constraint.columns.keys()) or "organization_id" in str(getattr(constraint, "sqltext", "")):
                        legacy.constraints.remove(constraint)
                for index in list(legacy.indexes):
                    if {"organization_id", "account_id"} & set(index.columns.keys()):
                        legacy.indexes.remove(index)
                for column in ("organization_id", "account_id"):
                    legacy._columns.remove(legacy.c[column])
                legacy.create(connection)
                old = Path(__file__).resolve().parents[1] / "migrations/versions/0075_finance_bank_account.py"
                context = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
                with Operations.context(context):
                    runpy.run_path(str(old))["upgrade"]()
                for model in (PaymentAllocation, BankTransaction):
                    model.__table__.create(connection)

            mode = getattr(request, "param", "current_orm")
            assert mode in {"current_orm", "migration_0196"}
            await conn.run_sync(create_legacy_tables if mode == "migration_0196" else create_tables)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        try:
            if engine is not None:
                await engine.dispose()
            if created:
                async with admin.connect() as conn:
                    actual = await conn.scalar(text(
                        "SELECT shobj_description(oid, 'pg_database') "
                        "FROM pg_database WHERE datname=:name"
                    ), {"name": database})
                    assert actual == marker, "Disposable database ownership marker changed"
                    # Pool disconnect visibility may lag; this is cleanup polling,
                    # never a timing assumption in the concurrency proof below.
                    for _ in range(20):
                        active = await conn.scalar(text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=:name"
                        ), {"name": database})
                        if not active:
                            break
                        await asyncio.sleep(0.1)
                    assert active == 0, "Disposable database still has live connections"
                    await conn.execute(text(f'DROP DATABASE "{database}"'))
                    assert await conn.scalar(text(
                        "SELECT count(*) FROM pg_database WHERE datname=:name"
                    ), {"name": database}) == 0
                    assert await conn.scalar(text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=:name"
                    ), {"name": database}) == 0
        finally:
            await admin.dispose()


async def _concurrent_matches(factory, second_tx):
    actor = "native-finance-chief"
    async with factory() as session:
        session.add(User(username=actor, full_name="Synthetic native actor", role="director", status="active"))
        session.add(Organization(id=1, name="Synthetic native organization", unp="000000001"))
        await session.flush()
        session.add(AccessGrant(organization_id=1, subject=actor, role="chief"))
        session.add(Payment(id=21, organization_id=1, ref="native-payment", amount=Decimal("10.00")))
        for identity, amount in ((31, "4.01"), (32, "5.99")):
            session.add(BankTransaction(
                id=identity, ext_id=f"native-bank-{identity}", amount=Decimal(amount),
                currency="BYN", occurred_on=date(2026, 7, 1), direction="receipt",
            ))
            session.add(SourceBinding(
                organization_id=1, source_type="finance_bank_transaction", source_id=identity,
                ownership="own", evidence="Synthetic explicit source confirmation", actor=actor,
            ))
        await session.commit()
        original_bindings = (await session.execute(select(
            SourceBinding.id, SourceBinding.organization_id, SourceBinding.source_type,
            SourceBinding.source_id, SourceBinding.ownership, SourceBinding.evidence, SourceBinding.actor,
            SourceBinding.created_at,
        ).order_by(SourceBinding.id))).all()

    before_commit, release = asyncio.Event(), asyncio.Event()
    pids, pid_ready = {}, {1: asyncio.Event(), 2: asyncio.Event()}
    user = CurrentUser(actor, ["director"], local_status="active")
    core = SimpleNamespace(services=SimpleNamespace(accounting=AccountingService()), event_bus=OutboxEventBus())
    app = FastAPI()
    app.include_router(router, prefix="/finance")

    async def db(request: Request):
        ordinal = int(request.headers["x-native-request"])
        async with factory() as session:
            pids[ordinal] = await session.scalar(text("SELECT pg_backend_pid()"))
            pid_ready[ordinal].set()
            commit = session.commit

            async def held_commit():
                if ordinal == 1:
                    before_commit.set()
                    await release.wait()
                await commit()

            session.commit = held_commit
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_core] = lambda: core
    tasks = []
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://fixture") as client:
        async def post(tx, ordinal):
            return await client.post(
                f"/finance/bank/transactions/{tx}/match", params={"organization_id": 1},
                json={"payment_id": 21}, headers={"x-native-request": str(ordinal)},
            )

        try:
            first = asyncio.create_task(post(31, 1))
            tasks.append(first)
            async with asyncio.timeout(15):
                await before_commit.wait()
            assert not first.done()
            second = asyncio.create_task(post(second_tx, 2))
            tasks.append(second)
            async with asyncio.timeout(15):
                await pid_ready[2].wait()
                async with factory() as observer:
                    while True:
                        assert not second.done(), "Second request finished before PostgreSQL lock observation"
                        blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[2]})
                        if pids[1] in blockers:
                            break
            release.set()
            async with asyncio.timeout(20):
                responses = await asyncio.gather(first, second)
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async with factory() as session:
        payment = await session.get(Payment, 21)
        allocations = (await session.scalars(select(PaymentAllocation).order_by(PaymentAllocation.id))).all()
        transactions = (await session.scalars(select(BankTransaction).order_by(BankTransaction.id))).all()
        events = (await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id))).all()
        bindings = (await session.execute(select(
            SourceBinding.id, SourceBinding.organization_id, SourceBinding.source_type,
            SourceBinding.source_id, SourceBinding.ownership, SourceBinding.evidence, SourceBinding.actor,
            SourceBinding.created_at,
        ).order_by(SourceBinding.id))).all()
        assert bindings == original_bindings
        assert payment.organization_id == 1 and payment.amount == Decimal("10.00")
        assert all(row.payment_id == payment.id for row in allocations)
        assert all(event.payload["organization_id"] == 1 for event in events)
        return responses, payment, allocations, transactions, events


async def test_same_bank_transaction_concurrent_manual_match_once(native_bank_factory):
    responses, payment, allocations, transactions, events = await _concurrent_matches(native_bank_factory, 31)
    assert [response.status_code for response in responses] == [200, 409]
    assert responses[0].json()["organization_id"] == 1
    assert len(allocations) == 1 and allocations[0].amount == Decimal("4.01")
    assert payment.organization_id == 1 and payment.status == "partial" and payment.paid_at is None
    assert [(row.event_type, row.payload["amount"], row.payload["outstanding"]) for row in events] == [
        ("finance.payment.received", "4.01", "5.99"),
    ]
    assert transactions[0].match_status == "manual" and transactions[0].payment_id == payment.id
    assert transactions[0].allocation_id == allocations[0].id
    assert transactions[1].match_status == "unmatched"
    assert transactions[1].payment_id is None and transactions[1].allocation_id is None


async def test_different_bank_transactions_concurrent_same_payment(native_bank_factory):
    responses, payment, allocations, transactions, events = await _concurrent_matches(native_bank_factory, 32)
    assert [response.status_code for response in responses] == [200, 200]
    assert all(response.json()["organization_id"] == 1 for response in responses)
    assert len(allocations) == 2 and len({row.id for row in allocations}) == 2
    assert sum((row.amount for row in allocations), Decimal("0")) == Decimal("10.00")
    assert all(row.payment_id == payment.id for row in allocations)
    assert payment.organization_id == 1 and payment.status == "paid" and payment.paid_at is not None
    assert [row.event_type for row in events] == ["finance.payment.received", "finance.payment.received", "finance.payment.paid"]
    received = [row.payload for row in events if row.event_type == "finance.payment.received"]
    assert [Decimal(row["amount"]) for row in received] == [Decimal("4.01"), Decimal("5.99")]
    assert [Decimal(row["outstanding"]) for row in received] == [Decimal("5.99"), Decimal("0")]
    assert all(row.match_status == "manual" and row.payment_id == payment.id for row in transactions)
    assert {row.allocation_id for row in transactions} == {row.id for row in allocations}
    by_id = {row.id: row for row in allocations}
    assert all(by_id[row.allocation_id].amount == row.amount for row in transactions)


@pytest.mark.parametrize("native_bank_factory", ["migration_0196"], indirect=True)
async def test_finance_organization_migration_roundtrip(native_bank_factory):
    """Real Operations upgrade/guarded downgrade; prepared Finance predecessor only."""
    root = Path(__file__).resolve().parents[1]
    migration = runpy.run_path(str(root / "migrations/versions/0196_finance_organization_ownership.py"))
    assert migration["revision"] == "0196" and migration["down_revision"] == "0195"

    async def apply(session, function):
        connection = await session.connection()
        def migrate(sync_connection):
            context = MigrationContext.configure(sync_connection, opts={"target_metadata": Base.metadata})
            with Operations.context(context):
                function()
        await connection.run_sync(migrate)

    async def shape(session):
        connection = await session.connection()
        def read(sync_connection):
            inspector = inspect(sync_connection)
            return {table: {
                "columns": {c["name"]: c["nullable"] for c in inspector.get_columns(table, schema="finance")},
                "fks": {c["name"]: c for c in inspector.get_foreign_keys(table, schema="finance", postgresql_ignore_search_path=True)},
                "unique": {c["name"]: c["column_names"] for c in inspector.get_unique_constraints(table, schema="finance")},
                "checks": {c["name"] for c in inspector.get_check_constraints(table, schema="finance")},
                "indexes": {c["name"] for c in inspector.get_indexes(table, schema="finance")},
            } for table in ("payment", "bank_account")}
        return await connection.run_sync(read)

    async def snapshots(session):
        return [await session.scalar(text(f"SELECT to_jsonb(row) FROM finance.{table} row WHERE id=:id"), {"id": ident})
                for table, ident in (("bank_account", 41), ("payment", 51))]

    async with native_bank_factory() as session:
        before_shape = await shape(session)
        assert before_shape["bank_account"]["unique"] == {"uq_bank_account_code": ["code"]}
        assert before_shape["payment"]["fks"]["fk_payment_account_id_bank_account"]["options"]["ondelete"] == "SET NULL"
        await session.execute(text("INSERT INTO finance.bank_account(id,code,title) VALUES (41,'synthetic-legacy','Synthetic legacy account')"))
        await session.execute(text("INSERT INTO finance.payment(id,ref,amount,account_id) VALUES (51,'Synthetic legacy payment',12.34,41)"))
        before_rows = await snapshots(session)
        await session.commit()
        await apply(session, migration["upgrade"])
        await session.commit()
        after_rows = await snapshots(session)
        assert all(row.pop("organization_id") is None for row in after_rows)
        assert after_rows == before_rows
        target = await shape(session)
        for table in ("payment", "bank_account"):
            assert target[table]["columns"]["organization_id"] is True
            assert f"fk_{table}_organization_id_organization" in target[table]["fks"]
            assert f"ix_finance_{table}_organization_id" in target[table]["indexes"]
            assert f"ck_{table}_ck_finance_{table}_organization_positive" in target[table]["checks"]
        assert "uq_bank_account_code" not in target["bank_account"]["unique"]
        assert target["bank_account"]["unique"]["uq_finance_bank_account_organization_code"] == ["organization_id", "code"]
        assert target["bank_account"]["unique"]["uq_finance_bank_account_organization_id"] == ["organization_id", "id"]
        composite = target["payment"]["fks"]["fk_finance_payment_account_organization"]
        assert composite["constrained_columns"] == ["organization_id", "account_id"]
        assert composite["referred_columns"] == ["organization_id", "id"]
        assert composite["options"]["ondelete"] == "RESTRICT"
        assert target["payment"]["fks"]["fk_payment_account_id_bank_account"]["options"]["ondelete"] == "RESTRICT"
        session.add_all([Organization(id=7, name="Synthetic seven", unp="900000007"), Organization(id=9, name="Synthetic nine", unp="900000009")])
        await session.flush()
        await session.execute(text("INSERT INTO finance.bank_account(id,organization_id,code,title) VALUES (71,7,'same','Synthetic seven'),(91,9,'same','Synthetic nine')"))
        await session.execute(text("INSERT INTO finance.payment(id,organization_id,ref,amount,account_id) VALUES (72,7,'Synthetic owned payment',5.00,71)"))
        await session.commit()
        for sql in (
            "INSERT INTO finance.payment(organization_id,ref,account_id) VALUES (7,'Synthetic cross book',91)",
            "INSERT INTO finance.bank_account(organization_id,code,title) VALUES (7,'same','Synthetic duplicate')",
            "INSERT INTO finance.bank_account(organization_id,code,title) VALUES (999,'unknown','Synthetic unknown book')",
            "INSERT INTO finance.payment(organization_id,ref) VALUES (0,'Synthetic zero book')",
            "DELETE FROM finance.bank_account WHERE id=71",
        ):
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(text(sql))
        with pytest.raises(RuntimeError, match="ownership cannot be discarded"):
            async with session.begin_nested():
                await apply(session, migration["downgrade"])
        assert await shape(session) == target
        await session.commit()

    # A fresh session proves refusal preserved committed owners and original rows.
    async with native_bank_factory() as session:
        assert await session.scalar(text("SELECT organization_id FROM finance.payment WHERE id=72")) == 7
        assert await session.scalar(text("SELECT account_id FROM finance.payment WHERE id=72")) == 71
        assert await session.scalar(text("SELECT count(*) FROM finance.bank_account WHERE organization_id IS NOT NULL")) == 2
        await session.execute(text("DELETE FROM finance.payment WHERE id=72"))
        await session.execute(text("DELETE FROM finance.bank_account WHERE id IN (71,91)"))
        await session.execute(text("INSERT INTO finance.bank_account(id,code,title) VALUES (61,'synthetic-legacy','Synthetic duplicate legacy')"))
        await session.commit()
        with pytest.raises(RuntimeError, match="Duplicate legacy account codes"):
            async with session.begin_nested():
                await apply(session, migration["downgrade"])
        assert await shape(session) == target
        assert await session.scalar(text("SELECT count(*) FROM finance.bank_account WHERE code='synthetic-legacy'")) == 2
        await session.commit()
        await session.execute(text("DELETE FROM finance.bank_account WHERE id=61"))
        await session.commit()
        await apply(session, migration["downgrade"])
        await session.commit()
        assert await shape(session) == before_shape
        assert await snapshots(session) == before_rows
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(text("INSERT INTO finance.bank_account(code,title) VALUES ('synthetic-legacy','Synthetic blocked duplicate')"))
        # Actual historical consumer accepts restored constraint/index names.
        old = runpy.run_path(str(root / "migrations/versions/0075_finance_bank_account.py"))
        await apply(session, old["downgrade"])
        await session.commit()
        assert await session.scalar(text("SELECT amount::text FROM finance.payment WHERE id=51")) == "12.34"
        assert await session.scalar(text("SELECT ref FROM finance.payment WHERE id=51")) == "Synthetic legacy payment"
