"""Real PostgreSQL wait proves a stale branch PATCH cannot restore an old parent."""
import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text

from core.domain.models import Counterparty, CounterpartyAlias, CounterpartyBranch, OutboxEvent
from core.services import mdm
from modules.sales.models import Deal
from modules.sales.party_identity import prepare_party_change
from modules.sales.touch_history import SalesTouchHistory
from tests.integration.test_counterparty_requisites import _row_waiter_pids


async def test_branch_patch_rechecks_parent_after_waiting_for_party_change(pg_app):
    factory = pg_app._transport.app.state.core.services.db.session_factory
    marker = f"party-race-{uuid4().hex}"
    async with factory() as session:
        old, new = Counterparty(name=marker+'-old'), Counterparty(name=marker+'-new')
        session.add_all([old, new])
        await session.flush()
        branch = CounterpartyBranch(legal_entity_id=old.id, name=marker+'-branch')
        deal = Deal(number=marker, title=marker, counterparty=old.name, counterparty_id=old.id)
        session.add_all([branch, deal])
        await session.commit()
        old_id, new_id, branch_id, deal_id = old.id, new.id, branch.id, deal.id
    task = None
    try:
        async with factory() as holder, factory() as observer:
            try:
                async with asyncio.timeout(15):
                    pid = await holder.scalar(text('SELECT pg_backend_pid()'))
                    current = await holder.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
                    current.counterparty_id = new_id
                    current.counterparty = marker+'-new'
                    await holder.flush()
                    task = asyncio.create_task(pg_app.patch(f'/sales/deals/{deal_id}', json={'branch_id': branch_id}))
                    while not await _row_waiter_pids(observer, pid):
                        assert not task.done(), 'PATCH must be observed waiting on the held deal'
                        await asyncio.sleep(0.025)
                    await holder.commit()
                    response = await task
                    assert response.status_code == 422, response.text
            finally:
                await holder.rollback()
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)
        async with factory() as session:
            saved = await session.get(Deal, deal_id)
            assert saved.counterparty_id == new_id
            assert saved.branch_id is None
            assert saved.counterparty == marker+'-new'
    finally:
        assert task is None or task.done(), 'No cleanup while a writer is active'
        async with factory() as session:
            await session.execute(delete(Deal).where(Deal.id == deal_id, Deal.number == marker))
            await session.execute(delete(CounterpartyBranch).where(CounterpartyBranch.id == branch_id))
            await session.execute(delete(Counterparty).where(Counterparty.id.in_([old_id, new_id])))
            await session.commit()


@pytest.mark.parametrize('selection_first', [True, False])
async def test_merge_and_selection_observe_each_others_commits(pg_app, selection_first):
    core = pg_app._transport.app.state.core
    factory = core.services.db.session_factory
    marker = f'merge-race-{uuid4().hex}'
    async with factory() as session:
        survivor, duplicate = Counterparty(name=marker+'-survivor'), Counterparty(name=marker+'-duplicate')
        session.add_all([survivor, duplicate])
        await session.commit()
        survivor_id, duplicate_id = survivor.id, duplicate.id

    async def selection(session):
        data = {'counterparty': marker+'-duplicate', 'counterparty_id': duplicate_id}
        await prepare_party_change(session, data)
        session.add(Deal(number=marker, title=marker, **data))
        await session.flush()

    async def merge(session):
        await mdm.merge(session, core.event_bus, survivor_id, duplicate_id,
                        reference_guard=SalesTouchHistory().has_deals)
        await session.flush()

    async def contender():
        async with factory() as session:
            try:
                await (merge(session) if selection_first else selection(session))
                pytest.fail('The second transaction must reject the incompatible committed state')
            except (ValueError, HTTPException) as error:
                await session.rollback()
                return error

    task = None
    try:
        async with factory() as holder, factory() as observer:
            try:
                async with asyncio.timeout(15):
                    pid = await holder.scalar(text('SELECT pg_backend_pid()'))
                    await (selection(holder) if selection_first else merge(holder))
                    task = asyncio.create_task(contender())
                    while not await _row_waiter_pids(observer, pid):
                        assert not task.done(), 'Contender must wait on the selected legal entity'
                        await asyncio.sleep(0.025)
                    await holder.commit()
                    error = await task
                    if selection_first:
                        assert isinstance(error, ValueError) and 'сделки' in str(error)
                    else:
                        assert isinstance(error, HTTPException) and error.status_code == 409
            finally:
                await holder.rollback()
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)
        async with factory() as session:
            saved = await session.get(Counterparty, duplicate_id)
            deal = await session.scalar(select(Deal).where(Deal.number == marker))
            aliases = list(await session.scalars(select(CounterpartyAlias).where(
                CounterpartyAlias.source == 'merge', CounterpartyAlias.external_ref == str(duplicate_id),
            )))
            if selection_first:
                assert saved.is_active and saved.merged_into_id is None
                assert deal.counterparty_id == duplicate_id and not aliases
            else:
                assert not saved.is_active and saved.merged_into_id == survivor_id
                assert deal is None and len(aliases) == 1
    finally:
        assert task is None or task.done()
        async with factory() as session:
            await session.execute(delete(Deal).where(Deal.number == marker))
            await session.execute(delete(CounterpartyAlias).where(CounterpartyAlias.counterparty_id == survivor_id))
            await session.execute(delete(OutboxEvent).where(
                OutboxEvent.event_type == 'counterparty.merged', OutboxEvent.payload['survivor_id'].as_integer() == survivor_id,
            ))
            await session.execute(delete(Counterparty).where(Counterparty.id.in_([survivor_id, duplicate_id])))
            await session.commit()
