"""Document-only Finance seam: fixed identity, no duplicate demand, no moved cash."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import OutboxEvent
from core.services.eventbus import OutboxEventBus
from modules.finance.aging import _payments_outstanding
from modules.finance.allocation import apply_allocation
from modules.finance.document_versions import on_original_issued, on_original_superseded
from modules.finance.models import Payment, PaymentAllocation
from modules.sales.models import PriceQuote
from tests.test_document_versions import make_invoice


async def test_invoice_projection_replay_is_idempotent(api, session):
    _, doc, *_ = await make_invoice(api, session)
    ctx = SimpleNamespace(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    event = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == 'sales.document.posted'))).scalars().one()
    await on_original_issued(event.payload, ctx)
    await session.flush()
    await on_original_issued(event.payload, ctx)
    await session.commit()
    payments = (await session.execute(select(Payment))).scalars().all()
    assert len(payments) == 1
    assert payments[0].entity_ref == f"document:{doc['id']}"
    assert payments[0].amount == Decimal('240')


@pytest.mark.parametrize(
    ('late_amount', 'expected_status', 'manual_paid'),
    [('10', 'superseded', False), ('190', 'paid', False), pytest.param('10', 'paid', True, id='manual-paid')],
)
async def test_replacement_retires_old_demand_and_preserves_allocated_cash(
    api, session, late_amount, expected_status, manual_paid,
):
    _, old, sku, cp, _ = await make_invoice(api, session)
    ctx = SimpleNamespace(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    original_event = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == 'sales.document.posted'))).scalars().one()
    await on_original_issued(original_event.payload, ctx)
    await session.flush()
    old_payment = (await session.execute(select(Payment))).scalars().one()
    receipt_url = f'/finance/payments/{old_payment.id}/allocations'
    first_receipt = await api.post(receipt_url, json={'amount': '50'})
    assert first_receipt.status_code == 201
    first_allocation_id = first_receipt.json()['id']
    assert old_payment.status == 'partial'
    manual_paid_at = None
    if manual_paid:
        marked = await api.patch(f'/finance/payments/{old_payment.id}', json={'status': 'paid'})
        assert marked.status_code == 200
        assert old_payment.status == 'paid' and old_payment.paid_at is not None
        manual_paid_at = old_payment.paid_at
    new = (await api.post(f"/sales/documents/{old['id']}/revision", json={'reason':'Replacement', 'request_key':'finance-revision'})).json()
    session.add(PriceQuote(sku_code=sku.code, counterparty=cp.name, price=Decimal('150')))
    await session.commit()
    assert (await api.post(f"/sales/documents/{new['id']}/issue")).status_code == 200
    replacement_event = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == 'sales.document.superseded'))).scalars().one()
    await on_original_superseded(replacement_event.payload, ctx)
    await session.flush()
    await on_original_superseded(replacement_event.payload, ctx)
    new_event = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == 'sales.document.posted').order_by(OutboxEvent.id.desc()))).scalars().first()
    await on_original_issued(new_event.payload, ctx)
    await session.commit()
    payments = (await session.execute(select(Payment).order_by(Payment.id))).scalars().all()
    assert len(payments) == 2
    assert [p.amount for p in payments] == [Decimal('240'), Decimal('360')]
    assert payments[0].status == ('paid' if manual_paid else 'superseded')
    assert payments[1].status == 'pending'
    allocations = (await session.execute(select(PaymentAllocation))).scalars().all()
    assert [(a.payment_id, a.amount) for a in allocations] == [(old_payment.id, Decimal('50'))]
    outstanding = await _payments_outstanding(session, ('receivable',))
    assert [(p.id, amount) for p, amount in outstanding] == [(payments[1].id, Decimal('360'))]

    # A receipt naming the retired invoice stays on that exact historical version.
    assert (await api.post(receipt_url, json={'amount': late_amount})).status_code == 201
    outstanding = await _payments_outstanding(session, ('receivable',))
    assert [(p.id, amount) for p, amount in outstanding] == [(payments[1].id, Decimal('360'))]
    assert old_payment.status == expected_status
    if manual_paid:
        assert old_payment.paid_at == manual_paid_at
    assert old_payment.entity_ref == f"document:{old['id']}"
    assert payments[1].entity_ref == f"document:{new['id']}"
    assert payments[1].status == 'pending' and payments[1].paid_at is None
    allocations = (await session.execute(select(PaymentAllocation).order_by(PaymentAllocation.id))).scalars().all()
    assert [(a.payment_id, a.amount) for a in allocations] == [
        (old_payment.id, Decimal('50')), (old_payment.id, Decimal(late_amount)),
    ]
    assert allocations[0].id == first_allocation_id
    received = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == 'finance.payment.received',
    ).order_by(OutboxEvent.id))).scalars().all()
    assert [Decimal(event.payload['amount']) for event in received] == [Decimal('50'), Decimal(late_amount)]
    assert Decimal(received[-1].payload['outstanding']) == Decimal('190') - Decimal(late_amount)
    assert all(event.payload['ref'] == old['number'] for event in received)
    assert all(event.payload['entity_ref'] == f'payment:{old_payment.id}' for event in received)
    if expected_status == 'paid':
        await session.refresh(old_payment)
        assert old_payment.paid_at is not None
        paid_at = old_payment.paid_at
        # A manual paid mark can precede the receipts that reach the invoice total.
        following_amount = '180' if manual_paid else '1'
        assert (await api.post(receipt_url, json={'amount': following_amount})).status_code == 201
        assert old_payment.status == 'paid'
        assert old_payment.paid_at == paid_at
        if manual_paid:
            assert old_payment.paid_at == manual_paid_at
        final_allocations = (await session.execute(select(PaymentAllocation).order_by(PaymentAllocation.id))).scalars().all()
        assert [a.id for a in final_allocations[:2]] == [a.id for a in allocations]
        assert [(a.payment_id, a.amount) for a in final_allocations] == [
            (old_payment.id, Decimal('50')), (old_payment.id, Decimal(late_amount)),
            (old_payment.id, Decimal(following_amount)),
        ]
        outstanding = await _payments_outstanding(session, ('receivable',))
        assert [(p.id, amount) for p, amount in outstanding] == [(payments[1].id, Decimal('360'))]
    else:
        assert old_payment.paid_at is None
    paid = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == 'finance.payment.paid',
    ))).scalars().all()
    assert len(paid) == (1 if expected_status == 'paid' else 0)
    if paid:
        assert paid[0].payload['ref'] == old['number']
        assert paid[0].payload['entity_ref'] == f'payment:{old_payment.id}'
    # Original replay cannot resurrect the superseded demand.
    await on_original_issued(original_event.payload, ctx)
    await on_original_superseded(replacement_event.payload, ctx)
    assert payments[0].status == expected_status


@pytest.mark.parametrize('concurrent_status', ['superseded', 'paid'])
async def test_late_allocation_refreshes_status_from_another_transaction(session, concurrent_status):
    old = Payment(ref='OLD', entity_ref='document:1', amount=Decimal('240'), kind='receivable')
    replacement = Payment(ref='NEW', entity_ref='document:2', amount=Decimal('360'), kind='receivable')
    session.add_all([old, replacement])
    await session.flush()
    bus = OutboxEventBus()
    await apply_allocation(session, bus, old, Decimal('50'))
    await session.commit()

    # The caller has already read the payment when another transaction changes it.
    async with AsyncSession(bind=session.bind, expire_on_commit=False) as other_session:
        if concurrent_status == 'superseded':
            ctx = SimpleNamespace(session=other_session, services=SimpleNamespace(event_bus=bus))
            await on_original_superseded({
                'kind': 'invoice', 'document_id': 1, 'replacement_document_id': 2,
                'number': 'OLD', 'amount': '240',
            }, ctx)
        else:
            other_payment = await other_session.get(Payment, old.id)
            await apply_allocation(other_session, bus, other_payment, Decimal('190'))
        await other_session.commit()

    assert old.status == 'partial'  # stale identity map retained by the caller
    await apply_allocation(session, bus, old, Decimal('10'))
    await session.commit()
    assert old.status == concurrent_status
    assert (old.paid_at is not None) == (concurrent_status == 'paid')
    assert old.entity_ref == 'document:1'
    outstanding = await _payments_outstanding(session, ('receivable',))
    assert [(p.id, amount) for p, amount in outstanding] == [(replacement.id, Decimal('360'))]
    allocations = (await session.execute(select(PaymentAllocation).order_by(PaymentAllocation.id))).scalars().all()
    expected_amounts = ['50', '10'] if concurrent_status == 'superseded' else ['50', '190', '10']
    assert [(a.payment_id, a.amount) for a in allocations] == [
        (old.id, Decimal(amount)) for amount in expected_amounts
    ]
    paid = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == 'finance.payment.paid',
    ))).scalars().all()
    assert len(paid) == (1 if concurrent_status == 'paid' else 0)


@pytest.mark.parametrize('entity_ref', ['document:1', None], ids=['exact-id', 'legacy-ref'])
async def test_supersede_preserves_payment_settled_by_another_transaction(session, entity_ref):
    old = Payment(ref='OLD', entity_ref=entity_ref, amount=Decimal('240'), kind='receivable')
    replacement = Payment(ref='NEW', entity_ref='document:2', amount=Decimal('360'), kind='receivable')
    session.add_all([old, replacement])
    await session.flush()
    bus = OutboxEventBus()
    await apply_allocation(session, bus, old, Decimal('50'))
    await session.commit()

    async with AsyncSession(bind=session.bind, expire_on_commit=False) as other_session:
        other_payment = await other_session.get(Payment, old.id)
        await apply_allocation(other_session, bus, other_payment, Decimal('190'))
        await other_session.commit()
    assert old.status == 'partial'
    ctx = SimpleNamespace(session=session, services=SimpleNamespace(event_bus=bus))
    payload = {
        'kind': 'invoice', 'document_id': 1, 'replacement_document_id': 2,
        'number': 'OLD', 'deal_id': None, 'amount': '240',
    }
    await on_original_superseded(payload, ctx)
    await session.commit()
    assert old.status == 'paid'
    assert old.paid_at is not None
    assert old.entity_ref == entity_ref
    assert replacement.status == 'pending' and replacement.paid_at is None
    await on_original_superseded(payload, ctx)
    await session.commit()
    outstanding = await _payments_outstanding(session, ('receivable',))
    assert [(p.id, amount) for p, amount in outstanding] == [(replacement.id, Decimal('360'))]
    allocations = (await session.execute(select(PaymentAllocation).order_by(PaymentAllocation.id))).scalars().all()
    assert [(a.payment_id, a.amount) for a in allocations] == [
        (old.id, Decimal('50')), (old.id, Decimal('190')),
    ]
    events = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type.in_(
        ['finance.payment.paid', 'finance.invoice.superseded'],
    )).order_by(OutboxEvent.id))).scalars().all()
    assert [event.event_type for event in events] == ['finance.payment.paid', 'finance.invoice.superseded']
    assert all(event.payload['entity_ref'] == f'payment:{old.id}' for event in events)
