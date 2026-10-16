"""Execute invoice evidence JSON/graph queries against the frozen PostgreSQL schema."""
import pytest
from sqlalchemy import select

from core.services.auth import CurrentUser
from modules.accounting import service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import Entry, Inbox
from tests.accounting.test_postgres import pg_book as pg_book  # noqa: F401
from tests.accounting.test_postgres import pg_factory as pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def test_postgres_analytical_graph_pending_correction_and_no_hidden_commit(pg_factory, pg_book, posting):
    gateway = AccountingService()
    user = CurrentUser("tester", ["director"])
    async with pg_factory() as session:
        root = await service.post(session, pg_book[0], posting(source="legacy-root"), "tester")
        matched = posting(source="analytical-match", correction_of=root.id)
        matched.lines[0].dimensions = {"settlement_document": "sales:document:17"}
        child = await service.post(session, pg_book[0], matched, "tester")
        other = await service.post(session, pg_book[0], posting(source="sales:document:170"), "tester")
        await session.commit()
        initial = await gateway.invoice_fulfillment_snapshot(session, pg_book[0], user, 17)
        assert [row["id"] for row in initial["facts"]["entries"]] == [root.id, child.id]
        assert other.id not in {row["entry_id"] for row in initial["facts"]["lines"]}
        assert initial["facts"]["coverage_complete"] is False
        correction = posting(source="pending-correction", correction_of=child.id)
        queued = await service.receive(session, pg_book[0], "pending-review", "2026-09",
                                       correction.model_dump(mode="json"))
        current = await gateway.invoice_fulfillment_snapshot(session, pg_book[0], user, 17)
        assert current["digest"] != initial["digest"]
        assert [row["id"] for row in current["facts"]["inbox"]] == [queued.id]
        await session.rollback()
    async with pg_factory() as session:
        assert await session.scalar(select(Inbox.id)) is None
        assert len((await session.scalars(select(Entry))).all()) == 3
        repeated = await gateway.invoice_fulfillment_snapshot(session, pg_book[0], user, 17)
        assert repeated == initial
