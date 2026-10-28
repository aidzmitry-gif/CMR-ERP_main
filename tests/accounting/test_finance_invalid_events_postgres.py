"""Synthetic PostgreSQL acceptance for malformed legacy Finance events."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent
from core.services.eventbus import OutboxEventBus
from modules.finance.events import on_document_posted, on_landed_cost
from modules.finance.models import Payment
from tests.accounting.test_postgres import pg_factory as _pg_factory_fixture
from tests.test_finance import _ctx

pytestmark = pytest.mark.integration
pg_factory = _pg_factory_fixture


async def test_invalid_finance_events_do_not_commit_or_mark_delivery(pg_factory):
    async with pg_factory() as session:
        bus = OutboxEventBus()
        bus.subscribe("synthetic.invoice.posted", on_document_posted)
        bus.emit(session, "synthetic.invoice.posted", {"kind": "invoice", "number": "BAD", "amount": "invalid"})
        bus.emit(session, "synthetic.invoice.posted", {"kind": "invoice", "number": "GOOD", "amount": "10.00"})
        await session.commit()
        with pytest.raises(ValueError, match="amount"):
            await bus.relay_once(session, _ctx(session))
        await session.rollback()
        events = (await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id))).all()
        assert len(events) == 2 and all(event.processed_at is None for event in events)
        assert (await session.scalars(select(Payment))).all() == []

        with pytest.raises(ValueError, match="amount"):
            await on_landed_cost({"amount": "invalid", "total_landed_byn": "100.00"}, _ctx(session))
        await session.rollback()
        assert (await session.scalars(select(Payment))).all() == []

        await on_document_posted({"kind": "invoice", "number": "ZERO", "amount": "0.00"}, _ctx(session))
        await on_landed_cost({"total_landed_byn": "100.00"}, _ctx(session))
        await session.commit()
        payments = (await session.scalars(select(Payment).order_by(Payment.id))).all()
        assert [(payment.ref, payment.amount) for payment in payments] == [
            ("ZERO", Decimal("0.00")), ("landed:", Decimal("100.00"))
        ]
