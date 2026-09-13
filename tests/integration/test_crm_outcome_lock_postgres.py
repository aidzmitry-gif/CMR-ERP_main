"""Concurrent close retries serialize and publish one canonical outcome event."""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from core.domain.models import OutboxEvent
from modules.sales.models import Deal, DealStageEvent


@pytest.mark.parametrize('outcome',['win','lose'])
async def test_concurrent_close_has_one_event(pg_app,outcome):
    created=await pg_app.post('/sales/deals',json={'number':uuid4().hex,'title':'Synthetic','counterparty':'Synthetic'})
    assert created.status_code==201
    deal_id=created.json()['id']
    factory=pg_app._transport.app.state.core.services.db.session_factory
    async with factory() as holder, factory() as observer:
        await holder.execute(select(Deal).where(Deal.id==deal_id).with_for_update())
        holder_pid=await holder.scalar(text('SELECT pg_backend_pid()'))
        tasks=[asyncio.create_task(pg_app.post(f'/sales/deals/{deal_id}/{outcome}',json={'reason_code':'price'})) for _ in range(2)]
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
            assert sorted(r.status_code for r in responses)==[200,409],[r.text for r in responses]
            event_type='sales.deal.won' if outcome=='win' else 'sales.deal.lost'
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
