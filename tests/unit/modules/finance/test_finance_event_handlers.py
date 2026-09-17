from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.finance import events


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar = scalar

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.scalar


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []

    async def execute(self, _statement):
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def ctx(*results, facade=None):
    session = Session(*results)
    bus = Bus()
    services = SimpleNamespace(event_bus=bus, sku_master=facade)
    return SimpleNamespace(session=session, services=services), session, bus


@pytest.mark.asyncio
async def test_finance_document_and_cost_handlers_create_expected_payments():
    context, session, bus = ctx()
    await events.on_document_posted(
        {"kind": "invoice", "number": "INV-1", "amount": "12.50", "due_date": "2026-09-20", "deal_id": 4}, context
    )
    assert session.added[0].amount == Decimal("12.50")
    assert session.added[0].due_date.isoformat() == "2026-09-20"
    assert bus.calls[0][1] == "finance.payment.created"
    assert bus.calls[0][2]["amount"] == "12.50"

    await events.on_freight_cost({"amount": "10", "currency": "USD", "ref": "SHIP-1", "deal_id": 4}, context)
    assert session.added[-1].kind == "freight"
    assert session.added[-1].amount == Decimal("36.30")
    await events.on_freight_cost({"amount": "0"}, context)
    await events.on_freight_cost({"amount": "10", "currency": "XXX"}, context)
    await events.on_freight_refund({"amount": "5", "currency": "BYN", "shipment_code": "S-1"}, context)
    assert session.added[-1].kind == "freight_refund"
    assert session.added[-1].amount == Decimal("-5")

    await events.on_landed_cost({"unit_landed_cost_byn": "4", "qty": "3", "sku_code": "S-1"}, context)
    assert session.added[-1].kind == "landed"
    await events.on_claim_resolved({"status": "resolved", "amount_byn": "8", "supplier_id": 9}, context)
    assert session.added[-1].kind == "claim_refund"
    await events.on_claim_resolved({"status": "rejected", "amount_byn": "8"}, context)
    await events.on_po_drafted({"planned_amount": "12", "po_ref": "PO-1", "eta_date": "2026-10-01", "supplier_id": 5}, context)
    assert session.added[-1].kind == "po_planned"
    await events.on_payroll_accrued({"amount_byn": "100", "entity_ref": "payroll:1", "employee_name": "A", "period": "2026-09"}, context)
    assert session.added[-1].kind == "payroll"


@pytest.mark.asyncio
async def test_payroll_and_revenue_handlers_are_idempotent():
    payroll = SimpleNamespace(status="pending")
    context, session, _ = ctx(Result(scalar=payroll))
    await events.on_payroll_paid({"entity_ref": "payroll:1"}, context)
    assert payroll.status == "paid"

    context, session, _ = ctx(Result(scalar=None))
    await events.on_payroll_paid({"entity_ref": "missing"}, context)
    await events.on_payroll_paid({}, context)

    context, session, _ = ctx(Result(scalar=None))
    await events.on_deal_handoff({"deal_id": 7, "amount": "100", "number": "INV-7"}, context)
    assert session.added[-1].kind == "revenue_recognized"
    assert session.added[-1].entity_ref == "deal:7"

    existing = SimpleNamespace()
    context, session, _ = ctx(Result(scalar=existing))
    await events.on_deal_handoff({"deal_id": 7, "amount": "100"}, context)
    assert session.added == []
    await events.on_deal_handoff({"deal_id": None, "amount": "100"}, context)
    await events.on_deal_handoff({"deal_id": 7, "amount": "0"}, context)


@pytest.mark.asyncio
async def test_reference_change_emits_one_sorted_recompute_signal():
    context, session, bus = ctx()
    await events.on_reference_changed(
        {"ref_key": "core.currency_rates", "entity_ref": "currency_rates:USD", "actor": "a"}, context
    )
    assert bus.calls[-1][1] == "finance.fx.recompute_requested"
    assert bus.calls[-1][2]["currency_code"] == "USD"

    facade = SimpleNamespace(landed_inputs_batch=AsyncMock(return_value={"S-1": {"duty_pct": 5}}))
    context, session, bus = ctx(facade=facade)
    await events.on_reference_changed({"ref_key": "core.skus", "entity_ref": "sku:S-1", "actor": "a"}, context)
    assert bus.calls[-1][1] == "finance.landed.recompute_requested"
    assert bus.calls[-1][2]["sku_codes"] == ["S-1"]

    context, session, bus = ctx(Result(rows=[("S-2",), ("S-1",)]), facade=facade)
    await events.on_reference_changed({"ref_key": "core.tnved", "entity_ref": "tnved:8507"}, context)
    assert bus.calls[-1][2]["sku_codes"] == ["S-1", "S-2"]
    await events.on_reference_changed({"ref_key": "unknown", "entity_ref": "x:1"}, context)
    assert len(bus.calls) == 1

    context, session, bus = ctx(facade=SimpleNamespace(landed_inputs_batch=AsyncMock(side_effect=RuntimeError("offline"))))
    await events.on_reference_changed({"ref_key": "core.skus", "entity_ref": "sku:S-1"}, context)
    assert bus.calls[-1][2]["inputs"] == {}


def test_finance_event_parsers_are_honest_empty():
    assert events._parse_due_date(None) is None
    assert events._parse_due_date("bad") is None
    assert events._parse_due_date("2026-09-17").isoformat() == "2026-09-17"
    assert events._to_decimal(None) == Decimal("0")
    assert events._to_decimal("bad") == Decimal("0")
