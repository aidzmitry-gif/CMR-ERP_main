"""Actual invoice Finance delivery in disposable, migration-built PostgreSQL."""
import asyncio
from copy import deepcopy
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from core.domain.models import OutboxEvent
from modules.finance import document_versions as projection
from modules.finance.allocation import apply_allocation
from modules.finance.models import Payment, PaymentAllocation
from modules.logistics.models import CarrierBid, CarrierRfqInvite
from modules.sales.models import DealDocument
from modules.sales.reservation_source import SalesReservationSource
from tests.accounting.test_postgres import pg_factory as pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import (
    issuance_pg as issuance_pg,  # noqa: F401
)
from tests.test_invoice_cancellation import cancel_request, exercise_cancelled_invoice_replacement
from tests.test_invoice_issuance import command, create, seed

pytestmark = [pytest.mark.integration, pytest.mark.parametrize('pg_factory', ['finance_0196'], indirect=True)]


def runtime(client):
    core = client._transport.app.state.core
    assert projection.on_invoice_issued in core.event_bus._handlers['sales.invoice.issued']
    assert projection.on_invoice_cancelled in core.event_bus._handlers['sales.invoice.cancelled']
    return core.event_bus, core.services


async def last_event(factory, event_type):
    async with factory() as session:
        saved = await session.scalar(select(OutboxEvent).where(
            OutboxEvent.event_type == event_type).order_by(OutboxEvent.id.desc()).limit(1))
        assert saved is not None
        return saved.id, deepcopy(saved.payload)


async def original(client, factory, mode='stock'):
    async with factory() as session:
        ids, base = await seed(client, session, physical='10' if mode == 'stock' else '0')
    if mode == 'stock':
        cmd, _ = await command(client, ids, base)
    else:
        base['reserve_mode'] = 'on_order'
        response = await client.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
        assert response.status_code == 200, response.text
        preview = response.json()
        cmd = {**base, 'request_key': 'native-finance-on-order',
               'expected_document_version': preview['document_version'],
               'expected_basis_digest': preview['basis_digest'],
               'allocations': [], 'unreserved_confirmed': True}
    response = await create(client, ids, cmd)
    assert response.status_code == 201, response.text
    _, payload = await last_event(factory, 'sales.invoice.issued')
    return ids, payload


async def cancellation_prerequisites(factory):
    # Same native prerequisites as the existing cancellation helper.
    async with factory() as session:
        conn = await session.connection()
        for model in (CarrierBid, CarrierRfqInvite):
            await conn.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        await session.commit()


async def deliver_with_observed_contention(factory, bus, services, monkeypatch, event_types):
    """Two real relay workers; prove domain contention, not just outbox locks."""
    entered, second_entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    account_lock = services.accounting.lock_event_organization
    pids = {}
    ordinal = 0
    workers = []

    async def gated_lock(session, organization_id):
        nonlocal ordinal
        ordinal += 1
        number = ordinal
        pid = await session.scalar(text('SELECT pg_backend_pid()'))
        if number == 1:
            await account_lock(session, organization_id)
            pids['first'] = pid
            entered.set()
            await asyncio.wait_for(release.wait(), timeout=10)
        else:
            if number == 2:
                pids['second'] = pid
                second_entered.set()
            await account_lock(session, organization_id)

    monkeypatch.setattr(services.accounting, 'lock_event_organization', gated_lock)
    try:
        workers.append(asyncio.create_task(bus.relay_pending(factory, services, event_types=event_types)))
        await asyncio.wait_for(entered.wait(), timeout=10)
        workers.append(asyncio.create_task(bus.relay_pending(factory, services, event_types=event_types)))
        await asyncio.wait_for(second_entered.wait(), timeout=10)
        assert pids['first'] != pids['second']
        async with factory() as observer:
            for _ in range(125):
                blockers = await observer.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': pids['second']})
                if pids['first'] in blockers:
                    break
                await asyncio.sleep(0.02)  # bounded observation, not a race timing assumption
            else:
                raise AssertionError('Second relay never blocked on the first domain transaction')
        release.set()
        delivered = await asyncio.wait_for(asyncio.gather(*workers), timeout=15)
        assert sum(delivered) == 2, delivered
    finally:
        release.set()
        for worker in workers:
            if not worker.done():
                worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        monkeypatch.setattr(services.accounting, 'lock_event_organization', account_lock)
        assert all(worker.done() for worker in workers)


@pytest.mark.parametrize('mode', ['stock', 'on_order'])
async def test_pg_registered_finance_concurrent_issue_replay(issuance_pg, monkeypatch, mode):
    client, factory = issuance_pg
    _, payload = await original(client, factory, mode)
    bus, services = runtime(client)
    async with factory() as session:
        doc = await session.get(DealDocument, payload['document_id'])
        original_identity = (doc.original_html, doc.version, doc.content_sha256, doc.amount)
        first = await session.scalar(select(OutboxEvent.id).where(OutboxEvent.event_type == 'sales.invoice.issued'))
        bus.emit(session, 'sales.invoice.issued', deepcopy(payload))
        await session.flush()
        event_ids = list(await session.scalars(select(OutboxEvent.id).where(
            OutboxEvent.event_type == 'sales.invoice.issued').order_by(OutboxEvent.id)))
        assert len(event_ids) == 2 and event_ids[0] == first
        await session.commit()
    await deliver_with_observed_contention(factory, bus, services, monkeypatch, ('sales.invoice.issued',))
    async with factory() as session:
        saved = list(await session.scalars(select(Payment)))
        assert len(saved) == 1
        payment = saved[0]
        assert (payment.organization_id, payment.deal_id, payment.entity_ref) == (
            payload['organization_id'], payload['deal_id'], f"document:{payload['document_id']}")
        assert payment.amount == Decimal(payload['amount']) and payment.status == 'pending' and payment.paid_at is None
        assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type.in_(('finance.payment.received', 'finance.payment.paid')))) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.id.in_(event_ids), OutboxEvent.processed_at.is_not(None))) == 2
        doc = await session.get(DealDocument, payload['document_id'])
        assert (doc.original_html, doc.version, doc.content_sha256, doc.amount) == original_identity


