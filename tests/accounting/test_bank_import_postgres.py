"""PostgreSQL evidence for source-bound finance bank imports."""
from __future__ import annotations

import asyncio
from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from core.db.base import Base
from modules.accounting import bank_import, closing_controls, service
from modules.accounting.models import BankImportReceipt, SourceBinding
from modules.finance.models import BankAccount, BankTransaction, Payment, PaymentAllocation
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration



@pytest_asyncio.fixture(autouse=True)
async def bank_period_sql_guards(pg_factory):  # noqa: F811
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    async with pg_factory() as session:
        connection = await session.connection()
        sql = Path("modules/accounting/bank_period_guards.sql").read_text(encoding="utf-8")
        await connection.run_sync(lambda conn: Operations(MigrationContext.configure(conn)).execute(sql))
        await session.commit()

async def _install_finance_source_tables(session):
    """The frozen accounting proposal deliberately does not own finance.*."""
    await session.execute(text("CREATE SCHEMA IF NOT EXISTS finance"))
    connection = await session.connection()
    tables = [BankAccount.__table__, Payment.__table__, PaymentAllocation.__table__, BankTransaction.__table__]
    await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables, checkfirst=True))


def command(source_id: int, source_digest: str, policy_id: int) -> bank_import.BankImportInput:
    return bank_import.BankImportInput(
        request_key=str(uuid4()), source_transaction_id=source_id, source_digest=source_digest,
        policy_id=policy_id, bank_account="51", settlement_account="62",
        bank_dimensions={"bank_statement": "caller-value"},
        settlement_dimensions={"counterparty": "buyer-pg", "contract": "contract-pg"},
        posting_date=date(2026, 9, 4), cash_activity="operating",
        explanation="Review imported bank receipt in PostgreSQL acceptance",
    )


async def test_imported_bank_source_is_mapped_atomic_and_immutable(pg_factory, pg_book):  # noqa: F811
    async with pg_factory() as session:
        await _install_finance_source_tables(session)
        source = BankTransaction(
            ext_id="PG-BANK-IMPORT-1", occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN",
            payer_unp="191234567", payer_name="PG Buyer", purpose="Advance", account_code="main",
        )
        session.add(source)
        await session.flush()
        session.add(SourceBinding(
            organization_id=pg_book[0], source_type="finance_bank_transaction", source_id=source.id,
            ownership="own", evidence="PostgreSQL chief mapping for the pilot company", actor="tester",
        ))
        await session.commit()
        snapshot = bank_import.source_snapshot(source)

    async with pg_factory() as session:
        from modules.accounting.schemas import CloseInput

        controls = await closing_controls.snapshot(session, pg_book[0], "2026-09")
        assert next(item["count"] for item in controls["blockers"] if item["code"] == "unposted_bank_imports") == 1
        with pytest.raises(service.AccountingError, match="Unposted imported bank"):
            await service.validate_close_period(session, pg_book[0], "2026-09", CloseInput(
                expected_generation=controls["period"]["generation"],
                evidence={key: "Synthetic PG verification" for key in service.CLOSE_STEPS},
            ))

    data = command(source.id, bank_import._digest(snapshot), pg_book[1])
    async with pg_factory() as session:
        preview = await bank_import.prepare(session, pg_book[0], data)
        confirmed = bank_import.BankImportConfirmInput(
            **data.model_dump(), basis_digest=preview["basis_digest"], digest=preview["digest"],
        )

    async def writer():
        async with pg_factory() as session:
            try:
                row = await bank_import.confirm(session, pg_book[0], confirmed, "tester")
                await session.commit()
                return row.entry_id
            except Exception:
                await session.rollback()
                return None

    results = await asyncio.gather(writer(), writer())
    assert results[0] == results[1] and results[0] is not None

    async with pg_factory() as session:
        await session.execute(update(BankTransaction).where(BankTransaction.id == source.id).values(match_status="matched"))
        await session.commit()
    async with pg_factory() as session:
        replay = await bank_import.confirm(session, pg_book[0], confirmed, "tester")
        await session.commit()
        assert replay.entry_id == results[0]

    async with pg_factory() as session:
        receipt = await session.scalar(select(BankImportReceipt).where(BankImportReceipt.entry_id == results[0]))
        controls = await closing_controls.snapshot(session, pg_book[0], "2026-09")
        assert not any(item["code"] == "unposted_bank_imports" for item in controls["blockers"])
        assert receipt is not None
        assert receipt.snapshot["source_snapshot"]["ext_id"] == "PG-BANK-IMPORT-1"
        assert await session.scalar(select(func.count()).select_from(BankImportReceipt)) == 1

        with pytest.raises(DBAPIError):
            await session.execute(text("""
                INSERT INTO accounting.bank_import_receipt
                    (entry_id, organization_id, source_transaction_id, source_ext_id, source_digest,
                     source, request_key, bank_account, settlement_account, amount,
                     document_date, operation_date, posting_date, command, command_digest,
                     basis_digest, snapshot, posting, digest, actor)
                VALUES (:entry_id, :org, :source_id, 'FORGED-STATEMENT', :source_digest,
                        :source, :request_key, :bank_account, :settlement_account, :amount,
                        :document_date, :operation_date, :posting_date, CAST(:command AS json),
                        :command_digest, :basis_digest, CAST(:snapshot AS json), CAST(:posting AS json),
                        :digest, 'tester')
            """), {
                "entry_id": receipt.entry_id, "org": receipt.organization_id,
                "source_id": receipt.source_transaction_id, "source_digest": receipt.source_digest,
                "source": receipt.source, "request_key": str(uuid4()),
                "bank_account": receipt.bank_account, "settlement_account": receipt.settlement_account,
                "amount": receipt.amount, "document_date": receipt.document_date,
                "operation_date": receipt.operation_date, "posting_date": receipt.posting_date,
                "command": "{}", "command_digest": receipt.command_digest,
                "basis_digest": receipt.basis_digest, "snapshot": "{}", "posting": "{}",
                "digest": receipt.digest,
            })
        await session.rollback()

    for statement in (
        "UPDATE accounting.bank_import_receipt SET amount=0",
        "DELETE FROM accounting.bank_import_receipt",
        "TRUNCATE accounting.bank_import_receipt",
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text(statement))
            await session.rollback()


