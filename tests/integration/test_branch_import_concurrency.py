"""Observe real PostgreSQL waits before accepting branch source identity."""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text

from core.domain.models import (
    AuditLog,
    Counterparty,
    CounterpartyAlias,
    CounterpartyBranch,
    CounterpartyBranchAlias,
    OutboxEvent,
)
from core.services import mdm
from core.services.mdm import CounterpartyWriteError
from core.services.reference_import import import_counterparties
from modules.sales.touch_history import SalesTouchHistory
from tests.integration.test_counterparty_requisites import _row_waiter_pids


@pytest.mark.parametrize('branch_first', [False, True])
async def test_same_source_id_cannot_cross_legal_and_branch_tables(pg_app, branch_first):
    factory = pg_app._transport.app.state.core.services.db.session_factory
    source = 'kind-' + uuid4().hex[:20]
    unp = str(100000000 + uuid4().int % 800000000)
    async with factory() as session:
        parent = Counterparty(name=source, legal_name=source, unp=unp)
        session.add(parent)
        await session.flush()
        parent_id = parent.id
        session.add(CounterpartyAlias(counterparty_id=parent_id, source=source, external_ref='parent'))
        await session.commit()
    legal = {'id': 'collision', 'unp': unp, 'name': source, 'legal_name': source}
    branch = {'id': 'collision', 'record_kind': 'branch', 'parent_external_ref': 'parent', 'name': source}

    async def contender():
        async with factory() as session:
            try:
                await import_counterparties(session, [legal if branch_first else branch], source=source)
                pytest.fail('Cross-table source identity must reject the competing kind')
            except CounterpartyWriteError as error:
                await session.rollback()
                return error.code

    task = None
    try:
        async with factory() as holder, factory() as observer:
            try:
                async with asyncio.timeout(15):
                    pid = await holder.scalar(text('SELECT pg_backend_pid()'))
                    await import_counterparties(holder, [branch if branch_first else legal], source=source)
                    task = asyncio.create_task(contender())
                    while not await _row_waiter_pids(observer, pid):
                        assert not task.done(), 'The losing import must actually wait'
                        await asyncio.sleep(0.025)
                    await holder.commit()
                    assert await task == ('source_kind_conflict' if branch_first else 'legacy_flattened_branch_alias')
            finally:
                await holder.rollback()
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)
        async with factory() as session:
            legal_alias = await session.scalar(select(CounterpartyAlias).where(
                CounterpartyAlias.source == source, CounterpartyAlias.external_ref == 'collision'))
            branch_alias = await session.scalar(select(CounterpartyBranchAlias).where(
                CounterpartyBranchAlias.source == source, CounterpartyBranchAlias.external_ref == 'collision'))
            assert (legal_alias is None) == branch_first
            assert (branch_alias is not None) == branch_first
            assert len(list(await session.scalars(select(Counterparty).where(Counterparty.unp == unp)))) == 1
            assert len(list(await session.scalars(select(CounterpartyBranch).where(
                CounterpartyBranch.legal_entity_id == parent_id)))) == int(branch_first)
    finally:
        assert task is None or task.done()
        async with factory() as session:
            await session.execute(delete(AuditLog).where(AuditLog.entity_ref == f'counterparty:{parent_id}'))
            await session.execute(delete(CounterpartyBranchAlias).where(CounterpartyBranchAlias.source == source))
            await session.execute(delete(CounterpartyBranch).where(CounterpartyBranch.legal_entity_id == parent_id))
            await session.execute(delete(CounterpartyAlias).where(CounterpartyAlias.source == source))
            await session.execute(delete(Counterparty).where(Counterparty.id == parent_id))
            await session.commit()


