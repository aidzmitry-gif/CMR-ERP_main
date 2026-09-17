from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.finance import events


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)


class FakeBus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((event_type, payload))


def _ctx():
    session = FakeSession()
    bus = FakeBus()
    return SimpleNamespace(session=session, services=SimpleNamespace(event_bus=bus)), session, bus


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), ("", None), (date(2026, 9, 17), date(2026, 9, 17)), ("2026-09-17", date(2026, 9, 17)), ("bad", None)],
)
def test_finance_date_and_decimal_parsers_are_fail_soft(raw, expected):
    assert events._parse_due_date(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "bad", object()])
def test_finance_decimal_parser_returns_zero_for_empty_or_malformed_values(raw):
    assert events._to_decimal(raw) == Decimal("0")
    assert events._to_decimal("12.340") == Decimal("12.340")


@pytest.mark.asyncio
async def test_document_posted_creates_receivable_and_emits_string_amount():
    ctx, session, bus = _ctx()
    await events.on_document_posted(
        {
            "kind": "invoice",
            "number": "INV-1",
            "amount": "123.45",
            "due_date": "2026-09-30",
            "deal_id": 7,
            "counterparty_ref": "unp:1",
            "entity_ref": "invoice:1",
        },
        ctx,
    )
    payment = session.added[0]
    assert payment.ref == "INV-1"
    assert payment.amount == Decimal("123.45")
    assert payment.due_date == date(2026, 9, 30)
    assert bus.events == [("finance.payment.created", {"ref": "INV-1", "amount": "123.45", "deal_id": 7, "entity_ref": "invoice:1"})]

    await events.on_document_posted({"kind": "order", "amount": "100"}, ctx)
    await events.on_document_posted({"kind": "invoice", "amount": "100"}, None)
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_freight_cost_handles_zero_unknown_currency_and_fx():
    ctx, session, _ = _ctx()
    await events.on_freight_cost({"amount": "0", "ref": "S-0"}, ctx)
    await events.on_freight_cost({"amount": "10", "currency": "ZZZ", "ref": "S-X"}, ctx)
    await events.on_freight_cost({"amount": "10", "currency": "USD", "ref": "S-1", "deal_id": 3}, ctx)
    payment = session.added[0]
    assert payment.ref == "freight:S-1"
    assert payment.kind == "freight"
    assert payment.amount == Decimal("36.30")
    assert payment.amount_orig == Decimal("10")
    assert payment.currency == "USD"
    assert payment.deal_id == 3


@pytest.mark.asyncio
async def test_freight_refund_is_negative_and_landed_cost_uses_fallbacks():
    ctx, session, _ = _ctx()
    await events.on_freight_refund({"amount": "20", "entity_ref": "ship:1"}, ctx)
    await events.on_landed_cost(
        {"unit_landed_cost_byn": "12.5", "qty": "4", "sku_code": "SKU-1"}, ctx
    )
    refund, landed = session.added
    assert refund.amount == Decimal("-20")
    assert refund.kind == "freight_refund"
    assert refund.ref == "freight_refund:ship:1"
    assert landed.amount == Decimal("50.0")
    assert landed.kind == "landed"
    assert landed.ref == "landed:SKU-1"


@pytest.mark.asyncio
async def test_claim_po_and_payroll_handlers_ignore_non_actionable_events():
    ctx, session, _ = _ctx()
    await events.on_claim_resolved({"status": "rejected", "amount_byn": "10"}, ctx)
    await events.on_claim_resolved({"status": "resolved", "amount_byn": "10", "supplier_id": 5, "claim_id": 8}, ctx)
    await events.on_po_drafted({"planned_amount": "0"}, ctx)
    await events.on_po_drafted({"planned_amount": "100", "po_ref": "PO-1", "eta_date": "2026-10-01", "supplier_id": 9}, ctx)
    await events.on_payroll_accrued({"amount_byn": "0"}, ctx)
    await events.on_payroll_accrued({"amount_byn": "200", "entity_ref": "payroll:1", "employee_name": "Иван", "period": "2026-09"}, ctx)
    assert len(session.added) == 3
    claim, po, payroll = session.added
    assert (claim.kind, claim.amount, claim.counterparty_ref) == ("claim_refund", Decimal("10"), "5")
    assert (po.kind, po.status, po.due_date) == ("po_planned", "planned", date(2026, 10, 1))
    assert (payroll.kind, payroll.description, payroll.entity_ref) == ("payroll", "ФОТ Иван 2026-09", "payroll:1")
