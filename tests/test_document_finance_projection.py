"""Document-only Finance seam: fixed identity, no duplicate demand, no moved cash."""
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from core.domain.models import OutboxEvent
from core.services.eventbus import OutboxEventBus
from modules.finance.aging import _payments_outstanding
from modules.finance.document_versions import on_original_issued, on_original_superseded
from modules.finance.models import Payment, PaymentAllocation
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


async def test_replacement_retires_old_demand_and_preserves_allocated_cash(api, session):
    _, old, *_ = await make_invoice(api, session)
    ctx = SimpleNamespace(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    original_event = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == 'sales.document.posted'))).scalars().one()
    await on_original_issued(original_event.payload, ctx)
    await session.flush()
    old_payment = (await session.execute(select(Payment))).scalars().one()
    old_payment.status = 'partial'
    session.add(PaymentAllocation(payment_id=old_payment.id, amount=Decimal('50')))
    await session.commit()
    new = (await api.post(f"/sales/documents/{old['id']}/revision", json={'reason':'Replacement', 'request_key':'finance-revision'})).json()
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
    assert payments[0].status == 'superseded' and payments[1].status == 'pending'
    allocations = (await session.execute(select(PaymentAllocation))).scalars().all()
    assert [(a.payment_id, a.amount) for a in allocations] == [(old_payment.id, Decimal('50'))]
    outstanding = await _payments_outstanding(session, ('receivable',))
    assert [(p.id, amount) for p, amount in outstanding] == [(payments[1].id, Decimal('240'))]
    # Original replay cannot resurrect the superseded demand.
    await on_original_issued(original_event.payload, ctx)
    assert payments[0].status == 'superseded'
