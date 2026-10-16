"""PostgreSQL guards for immutable OSV reconciliation issue queues."""
# ruff: noqa: F401, F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting.models import ReconciliationIssue, ReconciliationIssueItem
from tests.accounting.test_postgres import pg_book, pg_factory

pytestmark = pytest.mark.integration


def issue_values(*, request_key: str, left: str, right: str, command: str, digest: str):
    return {
        "organization_id": 0,  # Filled from the isolated fixture in each test.
        "request_key": request_key,
        "period_from": date(2026, 9, 1),
        "period_to": date(2026, 9, 30),
        "left_digest": left * 64,
        "right_digest": right * 64,
        "left_status": "closed_periods",
        "right_status": "closed_periods",
        "left_pending_documents": 0,
        "right_pending_documents": 0,
        "left_rows": 1,
        "right_rows": 1,
        "difference_count": 1,
        "eligibility_blockers": ["numeric_differences"],
        "responsible": "accountant:synthetic-owner",
        "evidence": "Synthetic queue evidence identifies responsible owner",
        "command_digest": command * 64,
        "snapshot": {"format": "crm-osv-comparison-v1", "difference_count": 1},
        "digest": digest * 64,
        "actor": "tester",
    }


async def test_reconciliation_issue_keeps_all_rows_and_history_immutable(pg_factory, pg_book):
    async with pg_factory() as session:
        values = issue_values(
            request_key="00000000-0000-4000-8000-000000000031", left="a", right="b", command="c", digest="d",
        )
        values["organization_id"] = pg_book[0]
        issue = ReconciliationIssue(**values)
        session.add(issue)
        await session.flush()
        item = ReconciliationIssueItem(
            organization_id=pg_book[0], issue_id=issue.id, item_key="e" * 64,
            account="001", dimensions={"sku": "A"}, currency="USD", off_balance=True,
            presence="both", fields={"debit": {"left": "1.00", "right": "2.00", "right_minus_left": "1.00"}},
            digest="f" * 64,
        )
        session.add(item)
        await session.commit()
        issue_id, item_id = issue.id, item.id

    for statement, params in (
        ("UPDATE accounting.reconciliation_issue SET responsible='forged' WHERE id=:id", {"id": issue_id}),
        ("DELETE FROM accounting.reconciliation_issue_item WHERE id=:id", {"id": item_id}),
        ("TRUNCATE accounting.reconciliation_issue_item", {}),
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement), params)
            await session.rollback()


async def test_reconciliation_issue_rejects_a_snapshot_without_every_difference(pg_factory, pg_book):
    async with pg_factory() as session:
        values = issue_values(
            request_key="00000000-0000-4000-8000-000000000032", left="1", right="2", command="3", digest="4",
        )
        values["organization_id"] = pg_book[0]
        session.add(ReconciliationIssue(**values))
        with pytest.raises(DBAPIError, match="retain every unmatched row"):
            await session.commit()
        await session.rollback()


async def test_reconciliation_issue_keeps_non_numeric_blockers_without_manufacturing_rows(pg_factory, pg_book):
    async with pg_factory() as session:
        values = issue_values(
            request_key="00000000-0000-4000-8000-000000000034", left="5", right="6", command="7", digest="8",
        )
        values.update({
            "organization_id": pg_book[0],
            "left_status": "preliminary",
            "right_status": "preliminary",
            "left_pending_documents": 2,
            "right_pending_documents": 2,
            "difference_count": 0,
            "eligibility_blockers": ["reports_not_closed", "pending_documents"],
            "snapshot": {"format": "crm-osv-comparison-v1", "difference_count": 0},
        })
        issue = ReconciliationIssue(**values)
        session.add(issue)
        await session.commit()
        assert issue.id > 0
        count = await session.scalar(text(
            "SELECT count(*) FROM accounting.reconciliation_issue_item WHERE issue_id=:id"), {"id": issue.id},
        )
        assert count == 0


async def test_reconciliation_issue_queue_replay_is_atomic_under_two_postgres_writers(pg_factory, pg_book):
    import asyncio
    import base64
    from uuid import UUID

    from sqlalchemy import func, select

    from modules.accounting import reconciliation
    from tests.accounting.test_reconciliation import snapshot

    left = base64.b64encode(snapshot(org=str(pg_book[0]), amount="1.00", status="closed_periods", pending="0")).decode()
    right = base64.b64encode(snapshot(org=str(pg_book[0]), amount="2.00", status="closed_periods", pending="0")).decode()
    request_key = UUID("00000000-0000-4000-8000-000000000033")

    async def writer():
        async with pg_factory() as session:
            result = await reconciliation.queue_uploads(
                session, pg_book[0], left, right, request_key, "accountant:synthetic-owner",
                "Synthetic concurrent queue evidence", "tester",
            )
            await session.commit()
            return result

    first, second = await asyncio.gather(writer(), writer())
    assert sorted([first["already_queued"], second["already_queued"]]) == [False, True]
    assert first["issue_id"] == second["issue_id"]
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ReconciliationIssue)) == 1
        assert await session.scalar(select(func.count()).select_from(ReconciliationIssueItem)) == 1
