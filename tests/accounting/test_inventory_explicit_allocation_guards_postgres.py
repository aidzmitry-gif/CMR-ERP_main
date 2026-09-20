"""PostgreSQL checks for explicit allocation structural guards."""
# ruff: noqa: F811
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.accounting.test_inventory_allocation_loader import save_mixed_weighted_receipt
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_zero_value_output_cost_postgres import run_migration

pytestmark = pytest.mark.integration


async def test_explicit_allocation_guard_empty_roundtrip(pg_factory):
    async with pg_factory() as session:
        await run_migration(session, "0144_inventory_explicit_allocation_guards.py", "upgrade")
        assert await session.scalar(text("SELECT to_regprocedure('accounting.validate_inventory_allocation_link(integer)') IS NOT NULL"))
        await run_migration(session, "0144_inventory_explicit_allocation_guards.py", "downgrade")
        assert await session.scalar(text("SELECT to_regprocedure('accounting.validate_inventory_allocation_link(integer)') IS NULL"))
        await run_migration(session, "0144_inventory_explicit_allocation_guards.py", "upgrade")
        await session.commit()


@pytest.mark.parametrize("mutation", [None, "missing_marker", "null_marker", "wrong_source", "wrong_total", "duplicate_source", "credit_quantity"])
async def test_explicit_mixed_packet_guard_at_commit(pg_factory, pg_book, posting, mutation):
    async with pg_factory() as session:
        await run_migration(session, "0144_inventory_explicit_allocation_guards.py", "upgrade")
        await session.commit()

    def prepare_packet(cost, package):
        package = package.model_copy(update={"rule_version": package.rule_version + ":a1"})
        if mutation == "missing_marker":
            del cost["source_allocation_version"]
        elif mutation == "null_marker":
            cost["source_allocation_version"] = None
        elif mutation == "wrong_source":
            cost["inventory_layers"][0]["source_line_id"] = 2147483647
        elif mutation == "wrong_total":
            cost["issue_quantity"] = "3"
        elif mutation == "duplicate_source":
            for field in ("source_entry_id", "source_line_id"):
                cost["inventory_layers"][1][field] = cost["inventory_layers"][0][field]
        elif mutation == "credit_quantity":
            package = package.model_copy(update={"lines": [
                line.model_copy(update={"quantity": line.quantity * 2}) if line.quantity is not None else line
                for line in package.lines]})
        return package

    if mutation is not None:
        with pytest.raises(DBAPIError, match="allocation|Allocation"):
            await save_mixed_weighted_receipt(pg_factory, pg_book, posting, prepare_packet=prepare_packet)
    else:
        await save_mixed_weighted_receipt(pg_factory, pg_book, posting, prepare_packet=prepare_packet)
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="Cannot downgrade"):
                await run_migration(session, "0144_inventory_explicit_allocation_guards.py", "downgrade")
            await session.rollback()


@pytest.mark.parametrize("method,sale", [("fifo", False), ("fifo", True), ("weighted_average", True)])
async def test_guarded_fifo_and_sale_preserve_mixed_remaining_cost(pg_factory, pg_book, posting, method, sale):
    async with pg_factory() as session:
        await run_migration(session, "0144_inventory_explicit_allocation_guards.py", "upgrade")
        await session.commit()
    await save_mixed_weighted_receipt(pg_factory, pg_book, posting, method=method, sale=sale,
        prepare_packet=lambda cost, package: package.model_copy(update={"rule_version": package.rule_version + ":a1"}))