@pytest.mark.parametrize('payment_state', ['partial', 'paid'])
async def test_pg_registered_finance_replacement_rollback(issuance_pg, monkeypatch, payment_state):
    client, factory = issuance_pg
    await cancellation_prerequisites(factory)
    bus, services = runtime(client)

    class DeliveredBeforeRevision:
        def __getattr__(self, key):
            return getattr(client, key)

        async def post(self, path, **kwargs):
            if path.endswith('/revision'):
                assert await bus.relay_pending(factory, services, event_types=('sales.invoice.issued',)) == 1
                async with factory() as funding:
                    payment = await funding.scalar(select(Payment))
                    assert payment is not None
                    amount = Decimal('20') if payment_state == 'partial' else payment.amount
                    await apply_allocation(funding, bus, payment, amount)
                    await funding.commit()
            return await client.post(path, **kwargs)

    async with factory() as setup:
        await exercise_cancelled_invoice_replacement(DeliveredBeforeRevision(), setup)
    event_id, payload = await last_event(factory, 'sales.invoice.issued')
    async with factory() as baseline:
        old = await baseline.scalar(select(Payment))
        old_id = old.id
        before = (old.status, old.paid_at, old.amount, old.description)
        allocations = list((await baseline.execute(select(PaymentAllocation.id, PaymentAllocation.payment_id,
            PaymentAllocation.amount, PaymentAllocation.allocated_at))).all())
        assert before[0] == payment_state

    real_fx = projection.event_amount
    seen = []
    async def after_retirement(amount, currency, trusted, ctx):
        previous = await ctx.session.get(Payment, old_id)
        assert previous.status == ('superseded' if payment_state == 'partial' else 'paid')
        await ctx.session.flush()  # prove a DB write is rolled back, not just a dirty identity map
        seen.append(previous.status)
        raise RuntimeError('Synthetic failure after predecessor retirement')
    monkeypatch.setattr(projection, 'event_amount', after_retirement)
    with pytest.raises(RuntimeError, match='after predecessor retirement'):
        await bus.relay_pending(factory, services, event_types=('sales.invoice.issued',))
    assert len(seen) == 1
    async with factory() as fresh:
        old = await fresh.get(Payment, old_id)
        assert (old.status, old.paid_at, old.amount, old.description) == before
        assert list((await fresh.execute(select(PaymentAllocation.id, PaymentAllocation.payment_id,
            PaymentAllocation.amount, PaymentAllocation.allocated_at))).all()) == allocations
        assert await fresh.scalar(select(func.count()).select_from(Payment)) == 1
        assert (await fresh.get(OutboxEvent, event_id)).processed_at is None
    monkeypatch.setattr(projection, 'event_amount', real_fx)
    assert await bus.relay_pending(factory, services, event_types=('sales.invoice.issued',)) == 1
    async with factory() as fresh:
        old = await fresh.get(Payment, old_id)
        assert old.status == ('superseded' if payment_state == 'partial' else 'paid')
        assert old.paid_at == before[1]
        assert list((await fresh.execute(select(PaymentAllocation.id, PaymentAllocation.payment_id,
            PaymentAllocation.amount, PaymentAllocation.allocated_at))).all()) == allocations
        current = await fresh.scalar(select(Payment).where(Payment.entity_ref == f"document:{payload['document_id']}"))
        assert current is not None and current.status == 'pending' and current.paid_at is None
        assert (await fresh.get(OutboxEvent, event_id)).processed_at is not None


async def test_pg_registered_finance_cancel_delayed_issue(issuance_pg, monkeypatch):
    client, factory = issuance_pg
    await cancellation_prerequisites(factory)
    ids, payload = await original(client, factory)
    bus, services = runtime(client)
    assert await bus.relay_pending(factory, services, event_types=('sales.invoice.issued',)) == 1
    async with factory() as session:
        source = await SalesReservationSource().invoice_reservation(session, payload['document_id'])
        await session.commit()
    path, request = await cancel_request(client, ids['org'], source)
    response = await client.post(path, json=request)
    assert response.status_code == 201, response.text
    cancellation_id, _ = await last_event(factory, 'sales.invoice.cancelled')
    async with factory() as session:
        bus.emit(session, 'sales.invoice.issued', deepcopy(payload))
        await session.flush()
        delayed_id = await session.scalar(select(func.max(OutboxEvent.id)).where(
            OutboxEvent.event_type == 'sales.invoice.issued'))
        await session.commit()
    await deliver_with_observed_contention(factory, bus, services, monkeypatch,
                                          ('sales.invoice.issued', 'sales.invoice.cancelled'))
    async with factory() as session:
        payment, = list(await session.scalars(select(Payment)))
        assert payment.status == 'cancelled' and payment.paid_at is None
        assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.id.in_((cancellation_id, delayed_id)), OutboxEvent.processed_at.is_not(None))) == 2
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type.in_(('finance.payment.received', 'finance.payment.paid')))) == 0
