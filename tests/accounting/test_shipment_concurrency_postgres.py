"""Observed PostgreSQL row-lock waits, not timing-only concurrency assertions."""

# ruff: noqa: F811
import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import models, service, shipment_commands, shipment_preview
from modules.accounting.schemas import PostingInput
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


@pytest.mark.parametrize("changed", [False, True])
async def test_waiting_confirmation_rechecks_committed_receipt(physical_pg, changed):
    factory, org, act, data = await prepare_accounting(physical_pg)
    waiting = asyncio.Event()
    backend_pid = None
    async with factory() as first:
        plan = await shipment_preview.prepare(first, org, act, data)
        saved = await shipment_commands.confirm(
            first, org, act, data, plan["basis_digest"], "allocator"
        )
        first_id = saved.id
        other = deepcopy(data)
        if changed:
            other.explanation = "Changed command while first transaction is pending"

        async def contender():
            nonlocal backend_pid
            async with factory() as second:
                backend_pid = await second.scalar(text("SELECT pg_backend_pid()"))
                waiting.set()
                try:
                    result = await shipment_commands.confirm(
                        second, org, act, other, plan["basis_digest"], "allocator"
                    )
                    await second.commit()
                    return result.id
                except service.AccountingError as exc:
                    await second.rollback()
                    return str(exc)

        task = asyncio.create_task(contender())
        try:
            await asyncio.wait_for(waiting.wait(), 5)
            async with factory() as observer:
                for _ in range(250):
                    state = await observer.scalar(
                        text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"),
                        {"pid": backend_pid},
                    )
                    if state == "Lock":
                        break
                    await asyncio.sleep(0.02)
                assert state == "Lock", "The contender must be observed waiting in PostgreSQL"
            assert not task.done()
            await first.commit()
            result = await asyncio.wait_for(task, 10)
            if changed:
                assert "different content" in result
            else:
                assert result == first_id
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    async with factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(models.ShipmentAccountingReceipt))
            == 1
        )
        assert await session.scalar(select(func.count()).select_from(models.Entry)) == 2
        assert (
            await session.scalar(
                select(models.SourceControl.entry_id).where(
                    models.SourceControl.source == plan["source"]
                )
            )
            is not None
        )


async def test_receipt_cannot_adopt_entries_committed_in_an_earlier_transaction(physical_pg):
    factory, org, act, data = await prepare_accounting(physical_pg)
    async with factory() as session:
        plan = await shipment_preview.prepare(session, org, act, data)
        saved = await shipment_commands.confirm(
            session, org, act, data, plan["basis_digest"], "allocator"
        )
        snapshot = deepcopy(saved.snapshot)
        await session.rollback()
    async with factory() as session:
        for page in snapshot["pages"]:
            entry = await service.post(
                session, org, PostingInput(**page["posting"]), "allocator", inventory_sale=True
            )
            page["entry_id"] = entry.id
        await session.commit()
    async with factory() as session:
        session.add(
            models.ShipmentAccountingReceipt(
                organization_id=org,
                source=plan["source"],
                act_digest=act["digest"],
                command=data.model_dump(mode="json"),
                basis_digest=plan["basis_digest"],
                snapshot=snapshot,
                anchor_entry_id=snapshot["pages"][0]["entry_id"],
                actor="allocator",
            )
        )
        with pytest.raises(DBAPIError, match="same organization and root transaction"):
            await session.commit()
        await session.rollback()
        assert (
            await session.scalar(select(func.count()).select_from(models.ShipmentAccountingReceipt))
            == 0
        )
        assert (
            await session.scalar(
                select(models.SourceControl.entry_id).where(
                    models.SourceControl.source == plan["source"]
                )
            )
            is None
        )