@pytest.mark.parametrize('different_parent', [False, True])
async def test_overlapping_branch_import_waits_and_keeps_exact_parent(pg_app, different_parent):
    factory = pg_app._transport.app.state.core.services.db.session_factory
    source = 'race-' + uuid4().hex[:20]
    async with factory() as session:
        parents = [Counterparty(name=source + str(i), legal_name=source + str(i),
                                unp=str(100000000 + (uuid4().int % 800000000))) for i in range(2)]
        session.add_all(parents)
        await session.flush()
        ids = [p.id for p in parents]
        session.add_all([CounterpartyAlias(counterparty_id=p.id, source=source, external_ref=f'head{i}')
                         for i, p in enumerate(parents)])
        await session.commit()
    first = [{'id': f'branch{i}', 'record_kind': 'branch', 'parent_external_ref': 'head0',
              'name': f'Branch {i}', 'raw_branch_code': '0002'} for i in range(2)]
    second = [dict(row, parent_external_ref='head1' if different_parent else 'head0')
              for row in reversed(first)]

    async def contender():
        async with factory() as session:
            try:
                result = await import_counterparties(session, second, source=source)
                await session.commit()
                return result
            except CounterpartyWriteError as error:
                await session.rollback()
                return error

    task = None
    try:
        async with factory() as holder, factory() as observer:
            try:
                async with asyncio.timeout(15):
                    pid = await holder.scalar(text('SELECT pg_backend_pid()'))
                    result = await import_counterparties(holder, first, source=source)
                    assert result['branches_created'] == 2
                    task = asyncio.create_task(contender())
                    while not await _row_waiter_pids(observer, pid):
                        assert not task.done(), 'Competing import must wait for uncommitted source identities'
                        await asyncio.sleep(0.025)
                    await holder.commit()
                    result = await task
                    if different_parent:
                        assert isinstance(result, CounterpartyWriteError)
                        assert result.code == 'branch_identity_conflict'
                    else:
                        assert result['branches_created'] == 0
                        assert result['branches_matched'] == 2
            finally:
                await holder.rollback()
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)
        async with factory() as session:
            branches = list(await session.scalars(select(CounterpartyBranch).where(
                CounterpartyBranch.legal_entity_id.in_(ids))))
            aliases = list(await session.scalars(select(CounterpartyBranchAlias).where(
                CounterpartyBranchAlias.source == source)))
            assert len(branches) == len(aliases) == 2
            assert all(branch.legal_entity_id == ids[0] and branch.portal_branch_code is None for branch in branches)
            assert {a.branch_id for a in aliases} == {b.id for b in branches}
    finally:
        assert task is None or task.done()
        async with factory() as session:
            await session.execute(delete(AuditLog).where(AuditLog.entity_ref.in_([f'counterparty:{i}' for i in ids])))
            await session.execute(delete(CounterpartyBranchAlias).where(CounterpartyBranchAlias.source == source))
            await session.execute(delete(CounterpartyBranch).where(CounterpartyBranch.legal_entity_id.in_(ids)))
            await session.execute(delete(CounterpartyAlias).where(CounterpartyAlias.source == source))
            await session.execute(delete(Counterparty).where(Counterparty.id.in_(ids)))
            await session.commit()


@pytest.mark.parametrize('import_first', [False, True])
async def test_branch_import_and_merge_cannot_cross_committed_identity(pg_app, import_first):
    core = pg_app._transport.app.state.core
    factory = core.services.db.session_factory
    source = 'merge-' + uuid4().hex[:20]
    async with factory() as session:
        parents = [Counterparty(name=source + str(i), legal_name=source + str(i),
                                unp=str(100000000 + (uuid4().int % 800000000))) for i in range(2)]
        session.add_all(parents)
        await session.flush()
        ids = [p.id for p in parents]
        session.add(CounterpartyAlias(counterparty_id=ids[1], source=source, external_ref='head'))
        await session.commit()

    async def branch_import(session):
        await import_counterparties(session, [{'id': 'branch', 'record_kind': 'branch',
                                              'parent_external_ref': 'head', 'name': source}], source=source)

    async def merge(session):
        await mdm.merge(session, core.event_bus, ids[0], ids[1], reference_guard=SalesTouchHistory().has_deals)
        await session.flush()

    async def contender():
        async with factory() as session:
            try:
                await (merge(session) if import_first else branch_import(session))
                pytest.fail('The competing operation must reject the newly committed identity')
            except (ValueError, CounterpartyWriteError) as error:
                await session.rollback()
                return error

    task = None
    try:
        async with factory() as holder, factory() as observer:
            try:
                async with asyncio.timeout(15):
                    pid = await holder.scalar(text('SELECT pg_backend_pid()'))
                    await (branch_import(holder) if import_first else merge(holder))
                    task = asyncio.create_task(contender())
                    while not await _row_waiter_pids(observer, pid):
                        assert not task.done(), 'A real transaction wait is required'
                        await asyncio.sleep(0.025)
                    await holder.commit()
                    error = await task
                    if import_first:
                        assert 'филиалы' in str(error)
                    else:
                        assert error.code == 'parent_archived'
            finally:
                await holder.rollback()
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)
        async with factory() as session:
            parent = await session.get(Counterparty, ids[1])
            assert parent.is_active == import_first
            branch = await session.scalar(select(CounterpartyBranch).where(CounterpartyBranch.legal_entity_id == ids[1]))
            assert (branch is not None) == import_first
    finally:
        assert task is None or task.done()
        async with factory() as session:
            await session.execute(delete(AuditLog).where(AuditLog.entity_ref.in_([f'counterparty:{i}' for i in ids])))
            await session.execute(delete(OutboxEvent).where(OutboxEvent.payload['survivor_id'].as_integer() == ids[0]))
            await session.execute(delete(CounterpartyBranchAlias).where(CounterpartyBranchAlias.source == source))
            await session.execute(delete(CounterpartyBranch).where(CounterpartyBranch.legal_entity_id.in_(ids)))
            await session.execute(delete(CounterpartyAlias).where(CounterpartyAlias.counterparty_id.in_(ids)))
            await session.execute(delete(Counterparty).where(Counterparty.id.in_(ids)))
            await session.commit()