@pytest.mark.parametrize("close_first", [True, False])
async def test_bank_binding_and_month_closing_serialize(pg_factory, pg_book, close_first):  # noqa: F811
    from fastapi import HTTPException

    from modules.accounting import routes
    from modules.accounting.models import Period
    from modules.accounting.schemas import CloseInput, SourceBindingInput

    async with pg_factory() as session:
        source = BankTransaction(ext_id="PG-BIND-CLOSE", occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN")
        session.add(source)
        await session.commit()
        source_id = source.id
    binding = SourceBindingInput(source_type="finance_bank_transaction", source_id=source_id,
                                 ownership="own", evidence="Synthetic concurrent bank binding")

    async def perform(session, closing):
        if closing:
            await service.close_period(session, pg_book[0], "2026-09", CloseInput(
                expected_generation=0, evidence={key: "Checked synthetic month" for key in service.CLOSE_STEPS}), "tester")
        else:
            await routes.bind_source(pg_book[0], binding, (session, "tester", "chief"))

    worker_started = asyncio.Event()
    worker_pid = None

    async def second():
        nonlocal worker_pid
        async with pg_factory() as session:
            worker_pid = await session.scalar(text("SELECT pg_backend_pid()"))
            worker_started.set()
            try:
                await perform(session, not close_first)
                await session.commit()
                return "unexpected success"
            except (HTTPException, service.AccountingError) as exc:
                await session.rollback()
                return str(exc)

    async with pg_factory() as holder:
        await perform(holder, close_first)
        task = asyncio.create_task(second())
        try:
            await asyncio.wait_for(worker_started.wait(), 5)
            for _ in range(100):
                blocked = await holder.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": worker_pid})
                if blocked:
                    break
                await asyncio.sleep(0.02)
            assert blocked, "Second writer must wait for the organization lock"
            await holder.commit()
            result = await asyncio.wait_for(task, 10)
            assert ("closed period" if close_first else "Unposted imported bank") in result
        finally:
            await holder.rollback()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    async with pg_factory() as session:
        bound = await session.scalar(select(SourceBinding.id).where(SourceBinding.source_id == source_id))
        closed = await session.scalar(select(Period.closed).where(Period.organization_id == pg_book[0], Period.month == "2026-09"))
        assert bool(bound) is (not close_first)
        assert bool(closed) is close_first


async def test_bank_sql_guards_reject_close_mutation_and_late_binding(pg_factory, pg_book):  # noqa: F811
    from modules.accounting.models import Period
    from modules.accounting.schemas import CloseInput

    async with pg_factory() as session:
        source = BankTransaction(ext_id="PG-SQL-GUARD", occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN")
        session.add(source)
        await session.flush()
        source_id = source.id
        session.add(SourceBinding(organization_id=pg_book[0], source_type="finance_bank_transaction", source_id=source_id,
                                  ownership="own", evidence="SQL guard fixture", actor="tester"))
        session.add(Period(organization_id=pg_book[0], month="2026-09", closed=False, generation=0))
        await session.commit()
    statements = [
        ("UPDATE accounting.period SET closed=true WHERE organization_id=:org AND month='2026-09'", "Unposted imported bank"),
        ("UPDATE finance.bank_transaction SET amount=121 WHERE id=:source", "financial fields are immutable"),
        ("DELETE FROM finance.bank_transaction WHERE id=:source", "financial fields are immutable"),
        ("TRUNCATE finance.bank_transaction", "cannot be truncated"),
    ]
    for sql, expected in statements:
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match=expected):
                await session.execute(text(sql), {"org": pg_book[0], "source": source_id})
                await session.commit()
            await session.rollback()
    async with pg_factory() as session:
        await session.execute(text("UPDATE finance.bank_transaction SET match_status='matched' WHERE id=:id"), {"id": source_id})
        await session.commit()
        # An earlier month can close; its source dates remain outside that month.
        await service.close_period(session, pg_book[0], "2026-08", CloseInput(
            expected_generation=0, evidence={key: "Synthetic SQL guard check" for key in service.CLOSE_STEPS}), "tester")
        await session.commit()
    async with pg_factory() as session:
        old = BankTransaction(ext_id="PG-SQL-LATE", occurred_on=date(2026, 8, 3), amount="1.00", currency="BYN")
        session.add(old)
        await session.flush()
        session.add(SourceBinding(organization_id=pg_book[0], source_type="finance_bank_transaction", source_id=old.id,
                                  ownership="own", evidence="Rejected old source", actor="tester"))
        with pytest.raises(DBAPIError, match="Bank source affects a closed period"):
            await session.flush()
        await session.rollback()
