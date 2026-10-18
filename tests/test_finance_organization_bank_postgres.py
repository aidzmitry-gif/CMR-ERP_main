"""Real PostgreSQL bank locks in disposable, synthetic-only databases.

This exercises current ORM constraints, not the production migration path.
"""
import asyncio
import os
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.settings import get_settings
from core.domain.models import IdentityInvitationRequest, OutboxEvent, User
from core.runtime.deps import get_core, get_session
from core.services.auth import CurrentUser, get_current_user
from core.services.eventbus import OutboxEventBus
from modules.accounting.gateway import AccountingService
from modules.accounting.models import AccessGrant, Organization, SourceBinding
from modules.finance.models import BankAccount, BankTransaction, Payment, PaymentAllocation
from modules.finance.routes import router


@pytest_asyncio.fixture
async def native_bank_factory():
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

            await conn.run_sync(create_tables)
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
