"""Real PostgreSQL row-lock waits between invoice replacement and late receipts."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from core.domain.models import OutboxEvent
from modules.finance.aging import _payments_outstanding
from modules.finance.allocation import apply_allocation
from modules.finance.document_versions import on_original_superseded
from modules.finance.models import Payment, PaymentAllocation


@pytest.mark.parametrize('first_writer', ['supersede', 'settle'])
async def test_replacement_and_late_payment_wait_and_keep_history(pg_app, first_writer):
    core = pg_app._transport.app.state.core
    factory = core.services.db.session_factory
    key = uuid4().hex
    document_id = f'lock-{key}'
    payload = {
        'kind': 'invoice', 'document_id': document_id,
        'replacement_document_id': f'{document_id}-new',
        'number': key, 'deal_id': None, 'amount': '240',
    }
    async with factory() as setup:
        old = Payment(ref=key, entity_ref=f'document:{document_id}',
                      amount=Decimal('240'), kind='receivable')
        replacement = Payment(ref=f'{key}-new', entity_ref=f'document:{document_id}-new',
                              amount=Decimal('360'), kind='receivable')
        setup.add_all([old, replacement])
        await setup.flush()
        await apply_allocation(setup, core.event_bus, old, Decimal('50'))
        await setup.commit()
        old_id, replacement_id = old.id, replacement.id

    task = None
    try:
        async with factory() as waiter, factory() as holder:
            stale = await waiter.get(Payment, old_id)
            assert stale.status == 'partial'
            waiter_pid = await waiter.scalar(text('SELECT pg_backend_pid()'))
            holder_pid = await holder.scalar(text('SELECT pg_backend_pid()'))
            if first_writer == 'supersede':
                await on_original_superseded(payload, SimpleNamespace(session=holder, services=core.services))
            else:
                payment = await holder.get(Payment, old_id)
                await apply_allocation(holder, core.event_bus, payment, Decimal('190'))

            async def second_writer():
                if first_writer == 'supersede':
                    await apply_allocation(waiter, core.event_bus, stale, Decimal('10'))
                else:
                    await on_original_superseded(payload, SimpleNamespace(session=waiter, services=core.services))
                await waiter.commit()

            task = asyncio.create_task(second_writer())
            async with asyncio.timeout(10), factory() as observer:
                for _ in range(100):
                    blocked = await observer.scalar(text(
                        'SELECT :holder = ANY(pg_blocking_pids(:waiter))',
                    ), {'holder': holder_pid, 'waiter': waiter_pid})
                    if blocked:
                        break
                    await asyncio.sleep(0.02)
                assert blocked, 'The competing transaction never waited on the invoice row lock'
                assert not task.done()
            await holder.commit()
            await asyncio.wait_for(task, timeout=10)

        async with factory() as check:
            old = await check.get(Payment, old_id)
            replacement = await check.get(Payment, replacement_id)
            assert old.status == ('superseded' if first_writer == 'supersede' else 'paid')
            assert (old.paid_at is not None) == (first_writer == 'settle')
            assert old.entity_ref == f'document:{document_id}'
            assert replacement.status == 'pending' and replacement.paid_at is None
            allocations = (await check.execute(select(PaymentAllocation).where(
                PaymentAllocation.payment_id.in_([old_id, replacement_id]),
            ).order_by(PaymentAllocation.id))).scalars().all()
            late_amount = Decimal('10') if first_writer == 'supersede' else Decimal('190')
            assert [(row.payment_id, row.amount) for row in allocations] == [
                (old_id, Decimal('50')), (old_id, late_amount),
            ]
            outstanding = await _payments_outstanding(check, ('receivable',))
            assert [(p.id, amount) for p, amount in outstanding if p.id in (old_id, replacement_id)] == [
                (replacement_id, Decimal('360')),
            ]
            events = (await check.execute(select(OutboxEvent).where(
                OutboxEvent.payload['entity_ref'].as_string() == f'payment:{old_id}',
            ).order_by(OutboxEvent.id))).scalars().all()
            assert sum(event.event_type == 'finance.invoice.superseded' for event in events) == 1
            assert sum(event.event_type == 'finance.payment.paid' for event in events) == (first_writer == 'settle')
            received = [event for event in events if event.event_type == 'finance.payment.received']
            assert [Decimal(event.payload['amount']) for event in received] == [Decimal('50'), late_amount]
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
