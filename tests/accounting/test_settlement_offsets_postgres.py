"""PostgreSQL evidence for immutable and concurrent advance offsets."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.services.auth import CurrentUser
from modules.accounting import service
from modules.accounting.documents import BankDocument
from modules.accounting.gateway import AccountingService
from modules.accounting.models import Entry, SettlementOffsetReceipt
from modules.accounting.settlement_offsets import (
    SettlementOffsetConfirmInput,
    SettlementOffsetInput,
    confirm,
    prepare,
)
from tests.accounting.test_bank_documents import document as bank_document
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


def offset(bank_entry_id: int, policy_id: int, request_key: str) -> SettlementOffsetInput:
    return SettlementOffsetInput(
        request_key=request_key,
        bank_entry_id=bank_entry_id,
        kind="customer_advance",
        target_document="sales:document:pg-offset",
        target_account="62",
        target_dimensions={
            "counterparty": "buyer-pg",
            "contract": "contract-pg",
            "settlement_document": "sales:document:pg-offset",
        },
        amount="100.00",
        document_date="2026-09-03",
        operation_date="2026-09-03",
        posting_date="2026-09-03",
        policy_id=policy_id,
        evidence="PostgreSQL reviewed advance allocation evidence",
        explanation="Apply customer advance in the PostgreSQL acceptance fixture",
    )


async def test_advance_offset_is_atomic_idempotent_and_immutable(pg_factory, pg_book):  # noqa: F811
    gateway = AccountingService()
    user = CurrentUser("tester", ["director"])
    bank = BankDocument(**bank_document(
        source="pg-customer-advance",
        statement_reference="pg-customer-advance-statement",
        policy_id=pg_book[1],
        settlement_account="60",
        amount="100.00",
        settlement_dimensions={
            "counterparty": "buyer-pg",
            "contract": "contract-pg",
            "settlement_document": "customer-advance:pg",
        },
    ))
    async with pg_factory() as session:
        bank_entry = await service.post(session, pg_book[0], bank.posting(), "tester")
        await session.commit()

    command = offset(bank_entry.id, pg_book[1], str(uuid4()))
    async with pg_factory() as session:
        preview = await prepare(session, pg_book[0], user, command, gateway)
        confirmed = SettlementOffsetConfirmInput(
            **command.model_dump(),
            basis_digest=preview["basis_digest"], digest=preview["digest"],
        )

    async def writer():
        async with pg_factory() as session:
            try:
                row = await confirm(session, pg_book[0], user, confirmed, gateway, "tester")
                await session.commit()
                return row.entry_id
            except Exception:
                await session.rollback()
                return None

    results = await asyncio.gather(writer(), writer())
    assert results[0] == results[1] and results[0] is not None
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SettlementOffsetReceipt)) == 1
        entry = await session.scalar(select(Entry).where(Entry.id == results[0]))
        assert entry.operation == "settlement_offset"
        assert (await session.scalar(select(SettlementOffsetReceipt).where(
            SettlementOffsetReceipt.entry_id == results[0],
        ))).source_snapshot["settlement_account"] == "60"

        with pytest.raises(DBAPIError):
            await session.execute(text("""
                INSERT INTO accounting.settlement_offset_receipt
                    (entry_id, organization_id, request_key, bank_entry_id, kind,
                     target_document, source_account, target_account, amount,
                     document_date, operation_date, posting_date, command,
                     command_digest, basis_digest, source_snapshot, target_snapshot,
                     snapshot, posting, digest, actor)
                VALUES (:entry_id, :org, :request_key, :bank_id, 'customer_advance',
                        'forged', '60', '62', 999.00,
                        '2026-09-03', '2026-09-03', '2026-09-03', '{}'::json,
                        :command_digest, :basis_digest, :source_snapshot, :target_snapshot,
                        '{}'::json, '{}'::json, :digest, 'tester')
            """), {
                "entry_id": bank_entry.id, "org": pg_book[0], "request_key": str(uuid4()),
                "bank_id": bank_entry.id, "command_digest": "a" * 64,
                "basis_digest": "b" * 64, "source_snapshot": "{}", "target_snapshot": "{}",
                "digest": "c" * 64,
            })
            await session.rollback()

    for statement in (
        "UPDATE accounting.settlement_offset_receipt SET amount=0",
        "DELETE FROM accounting.settlement_offset_receipt",
        "TRUNCATE accounting.settlement_offset_receipt",
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text(statement))
            await session.rollback()
