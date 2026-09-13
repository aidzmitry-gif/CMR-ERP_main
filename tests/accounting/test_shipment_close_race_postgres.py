"""Closing review must become stale after a concurrent shipment commits."""

# ruff: noqa: F811
import asyncio

import pytest
from sqlalchemy import select, text

from modules.accounting import models, service, shipment_commands, shipment_preview
from modules.accounting.schemas import CloseInput
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


async def test_close_rechecks_generation_after_waiting_for_shipment(physical_pg):
    factory, org, act, data = await prepare_accounting(physical_pg)
    month = data.posting_date.strftime("%Y-%m")
    started = asyncio.Event()
    pid = None
    async with factory() as first:
        plan = await shipment_preview.prepare(first, org, act, data)
        period = await service.period_for(first, org, month)
        review = CloseInput(
            expected_generation=period.generation,
            evidence={key: "Synthetic review before shipment" for key in service.CLOSE_STEPS},
        )
        await shipment_commands.confirm(first, org, act, data, plan["basis_digest"], "allocator")

        async def close_after_wait():
            nonlocal pid
            async with factory() as closing:
                pid = await closing.scalar(text("SELECT pg_backend_pid()"))
                started.set()
                with pytest.raises(service.AccountingError, match="Data changed after review"):
                    await service.close_period(closing, org, month, review, "allocator")
                await closing.rollback()

        task = asyncio.create_task(close_after_wait())
        try:
            await asyncio.wait_for(started.wait(), 5)
            async with factory() as observer:
                for _ in range(250):
                    state = await observer.scalar(
                        text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"),
                        {"pid": pid},
                    )
                    if state == "Lock":
                        break
                    await asyncio.sleep(0.02)
                assert state == "Lock"
            assert not task.done()
            await first.commit()
            await asyncio.wait_for(task, 10)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    async with factory() as session:
        period = await session.scalar(
            select(models.Period).where(
                models.Period.organization_id == org, models.Period.month == month
            )
        )
        assert not period.closed
        assert period.generation > review.expected_generation
        assert (
            await session.scalar(
                select(models.SourceControl.entry_id).where(
                    models.SourceControl.source == plan["source"]
                )
            )
            is not None
        )
