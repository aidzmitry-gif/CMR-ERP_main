"""A real physical act may need multiple balanced accounting pages."""

# ruff: noqa: F811
import asyncio
from time import perf_counter

from sqlalchemy import func, select, text

from modules.accounting import models, shipment_commands, shipment_preview
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


async def test_real_act_with_501_expense_allocations_commits_all_pages(physical_pg):
    factory, org, act, data = await prepare_accounting(physical_pg, stock_cost="100.00")
    template = data.allocations[0]
    raw = data.model_dump(mode="json")
    raw["allocations"] = [
        {
            **template.model_dump(mode="json"),
            "quantity": "0.001" if index < 500 else "0.500",
            "expense_dimensions": {"department": f"D{index:04d}"},
        }
        for index in range(501)
    ]
    data = shipment_preview.ShipmentPlanInput(**raw)
    async with factory() as session:
        await session.execute(text("SET LOCAL statement_timeout='30s'"))
        plan = await shipment_preview.prepare(session, org, act, data)
        assert len(plan["postings"]) == 2
        assert sum(len(page["posting"]["lines"]) for page in plan["postings"]) == 1006
        start = perf_counter()
        saved = await shipment_commands.confirm(
            session, org, act, data, plan["basis_digest"], "allocator"
        )
        await asyncio.wait_for(session.commit(), timeout=30)
        elapsed = perf_counter() - start
        assert len(saved.snapshot["pages"]) == 2
        assert await session.scalar(select(func.count()).select_from(models.Entry)) == 3
        print(f"whole-shipment 501 allocations/1006 lines commit_seconds={elapsed:.3f}")
