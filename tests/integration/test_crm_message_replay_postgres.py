"""Concurrent history retries block on a real deal lock and create one event."""
import asyncio
from uuid import uuid4

from sqlalchemy import func, select, text

from core.domain.models import OutboxEvent
from modules.sales.models import Deal, Message


async def test_concurrent_history_replay_has_one_row_and_event(pg_app):
    key = uuid4().hex
    created = await pg_app.post('/sales/deals', json={'number':key,'title':'History race','counterparty':'Synthetic'})
    assert created.status_code == 201, created.text
    deal_id = created.json()['id']
    factory = pg_app._transport.app.state.core.services.db.session_factory
    async with factory() as holder, factory() as observer:
        await holder.execute(select(Deal).where(Deal.id == deal_id).with_for_update())
        holder_pid = await holder.scalar(text('SELECT pg_backend_pid()'))
        data = {'text':'History race','request_key':key}
        tasks = [asyncio.create_task(pg_app.post(f'/sales/deals/{deal_id}/messages',json=data)) for _ in range(2)]
        try:
            async with asyncio.timeout(10):
                while True:
                    await observer.execute(text('SELECT pg_stat_clear_snapshot()'))
                    blocked = await observer.scalar(text('''WITH RECURSIVE blocked(pid) AS (
                        SELECT pid FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))
                        UNION SELECT a.pid FROM pg_stat_activity a JOIN blocked b ON b.pid = ANY(pg_blocking_pids(a.pid))
                    ) SELECT count(*) FROM blocked'''), {'pid':holder_pid})
                    if blocked >= 2:
                        break
                    assert not any(task.done() for task in tasks), 'Write did not wait for the deal lock'
                    await asyncio.sleep(0.02)
            await holder.commit()
            results = await asyncio.gather(*tasks)
            assert [result.status_code for result in results] == [201,201], [r.text for r in results]
            assert results[0].json()['id'] == results[1].json()['id']
            assert await observer.scalar(select(func.count()).select_from(Message).where(Message.deal_id == deal_id)) == 1
            events = (await observer.scalars(select(OutboxEvent).where(OutboxEvent.event_type == 'sales.message.sent'))).all()
            assert len([event for event in events if event.payload.get('deal_id') == deal_id]) == 1
        finally:
            await holder.rollback()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
