"""Manual period closure must preserve the same completeness boundary in SQL."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.test_shipping_producer_concurrency_postgres import (
    TIMEOUT,
    connection_identity,
    observe_wait,
    ready,
)


@pytest.mark.parametrize('registry', ['inbox', 'source_control'])
@pytest.mark.parametrize('commit_source', [True, False])
async def test_manual_close_rechecks_source_after_lock_wait(pg_factory, pg_book, registry, commit_source, tmp_path):  # noqa: F811
    from modules.accounting.schemas import CloseInput

    started = asyncio.Event()
    trace = {'registry': registry, 'commit_source': commit_source}
    async with pg_factory() as setup:
        await service.period_for(setup, pg_book[0], '2026-09')
        await setup.commit()
    async with pg_factory() as holder:
        trace['holder'] = await connection_identity(holder)
        sql = ("INSERT INTO accounting.inbox(organization_id,event_key,month,payload) VALUES (:org,'manual-lock','2026-09','{}')"
               if registry == 'inbox' else
               "INSERT INTO accounting.source_control(organization_id,source,version,month) VALUES (:org,'manual-lock',1,'2026-09')")
        await holder.execute(text(sql), {'org': pg_book[0]})

        async def waiting_close():
            async with pg_factory() as session:
                trace['waiter'] = await connection_identity(session)
                original_scalar = session.scalar

                async def hide_pending(statement, *args, **kwargs):
                    if f'accounting.{registry}.entry_id IS NULL' in str(statement):
                        return None
                    return await original_scalar(statement, *args, **kwargs)

                session.scalar = hide_pending
                started.set()
                try:
                    await service.close_period(session, pg_book[0], '2026-09', CloseInput(
                        expected_generation=0, evidence={key: 'Synthetic checked' for key in service.CLOSE_STEPS}), 'tester')
                    await session.commit()
                    return 'closed'
                except DBAPIError as exc:
                    assert 'Unposted documents prevent closing' in str(exc)
                    await session.rollback()
                    return 'blocked'

        task = asyncio.create_task(waiting_close())
        try:
            await ready(started, task)
            assert trace['holder']['pid'] != trace['waiter']['pid']
            assert trace['holder']['txid'] != trace['waiter']['txid']
            trace['lock'] = await observe_wait(SimpleNamespace(factory=pg_factory), trace['waiter']['pid'], trace['holder']['pid'])
            assert 'accounting.organization' in trace['lock']['query']
            if commit_source:
                await holder.commit()
            else:
                await holder.rollback()
            trace['result'] = await asyncio.wait_for(task, TIMEOUT)
            assert trace['result'] == ('blocked' if commit_source else 'closed')
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await holder.rollback()
            (tmp_path / 'manual-source-first-lock.json').write_text(json.dumps(trace, indent=2), encoding='utf-8')
    async with pg_factory() as session:
        assert await session.scalar(text('SELECT closed FROM accounting.period WHERE organization_id=:org'), {'org': pg_book[0]}) is not commit_source
        assert await session.scalar(text(f'SELECT count(*) FROM accounting.{registry}')) == int(commit_source)


@pytest.mark.parametrize('commit_close', [True, False])
async def test_manual_close_first_preserves_waiting_delivery(pg_factory, pg_book, posting, commit_close, tmp_path):  # noqa: F811
    from datetime import date

    from modules.accounting import reports
    from modules.accounting.schemas import CloseInput

    started = asyncio.Event()
    trace = {'commit_close': commit_close}
    async with pg_factory() as setup:
        await service.period_for(setup, pg_book[0], '2026-09')
        await setup.commit()
    async with pg_factory() as holder:
        trace['holder'] = await connection_identity(holder)
        await service.close_period(holder, pg_book[0], '2026-09', CloseInput(
            expected_generation=0, evidence={key: 'Synthetic checked' for key in service.CLOSE_STEPS}), 'tester')

        async def waiting_delivery():
            async with pg_factory() as session:
                trace['waiter'] = await connection_identity(session)
                started.set()
                row = await service.receive(session, pg_book[0], 'manual-waiting-delivery', '2026-09', posting().model_dump(mode='json'))
                await session.commit()
                return {'id': row.id, 'entry_id': row.entry_id, 'error': row.error}

        task = asyncio.create_task(waiting_delivery())
        try:
            await ready(started, task)
            assert trace['holder']['pid'] != trace['waiter']['pid']
            assert trace['holder']['txid'] != trace['waiter']['txid']
            trace['lock'] = await observe_wait(SimpleNamespace(factory=pg_factory), trace['waiter']['pid'], trace['holder']['pid'])
            if commit_close:
                await holder.commit()
            else:
                await holder.rollback()
            trace['result'] = await asyncio.wait_for(task, TIMEOUT)
            assert trace['result']['entry_id'] is None
            assert bool(trace['result']['error']) is commit_close
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await holder.rollback()
            (tmp_path / 'manual-close-first-lock.json').write_text(json.dumps(trace, indent=2), encoding='utf-8')
    async with pg_factory() as session:
        assert await session.scalar(text('SELECT closed FROM accounting.period WHERE organization_id=:org'), {'org': pg_book[0]}) is commit_close
        result = await reports.report(session, pg_book[0], date(2026, 9, 1), date(2026, 9, 30))
        assert result['status'] == 'preliminary' and result['pending_documents'] == 1


@pytest.mark.parametrize('already_closed', [False, True])
async def test_manual_close_requires_complete_evidence(pg_factory, pg_book, already_closed):  # noqa: F811
    valid = {key: 'Synthetic checked' for key in service.CLOSE_STEPS}
    invalid = [{}, {key: value for key, value in valid.items() if key != 'bank'}, {**valid, 'extra': 'checked'}]
    invalid += [{**valid, 'bank': value} for value in [None, 1, '', ' \t\n\u00a0\u001c', 'x' * 1001]]
    async with pg_factory() as session:
        await service.period_for(session, pg_book[0], '2026-09')
        await session.commit()
        statement = text('UPDATE accounting.period SET closed=true,closed_generation=generation,evidence=CAST(:evidence AS json) WHERE organization_id=:org')
        if already_closed:
            await session.execute(statement, {'org': pg_book[0], 'evidence': json.dumps(valid)})
            await session.commit()
        failures = []
        for evidence in invalid:
            package = await session.begin_nested()
            try:
                await session.execute(statement, {'org': pg_book[0], 'evidence': json.dumps(evidence)})
                await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
            except DBAPIError as exc:
                assert 'evidence' in str(exc.orig).lower()
            else:
                failures.append(evidence)
            finally:
                await package.rollback()
        assert not failures, failures
        await session.execute(statement, {'org': pg_book[0], 'evidence': json.dumps({**valid, 'bank': 'x' * 1000})})
        await session.commit()


async def test_manual_close_requires_earlier_month_then_allows_sequence(pg_factory, pg_book):  # noqa: F811
    from modules.accounting.schemas import CloseInput

    async with pg_factory() as session:
        await service.period_for(session, pg_book[0], '2026-09')
        await service.period_for(session, pg_book[0], '2026-10')
        await session.commit()
        evidence = {key: 'Synthetic checked' for key in service.CLOSE_STEPS}
        with pytest.raises(DBAPIError, match='Close earlier periods first'):
            await session.execute(text("UPDATE accounting.period SET closed=true,closed_generation=generation,evidence=CAST(:evidence AS json) WHERE organization_id=:org AND month='2026-10'"),
                                  {'org': pg_book[0], 'evidence': json.dumps(evidence)})
            await session.commit()
        await session.rollback()
        # Two legitimate manual close calls in one transaction use current state,
        # not a root-start snapshot that still records September as open.
        for month in ['2026-09', '2026-10']:
            await service.close_period(session, pg_book[0], month, CloseInput(expected_generation=0, evidence=evidence), 'tester')
        await session.commit()
        assert await session.scalar(text('SELECT count(*) FROM accounting.period WHERE organization_id=:org AND closed'),
                                    {'org': pg_book[0]}) == 2


@pytest.mark.parametrize('expected_generation', [0, 1])
async def test_manual_close_sql_checks_review_generation(pg_factory, pg_book, posting, monkeypatch, expected_generation):  # noqa: F811
    from modules.accounting.schemas import CloseInput

    async def bypass_review_check(session, org_id, month, data):
        return await service.period_for(session, org_id, month), []

    async with pg_factory() as session:
        await service.post(session, pg_book[0], posting(), 'tester')
        await session.commit()
        monkeypatch.setattr(service, 'validate_close_period', bypass_review_check)
        command = CloseInput(expected_generation=expected_generation,
                             evidence={key: 'Synthetic checked' for key in service.CLOSE_STEPS})
        if expected_generation == 0:
            with pytest.raises(DBAPIError, match='period structure'):
                await service.close_period(session, pg_book[0], '2026-09', command, 'tester')
                await session.commit()
            await session.rollback()
        else:
            await service.close_period(session, pg_book[0], '2026-09', command, 'tester')
            await session.commit()
        assert await session.scalar(text('SELECT closed FROM accounting.period WHERE organization_id=:org'),
                                    {'org': pg_book[0]}) is bool(expected_generation)


@pytest.mark.parametrize('policy_dates,allowed', [
    ([], False),
    ([('2026-09-15', True)], False),
    ([('2026-01-01', False)], False),
    ([('2026-01-01', True), ('2026-09-15', False)], False),
    ([('2026-01-01', False), ('2026-09-01', True)], True),
    ([('2026-01-01', True), ('2026-09-15', True)], True),
    ([('2026-01-01', True), ('2026-10-01', False)], True),
])
async def test_manual_close_requires_applicable_verified_policies(pg_factory, policy_dates, allowed):  # noqa: F811
    from datetime import date

    from modules.accounting.models import Organization, Policy

    async with pg_factory() as session:
        org = Organization(name='Synthetic policy boundary', unp='999999946')
        session.add(org)
        await session.flush()
        for effective, verified in policy_dates:
            session.add(Policy(organization_id=org.id, effective_from=date.fromisoformat(effective),
                               reference='Synthetic', inventory_method='specific', allocation_basis='direct_cost',
                               depreciation_method='straight_line', normative_reference='Synthetic only',
                               normative_verified=verified, approved_by='tester'))
        await session.flush()
        await service.period_for(session, org.id, '2026-09')
        await session.commit()
        command = text("UPDATE accounting.period SET closed=true,closed_generation=generation,evidence=CAST(:evidence AS json) WHERE organization_id=:org")
        params = {'org': org.id, 'evidence': json.dumps({key: 'Synthetic checked' for key in service.CLOSE_STEPS})}
        if allowed:
            await session.execute(command, params)
            await session.commit()
        else:
            with pytest.raises(DBAPIError, match='Normative basis must be verified'):
                await session.execute(command, params)
                await session.commit()
            await session.rollback()
        assert await session.scalar(text('SELECT closed FROM accounting.period WHERE organization_id=:org'), params) is allowed


@pytest.mark.parametrize('partial', [True, False])
@pytest.mark.parametrize('immediate', [False, True])
async def test_manual_reopen_requires_complete_later_periods(pg_factory, pg_book, partial, immediate):  # noqa: F811
    from modules.accounting.schemas import CloseInput

    async with pg_factory() as session:
        for month in ['2026-09', '2026-10']:
            await service.period_for(session, pg_book[0], month)
        await service.period_for(session, pg_book[0], '2026-11')
        await session.commit()
        for month in ['2026-09', '2026-10']:
            await service.close_period(session, pg_book[0], month, CloseInput(
                expected_generation=0, evidence={key: 'Synthetic checked' for key in service.CLOSE_STEPS}), 'tester')
        await session.commit()
        if immediate:
            await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        if partial:
            with pytest.raises(DBAPIError, match='Reopening.*later'):
                await session.execute(text("UPDATE accounting.period SET closed=false,closed_generation=NULL,evidence='{}' WHERE organization_id=:org AND month='2026-09'"),
                                      {'org': pg_book[0]})
                await session.commit()
            await session.rollback()
            assert await session.scalar(text('SELECT count(*) FROM accounting.period WHERE organization_id=:org AND closed'),
                                        {'org': pg_book[0]}) == 2
        else:
            await service.reopen_period(session, pg_book[0], '2026-09', 'Synthetic full reopening', 'tester')
            await session.commit()
            rows = (await session.execute(text('SELECT month,closed,closed_generation,generation,evidence FROM accounting.period WHERE organization_id=:org ORDER BY month'),
                                          {'org': pg_book[0]})).all()
            assert [row.month for row in rows] == ['2026-09', '2026-10', '2026-11']
            assert all(not row.closed and row.closed_generation is None and row.generation == 0 and row.evidence == {} for row in rows)


@pytest.mark.parametrize('from_month,remaining_closed', [
    ('2026-08', []), ('2026-09', []), ('2026-10', ['2026-09']),
    ('2026-11', ['2026-09', '2026-10']), ('2026-12', ['2026-09', '2026-10']),
])
async def test_manual_reopen_existing_open_and_absent_targets(pg_factory, pg_book, from_month, remaining_closed):  # noqa: F811
    from modules.accounting.schemas import CloseInput

    async with pg_factory() as session:
        for month in ['2026-09', '2026-10', '2026-11']:
            await service.period_for(session, pg_book[0], month)
        await session.commit()
        for month in ['2026-09', '2026-10']:
            await service.close_period(session, pg_book[0], month, CloseInput(
                expected_generation=0, evidence={key: 'Synthetic checked' for key in service.CLOSE_STEPS}), 'tester')
        await session.commit()
        await service.reopen_period(session, pg_book[0], from_month, 'Synthetic supported target', 'tester')
        await session.commit()
        rows = (await session.execute(text('SELECT month,closed,closed_generation,generation,evidence FROM accounting.period WHERE organization_id=:org ORDER BY month'),
                                      {'org': pg_book[0]})).all()
        assert [row.month for row in rows if row.closed] == remaining_closed
        assert len(rows) == 3 and all(row.generation == 0 for row in rows)
        assert all(row.closed_generation is None and row.evidence == {} for row in rows if not row.closed)


@pytest.mark.parametrize('immediate', [False, True])
@pytest.mark.parametrize('followup', ['posting', 'late-evidence'])
async def test_manual_reopen_validates_later_work_at_commit(pg_factory, pg_book, posting, immediate, followup):  # noqa: F811
    from modules.accounting.schemas import CloseInput

    async with pg_factory() as session:
        for month in ['2026-09', '2026-10']:
            await service.period_for(session, pg_book[0], month)
        await session.commit()
        for month in ['2026-09', '2026-10']:
            await service.close_period(session, pg_book[0], month, CloseInput(
                expected_generation=0, evidence={key: 'Synthetic checked' for key in service.CLOSE_STEPS}), 'tester')
        await session.commit()
        if immediate:
            await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        await service.reopen_period(session, pg_book[0], '2026-09', 'Synthetic validated reopening', 'tester')
        if followup == 'posting':
            await service.post(session, pg_book[0], posting(source='after-reopening'), 'tester')
            await session.commit()
            assert await session.scalar(text('SELECT count(*) FROM accounting.period WHERE NOT closed AND generation=1')) == 2
        else:
            await session.execute(text("UPDATE accounting.period SET evidence='{\"late\":\"uncleared\"}' WHERE organization_id=:org AND month='2026-10'"), {'org': pg_book[0]})
            with pytest.raises(DBAPIError, match='Reopening.*later'):
                await session.commit()
            await session.rollback()
            assert await session.scalar(text('SELECT count(*) FROM accounting.period WHERE closed')) == 2


async def test_manual_reopen_cannot_fabricate_generation(pg_factory, pg_book):  # noqa: F811
    from modules.accounting.schemas import CloseInput

    async with pg_factory() as session:
        await service.period_for(session, pg_book[0], '2026-09')
        await session.commit()
        await service.close_period(session, pg_book[0], '2026-09', CloseInput(
            expected_generation=0, evidence={key: 'Synthetic checked' for key in service.CLOSE_STEPS}), 'tester')
        await session.commit()
        for immediate in [False, True]:
            if immediate:
                await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
            with pytest.raises(DBAPIError, match='Manual reopening cannot increase'):
                await session.execute(text("UPDATE accounting.period SET closed=false,closed_generation=NULL,evidence='{}',generation=generation+1 WHERE organization_id=:org"), {'org': pg_book[0]})
                await session.commit()
            await session.rollback()
            assert await session.scalar(text('SELECT generation FROM accounting.period WHERE organization_id=:org'), {'org': pg_book[0]}) == 0


@pytest.mark.parametrize('registry', ['inbox', 'source_control'])
@pytest.mark.parametrize('arrival', ['before', 'after'])
@pytest.mark.parametrize('immediate', [False, True])
async def test_manual_close_rejects_pending_source_in_same_root(pg_factory, pg_book, registry, arrival, immediate):  # noqa: F811
    async with pg_factory() as session:
        await service.period_for(session, pg_book[0], '2026-09')
        await session.commit()
        if immediate:
            await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        params = {'org': pg_book[0], 'evidence': json.dumps({key: 'Synthetic checked' for key in service.CLOSE_STEPS})}
        source_sql = (
            "INSERT INTO accounting.inbox(organization_id,event_key,month,payload) "
            "VALUES (:org,'manual-pending','2026-09','{}')" if registry == 'inbox' else
            "INSERT INTO accounting.source_control(organization_id,source,version,month) "
            "VALUES (:org,'manual-pending',1,'2026-09')"
        )
        close_sql = (
            "UPDATE accounting.period SET closed=true,closed_generation=generation,evidence=CAST(:evidence AS json) "
            "WHERE organization_id=:org AND month='2026-09'"
        )
        with pytest.raises(DBAPIError, match='Unposted documents prevent closing'):
            for statement in ([source_sql, close_sql] if arrival == 'before' else [close_sql, source_sql]):
                await session.execute(text(statement), params)
            await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        await session.rollback()
        assert await session.scalar(text('SELECT closed FROM accounting.period WHERE organization_id=:org'), params) is False


async def test_manual_close_accepts_later_delivery_as_pending(pg_factory, pg_book, posting):  # noqa: F811
    from datetime import date

    from modules.accounting import reports
    from modules.accounting.schemas import CloseInput

    async with pg_factory() as session:
        await service.period_for(session, pg_book[0], '2026-09')
        await session.commit()
        await service.close_period(session, pg_book[0], '2026-09', CloseInput(
            expected_generation=0, evidence={key: 'Synthetic checked' for key in service.CLOSE_STEPS}), 'tester')
        await session.commit()
        assert (await reports.report(session, pg_book[0], date(2026, 9, 1), date(2026, 9, 30)))['status'] == 'closed_periods'
        await session.commit()
        row = await service.receive(session, pg_book[0], 'late-after-commit', '2026-09', posting().model_dump(mode='json'))
        await session.commit()
        assert row.entry_id is None and row.error
        result = await reports.report(session, pg_book[0], date(2026, 9, 1), date(2026, 9, 30))
        assert result['status'] == 'preliminary' and result['pending_documents'] == 1
