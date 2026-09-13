"""PostgreSQL evidence for source-bound finance bank imports."""
from __future__ import annotations

import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from core.db.base import Base
from modules.accounting import bank_import
from modules.accounting.models import BankImportReceipt, SourceBinding
from modules.finance.models import BankAccount, BankTransaction, Payment, PaymentAllocation
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


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
