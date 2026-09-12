"""Call write authorization must survive concurrent assignment changes."""
import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from modules.sales.access import DealAccess, locked_call_for_write
from modules.sales.models import CallLog, Deal


@pytest_asyncio.fixture
async def call_factory():
    raw = os.environ.get("CRM_READY_CALLS_DATABASE_URL")
    if not raw:
        pytest.skip("Requires the isolated CRM calls PostgreSQL")
    url = make_url(raw)
    if (url.host, url.port, url.database) != ("127.0.0.1", 15440, "crm_ready_calls"):
        pytest.fail("Use only the dedicated loopback CRM calls test database")
    schema = f"calls_{uuid4().hex}"
    engine = create_async_engine(url).execution_options(schema_translate_map={"sales": schema})
    try:
        async with engine.begin() as conn:
            await conn.execute(CreateSchema(schema))
            await conn.run_sync(Deal.__table__.create)
            await conn.run_sync(CallLog.__table__.create)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as conn:
            await conn.execute(DropSchema(schema, cascade=True, if_exists=True))
        await engine.dispose()


@pytest.mark.parametrize("changed", ["source_owner", "target_owner", "call_link"])
async def test_write_waits_then_rechecks_changed_assignment(call_factory, changed):
    async with call_factory() as seed:
        source = Deal(number="source", title="Source", counterparty="Synthetic", owner_id=301)
        target = Deal(number="target", title="Target", counterparty="Synthetic", owner_id=301)
        foreign = Deal(number="foreign", title="Foreign", counterparty="Synthetic", owner_id=302)
        seed.add_all([source, target, foreign])
        await seed.flush()
        call = CallLog(call_id="race", deal_id=source.id, owner_id=301)
        seed.add(call)
        await seed.commit()
        call_id, source_id, target_id, foreign_id = call.id, source.id, target.id, foreign.id
    async with call_factory() as holder, call_factory() as waiter:
        task = None
        try:
            # Prime stale ORM objects as a long-lived request would.
            stale_call = await waiter.get(CallLog, call_id)
            stale_source = await waiter.get(Deal, source_id)
            stale_target = await waiter.get(Deal, target_id)
            assert stale_call.deal_id == source_id
            assert stale_source.owner_id == stale_target.owner_id == 301
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            waiter_pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            if changed == "call_link":
                await holder.execute(update(CallLog).where(CallLog.id == call_id).values(deal_id=foreign_id))
            else:
                deal_id = source_id if changed == "source_owner" else target_id
                await holder.execute(update(Deal).where(Deal.id == deal_id).values(owner_id=302))

            async def write():
                try:
                    row = await locked_call_for_write(waiter, call_id, DealAccess("own", 301), target_id)
                    row.comment = "must not be saved"
                    row.deal_id = target_id
                    await waiter.commit()
                finally:
                    await waiter.rollback()

            task = asyncio.create_task(write())
            async with asyncio.timeout(10), call_factory() as observer:
                while True:
                    blocked = await observer.scalar(text(
                        "SELECT :holder = ANY(pg_blocking_pids(:waiter))"
                    ), {"holder": holder_pid, "waiter": waiter_pid})
                    if blocked:
                        break
                    if task.done():
                        pytest.fail("Call write did not wait for the assignment transaction")
                    await asyncio.sleep(0.02)
            await holder.commit()
            with pytest.raises(HTTPException) as denied:
                await asyncio.wait_for(task, timeout=10)
            assert denied.value.status_code == 404
        finally:
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    async with call_factory() as verify:
        row = await verify.get(CallLog, call_id)
        assert row.comment is None
        assert row.deal_id == (foreign_id if changed == "call_link" else source_id)
