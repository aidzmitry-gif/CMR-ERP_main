"""Document-only Finance seam: fixed identity, no duplicate demand, no moved cash."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import OutboxEvent
from core.services.eventbus import OutboxEventBus
from modules.finance.aging import _payments_outstanding
from modules.finance.allocation import apply_allocation
from modules.finance.document_versions import on_original_issued, on_original_superseded
from modules.finance.models import Payment, PaymentAllocation
from tests.test_document_versions import make_invoice
from tests.test_finance import finance_org as finance_org  # noqa: F401


async def erp_original(api, session, *, currency="BYN"):
    from core.domain.models import AuditLog
    from modules.finance import document_versions as projection
    from modules.sales.reservation_source import SalesReservationSource
    from tests.test_invoice_issuance import command, create, seed

    ids, base = await seed(api, session)
    if currency == "USD":
        from core.domain.reference import Currency

        session.add(Currency(code="USD", title="Synthetic USD", is_active=True))
        await session.commit()
        changed = await api.post(f"/accounting/organizations/{ids['org']}/seller-profiles", json={
            "source_key": "synthetic-seller-usd", "expected_revision": 1,
            "effective_from": "2026-01-01", "currency": "USD", "address": "Bound address",
            "account": "TEST ACCOUNT", "bank": "TEST BANK", "bik": "TEST BIK",
            "director": "Synthetic director", "evidence": "Synthetic USD seller", "confirmed": True,
        })
        assert changed.status_code == 201, changed.text
        base["currency"] = "USD"
        session.add(AuditLog(actor="synthetic", action="currency.nbrb.quote",
            entity_ref="nbrb:USD:2026-09-01", detail={"currency": "USD", "date": "2026-09-01",
                "official_rate": "3", "scale": 1, "rate": "3", "source": "NBRB"}))
        await session.commit()
    request, _ = await command(api, ids, base)
    issued = await create(api, ids, request)
    assert issued.status_code == 201, issued.text
    event = (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.invoice.issued"))).one()
    payload = deepcopy(event.payload)
    source = SalesReservationSource()
    facts = await source.invoice_financial_lifecycle(session, payload["document_id"],
        organization_id=ids["org"], expected_version=payload["document_version"],
        expected_content_sha256=payload["content_sha256"])
    assert facts["collectible"] and facts["cancellation"] is None
    ctx = SimpleNamespace(session=session, services=api._transport.app.state.core.services)
    # Prove the complete positive path before any fault injection, then undo it.
    savepoint = await session.begin_nested()
    await projection.on_invoice_issued(payload, ctx)
    payment = (await session.scalars(select(Payment))).one()
    assert payment.organization_id == ids["org"] and payment.paid_at is None
    assert payment.due_date is None  # valid_until is not a payment due date.
    await savepoint.rollback()
    return ids, payload, ctx


async def erp_projection_state(session):
    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
    from modules.sales.models import DealDocument

    # Compare all persisted columns, including originals and allocation identity.
    result = []
    for model in (Payment, PaymentAllocation, DealDocument, InvoiceIssuanceReceipt, OutboxEvent):
        rows = await session.execute(select(model.__table__).order_by(*model.__table__.primary_key.columns))
        result.append(tuple(rows.all()))
    return tuple(result)


@pytest.mark.parametrize("amount", ["0.00", "-1.25"], ids=["known-zero", "known-signed"])
async def test_legacy_known_amount_keeps_its_semantics(session, amount):
    from modules.finance.events import on_document_posted

    ctx = SimpleNamespace(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    await on_document_posted({"kind": "invoice", "number": "Synthetic-known", "amount": amount}, ctx)
    await session.flush()
    payment = (await session.scalars(select(Payment))).one()
    assert payment.amount == Decimal(amount) and payment.paid_at is None
    event = (await session.scalars(select(OutboxEvent))).one()
    assert event.event_type == "finance.payment.created" and Decimal(event.payload["amount"]) == Decimal(amount)


@pytest.mark.parametrize("fault", [
    "foreign-organization", "wrong-version", "bool-version", "wrong-content-sha", "wrong-amount",
    "wrong-currency", "wrong-number", "wrong-issuance-anchor", "wrong-deal",
])
async def test_erp_issue_identity_mismatch_is_atomic(api, session, fault):
    from modules.finance.document_versions import on_invoice_issued

    _, payload, ctx = await erp_original(api, session)
    key, value = {
        "foreign-organization": ("organization_id", payload["organization_id"] + 1),
        "wrong-version": ("document_version", payload["document_version"] + 1),
        "bool-version": ("document_version", True),
        "wrong-content-sha": ("content_sha256", "0" * 64),
        "wrong-amount": ("amount", "0.01"), "wrong-currency": ("currency", "USD"),
        "wrong-number": ("number", "SYNTHETIC-WRONG"),
        "wrong-issuance-anchor": ("issuance_receipt", "invalid"),
        "wrong-deal": ("deal_id", payload["deal_id"] + 1),
    }[fault]
    before = await erp_projection_state(session)
    with pytest.raises(ValueError):
        async with session.begin_nested():
            await on_invoice_issued({**payload, key: value}, ctx)
    assert await erp_projection_state(session) == before


@pytest.mark.parametrize("fault", ["legacy-unowned", "foreign-owned", "ambiguous-projections"])
async def test_erp_projection_conflict_is_not_rebound(api, session, fault):
    from modules.accounting.models import Organization
    from modules.finance.document_versions import on_invoice_issued

    _, payload, ctx = await erp_original(api, session)
    await on_invoice_issued(payload, ctx)
    row = (await session.scalars(select(Payment))).one()
    row_id = row.id
    before = await erp_projection_state(session)
    with pytest.raises(ValueError, match="ambiguous|binding conflicts"):
        async with session.begin_nested():
            if fault == "ambiguous-projections":
                session.add(Payment(organization_id=row.organization_id, ref=row.ref,
                    deal_id=row.deal_id, entity_ref=row.entity_ref, amount=row.amount,
                    currency=row.currency, kind="receivable", description=row.description))
            else:
                owner = None
                if fault == "foreign-owned":
                    other = Organization(name="Synthetic foreign", unp="999999998")
                    session.add(other)
                    await session.flush()
                    owner = other.id
                await session.execute(update(Payment).where(Payment.id == row_id).values(organization_id=owner))
            await session.flush()
            await on_invoice_issued(payload, ctx)
    assert await erp_projection_state(session) == before


@pytest.mark.parametrize("fault", ["missing-issuance-receipt", "corrupt-original"])
async def test_erp_projection_requires_persisted_original(api, session, fault):
    from modules.finance.document_versions import on_invoice_issued
    from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
    from modules.sales.models import DealDocument

    _, payload, ctx = await erp_original(api, session)
    before = await erp_projection_state(session)
    with pytest.raises(ValueError):
        async with session.begin_nested():
            if fault == "missing-issuance-receipt":
                await session.execute(delete(InvoiceIssuanceReceipt).where(
                    InvoiceIssuanceReceipt.document_id == payload["document_id"]))
            else:
                await session.execute(update(DealDocument).where(
                    DealDocument.id == payload["document_id"]).values(original_html="Synthetic corruption"))
            await on_invoice_issued(payload, ctx)
    assert await erp_projection_state(session) == before


@pytest.mark.parametrize("fault", ["wrong-cancellation-id", "wrong-cancellation-digest", "wrong-release-id"])
async def test_erp_cancellation_event_requires_exact_receipt(api, session, fault):
    from modules.finance.document_versions import on_invoice_cancelled
    from modules.sales.reservation_source import SalesReservationSource
    from tests.test_invoice_cancellation import cancel_request

    ids, original, ctx = await erp_original(api, session)
    source = SalesReservationSource()
    reservation = await source.invoice_reservation(session, original["document_id"])
    await session.commit()
    path, request = await cancel_request(api, ids["org"], reservation)
    cancelled = await api.post(path, json=request)
    assert cancelled.status_code == 201, cancelled.text
    event = (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.invoice.cancelled"))).one()
    payload = deepcopy(event.payload)
    # This is a real stock cancellation, with a real persisted release receipt.
    facts = await source.invoice_financial_lifecycle(session, original["document_id"],
        organization_id=ids["org"], expected_version=original["document_version"],
        expected_content_sha256=original["content_sha256"])
    assert not facts["collectible"] and facts["cancellation"]["release_id"] is not None
    await on_invoice_cancelled(payload, ctx)
    key = {"wrong-cancellation-id": "cancellation_id", "wrong-cancellation-digest": "cancellation_digest",
           "wrong-release-id": "release_id"}[fault]
    value = {"cancellation_id": "00000000-0000-0000-0000-000000000000",
             "cancellation_digest": "0" * 64, "release_id": payload["release_id"] + 1}[key]
    before = await erp_projection_state(session)
    with pytest.raises(ValueError, match="does not match its receipt"):
        async with session.begin_nested():
            await on_invoice_cancelled({**payload, key: value}, ctx)
    assert await erp_projection_state(session) == before


async def test_erp_projection_replay_keeps_original_fx(api, session, monkeypatch):
    from modules.finance import document_versions as projection

    _, payload, ctx = await erp_original(api, session, currency="USD")
    await projection.on_invoice_issued(payload, ctx)
    payment = (await session.scalars(select(Payment))).one()
    assert (payment.amount, payment.amount_orig, payment.currency) == (Decimal("720"), Decimal("240"), "USD")
    before = await erp_projection_state(session)

    async def unavailable_fx(*args, **kwargs):
        raise AssertionError("Replay must verify saved binding without querying a new FX rate")

    monkeypatch.setattr(projection, "event_amount", unavailable_fx)
    await projection.on_invoice_issued(payload, ctx)
    assert await erp_projection_state(session) == before


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
    [pytest.param('10', 'superseded', False, id='partial'),
     pytest.param('190', 'superseded', False, id='fully-received-retired'),
     pytest.param('10', 'paid', True, id='historical-paid')],
)
async def test_replacement_retires_old_demand_and_preserves_allocated_cash(
    api, session, finance_org, late_amount, expected_status, manual_paid,
):
    _, old, *_ = await make_invoice(api, session)
    bus = OutboxEventBus()
    ctx = SimpleNamespace(session=session, services=SimpleNamespace(event_bus=bus))
    original_event = (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == 'sales.document.posted'))).one()
    # Explicit historical owned input, never ownership assigned to a legacy
    # projection after its creation. The legacy consumer only replays this row.
    historical_paid_at = datetime(2026, 9, 1, 8) if manual_paid else None
    old_payment = Payment(organization_id=finance_org, ref=old['number'],
        entity_ref=f"document:{old['id']}", deal_id=original_event.payload['deal_id'],
        amount=Decimal('240'), kind='receivable', status='paid' if manual_paid else 'pending',
        paid_at=historical_paid_at)
    session.add(old_payment)
    await session.flush()
    await on_original_issued(original_event.payload, ctx)
    first = await apply_allocation(session, bus, old_payment, Decimal('50'))
    first_allocation_id = first.id
    assert old_payment.status == ('paid' if manual_paid else 'partial')
    await session.commit()
    revision = await api.post(f"/sales/documents/{old['id']}/revision", json={
        'reason': 'Replacement', 'request_key': 'finance-revision'})
    assert revision.status_code == 201, revision.text
    new = revision.json()
    replacement_event = {**original_event.payload, 'replacement_document_id': new['id']}
    await on_original_superseded(replacement_event, ctx)
    await session.flush()
    await on_original_superseded(replacement_event, ctx)
    new_event = {**original_event.payload, 'document_id': new['id'],
        'number': new['number'], 'document_version': new['version'],
        'amount': '360.00', 'content_sha256': 'b' * 64}
    replacement = Payment(organization_id=finance_org, ref=new['number'],
        entity_ref=f"document:{new['id']}", deal_id=original_event.payload['deal_id'],
        amount=Decimal('360'), kind='receivable')
    session.add(replacement)
    await session.flush()
    await on_original_issued(new_event, ctx)
    await session.commit()
    payments = (await session.scalars(select(Payment).order_by(Payment.id))).all()
    assert payments == [old_payment, replacement]
    assert [p.amount for p in payments] == [Decimal('240'), Decimal('360')]
    assert old_payment.status == ('paid' if manual_paid else 'superseded')
    assert replacement.status == 'pending' and replacement.paid_at is None
    assert old_payment.paid_at == historical_paid_at
    allocations = (await session.scalars(select(PaymentAllocation))).all()
    assert [(a.payment_id, a.amount) for a in allocations] == [(old_payment.id, Decimal('50'))]
    outstanding = await _payments_outstanding(session, ('receivable',), organization_id=finance_org)
    assert [(p.id, amount) for p, amount in outstanding] == [(replacement.id, Decimal('360'))]

    # The real API refuses manual source status and new cash on a retired invoice.
    # Confirmed historical receipt delivery uses its existing internal consumer.
    headers, params = dict(api.headers), api.params
    before_http = await erp_projection_state(session)
    try:
        api.headers.update({'X-User': 'yi-finance', 'X-User-Roles': 'accountant'})
        api.params = {'organization_id': finance_org}
        receipt_url = f'/finance/payments/{old_payment.id}/allocations'
        marked = await api.patch(f'/finance/payments/{old_payment.id}', json={'status': 'paid'})
        assert marked.status_code == 409, marked.text
        if not manual_paid:
            refused = await api.post(receipt_url, json={'amount': late_amount})
            assert refused.status_code == 409, refused.text
    finally:
        api.headers.clear()
        api.headers.update(headers)
        api.params = params
    assert await erp_projection_state(session) == before_http

    await apply_allocation(session, bus, old_payment, Decimal(late_amount))
    await session.commit()
    assert old_payment.status == expected_status
    assert old_payment.paid_at == historical_paid_at
    assert old_payment.entity_ref == f"document:{old['id']}"
    assert replacement.entity_ref == f"document:{new['id']}"
    assert replacement.status == 'pending' and replacement.paid_at is None
    allocations = (await session.scalars(select(PaymentAllocation).order_by(PaymentAllocation.id))).all()
    assert [(a.payment_id, a.amount) for a in allocations] == [
        (old_payment.id, Decimal('50')), (old_payment.id, Decimal(late_amount))]
    assert allocations[0].id == first_allocation_id
    received = (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == 'finance.payment.received').order_by(OutboxEvent.id))).all()
    assert [Decimal(e.payload['amount']) for e in received] == [Decimal('50'), Decimal(late_amount)]
    assert Decimal(received[-1].payload['outstanding']) == Decimal('190') - Decimal(late_amount)
    assert all(e.payload['ref'] == old['number'] for e in received)
    assert all(e.payload['entity_ref'] == f'payment:{old_payment.id}' for e in received)
    if manual_paid or late_amount == '190':
        following_amount = '180' if manual_paid else '1'
        await apply_allocation(session, bus, old_payment, Decimal(following_amount))
        await session.commit()
        final_allocations = (await session.scalars(select(PaymentAllocation).order_by(PaymentAllocation.id))).all()
        assert [a.id for a in final_allocations[:2]] == [a.id for a in allocations]
        assert [(a.payment_id, a.amount) for a in final_allocations] == [
            (old_payment.id, Decimal('50')), (old_payment.id, Decimal(late_amount)),
            (old_payment.id, Decimal(following_amount))]
        assert old_payment.status == expected_status and old_payment.paid_at == historical_paid_at
    outstanding = await _payments_outstanding(session, ('receivable',), organization_id=finance_org)
    assert [(p.id, amount) for p, amount in outstanding] == [(replacement.id, Decimal('360'))]
    paid = (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == 'finance.payment.paid'))).all()
    assert paid == []  # Retired demand cannot revive; historical paid never emits a second event.
    await on_original_issued(original_event.payload, ctx)
    await on_original_superseded(replacement_event, ctx)
    assert old_payment.status == expected_status and old_payment.paid_at == historical_paid_at


@pytest.mark.parametrize('concurrent_status', ['superseded', 'paid'])
async def test_late_allocation_refreshes_status_from_another_transaction(session, finance_org, concurrent_status):
    old = Payment(organization_id=finance_org, ref='OLD', entity_ref='document:1', amount=Decimal('240'), kind='receivable')
    replacement = Payment(organization_id=finance_org, ref='NEW', entity_ref='document:2', amount=Decimal('360'), kind='receivable')
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
    outstanding = await _payments_outstanding(session, ('receivable',), organization_id=finance_org)
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
async def test_supersede_preserves_payment_settled_by_another_transaction(session, finance_org, entity_ref):
    old = Payment(organization_id=finance_org, ref='OLD', entity_ref=entity_ref, amount=Decimal('240'), kind='receivable')
    replacement = Payment(organization_id=finance_org, ref='NEW', entity_ref='document:2', amount=Decimal('360'), kind='receivable')
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
    outstanding = await _payments_outstanding(session, ('receivable',), organization_id=finance_org)
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
