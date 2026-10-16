"""Concurrent close retries serialize and publish one canonical outcome event."""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from core.domain.models import OutboxEvent
from modules.accounting.models import AccessGrant, Organization
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.deal_loss import DealLossRequest, DealLossResolution
from modules.sales.models import Deal, DealStageEvent


@pytest.mark.parametrize('outcome',['win','lose'])
async def test_concurrent_close_has_one_event(pg_app,outcome):
    created=await pg_app.post('/sales/deals',json={'number':uuid4().hex,'title':'Synthetic','counterparty':'Synthetic'})
    assert created.status_code==201
    deal_id=created.json()['id']
    factory=pg_app._transport.app.state.core.services.db.session_factory
    command = {'reason_code': 'price'}
    headers = {}
    if outcome == 'lose':
        actor = 'joint-pg-loss'
        headers = {'X-User': actor, 'X-Expected-Principal': actor}
        async with factory() as seed:
            org = Organization(name='Synthetic loss ' + uuid4().hex, unp=str(100000000 + int(uuid4().hex[:8],16) % 800000000))
            seed.add(org)
            await seed.flush()
            seed.add_all([AccessGrant(organization_id=org.id, subject=actor, role='chief'),
                DealOwnership(deal_id=deal_id, organization_id=org.id, snapshot={}, evidence='Synthetic concurrency test', actor=actor)])
            await seed.commit()
            org_id = org.id
        preview = await pg_app.get(f'/sales/organizations/{org_id}/deals/{deal_id}/loss-preview', headers=headers)
        assert preview.status_code == 200, preview.text
        command = {'organization_id': org_id, 'request_key': str(uuid4()),
            'expected_composition_digest': preview.json()['composition_digest'],
            'reason_code': 'price', 'finalize_if_empty': True}
    async with factory() as holder, factory() as observer:
        await holder.execute(select(Deal).where(Deal.id==deal_id).with_for_update())
        holder_pid=await holder.scalar(text('SELECT pg_backend_pid()'))
        tasks=[asyncio.create_task(pg_app.post(f'/sales/deals/{deal_id}/{outcome}',json=command, headers=headers)) for _ in range(2)]
        try:
            async with asyncio.timeout(10):
                while True:
                    await observer.execute(text('SELECT pg_stat_clear_snapshot()'))
                    blocked=await observer.scalar(text('''WITH RECURSIVE blocked(pid) AS (
                        SELECT pid FROM pg_stat_activity WHERE :pid=ANY(pg_blocking_pids(pid))
                        UNION SELECT a.pid FROM pg_stat_activity a JOIN blocked b ON b.pid=ANY(pg_blocking_pids(a.pid))
                    ) SELECT count(*) FROM blocked'''),{'pid':holder_pid})
                    if blocked>=2:
                        break
                    assert not any(task.done() for task in tasks)
                    await asyncio.sleep(0.02)
            await holder.commit()
            responses=await asyncio.gather(*tasks)
            assert sorted(r.status_code for r in responses)==([200,200] if outcome == 'lose' else [200,409]),[r.text for r in responses]
            if outcome == 'lose':
                assert sorted(r.json()['replayed'] for r in responses) == [False, True]
                assert all(r.json()['state'] == 'finalized' for r in responses)
                requests = (await observer.scalars(select(DealLossRequest).where(DealLossRequest.deal_id == deal_id))).all()
                assert len(requests) == 1
                receipts = (await observer.scalars(select(DealLossResolution).where(DealLossResolution.request_id == command['request_key']))).all()
                assert len(receipts) == 1
            event_type='sales.deal.won' if outcome=='win' else 'sales.deal.loss_finalized'
            events=(await observer.scalars(select(OutboxEvent).where(OutboxEvent.event_type==event_type))).all()
            assert len([row for row in events if row.payload.get('deal_id')==deal_id])==1
            history=(await observer.scalars(select(DealStageEvent).where(DealStageEvent.deal_id==deal_id))).all()
            assert len(history)==1
        finally:
            await holder.rollback()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
