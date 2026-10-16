# ruff: noqa: F811 -- imported pytest fixtures
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.accounting.test_postgres import pg_factory  # noqa: F401


async def test_late_cost_receipt_guards_are_installed_and_reject_unbound_history(pg_factory):
    async with pg_factory() as session:
        names = set((await session.scalars(text("SELECT tgname FROM pg_trigger WHERE tgrelid='accounting.late_cost_receipt'::regclass AND NOT tgisinternal"))).all())
        assert names == {"immutable_late_cost_receipt", "guard_late_cost_receipt", "complete_late_cost_receipt"}
    for statement in ["UPDATE accounting.late_cost_receipt SET actor='other'",
                      "DELETE FROM accounting.late_cost_receipt", "TRUNCATE accounting.late_cost_receipt"]:
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement))
            await session.rollback()
    async with pg_factory() as session:
        with pytest.raises(DBAPIError, match="does not match its ledger entry"):
            await session.execute(text("INSERT INTO accounting.late_cost_receipt "
                "(entry_id, organization_id, expense_id, source_version, request_key, command, calculation, posting, digest, actor) "
                "VALUES (999,999,999,1,'00000000-0000-0000-0000-000000000001','{}','{}','{}','bad','tester')"))
        await session.rollback()
