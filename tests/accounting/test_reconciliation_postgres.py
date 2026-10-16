"""PostgreSQL evidence for immutable accountant OSV reconciliation receipts."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting.models import ReconciliationReceipt
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def test_reconciliation_receipt_requires_closed_complete_equal_reports_and_is_immutable(
    pg_factory, pg_book,
):
    async with pg_factory() as session:
        row = ReconciliationReceipt(
            organization_id=pg_book[0],
            request_key="00000000-0000-4000-8000-000000000010",
            period_from="2026-09-01", period_to="2026-09-30",
            left_digest="a" * 64, right_digest="b" * 64,
            left_status="closed_periods", right_status="closed_periods",
            left_pending_documents=0, right_pending_documents=0,
            left_rows=3, right_rows=3, difference_count=0,
            command_digest="c" * 64,
            evidence="Главный бухгалтер подтвердил совпадение закрытых ОСВ",
            snapshot={"format": "crm-osv-comparison-v1", "difference_count": 0},
            digest="d" * 64, actor="tester",
        )
        session.add(row)
        await session.commit()
        receipt_id = row.id

    for statement in (
        "UPDATE accounting.reconciliation_receipt SET actor='forged' WHERE id=:id",
        "DELETE FROM accounting.reconciliation_receipt WHERE id=:id",
        "TRUNCATE accounting.reconciliation_receipt",
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement), {"id": receipt_id})
            await session.rollback()

    async with pg_factory() as session:
        duplicate = ReconciliationReceipt(
            organization_id=pg_book[0],
            request_key="00000000-0000-4000-8000-000000000012",
            period_from="2026-09-01", period_to="2026-09-30",
            left_digest="a" * 64, right_digest="b" * 64,
            left_status="closed_periods", right_status="closed_periods",
            left_pending_documents=0, right_pending_documents=0,
            left_rows=3, right_rows=3, difference_count=0,
            command_digest="e" * 64,
            evidence="Повторная формулировка проверки бухгалтером",
            snapshot={"format": "crm-osv-comparison-v1", "difference_count": 0},
            digest="f" * 64, actor="tester",
        )
        session.add(duplicate)
        with pytest.raises(DBAPIError, match="uq_reconciliation_source_pair"):
            await session.flush()
        await session.rollback()

    async with pg_factory() as session:
        invalid = ReconciliationReceipt(
            organization_id=pg_book[0],
            request_key="00000000-0000-4000-8000-000000000011",
            period_from="2026-09-01", period_to="2026-09-30",
            left_digest="e" * 64, right_digest="f" * 64,
            left_status="preliminary", right_status="closed_periods",
            left_pending_documents=0, right_pending_documents=0,
            left_rows=1, right_rows=1, difference_count=0,
            command_digest="1" * 64,
            evidence="Нельзя принять незакрытый отчёт",
            snapshot={"format": "crm-osv-comparison-v1", "difference_count": 0},
            digest="2" * 64, actor="tester",
        )
        session.add(invalid)
        with pytest.raises(DBAPIError, match="reconciliation_reports_closed"):
            await session.flush()
        await session.rollback()
