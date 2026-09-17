from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.sales import events


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self


class Session:
    def __init__(self, *results, objects=None):
        self.results = list(results)
        self.objects = objects or {}
        self.added = []
        self._next_id = 50

    async def execute(self, _statement):
        return self.results.pop(0)

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = self._next_id
                self._next_id += 1


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def context(session, *, bus=None, llm=None, facade=None):
    return SimpleNamespace(
        session=session,
        services=SimpleNamespace(event_bus=bus or Bus(), llm=llm, landed_cost=facade),
    )


@pytest.mark.asyncio
async def test_lead_conversion_payment_paid_and_delivery(monkeypatch):
    bus = Bus()
    session = Session()
    await events.on_lead_converted({"lead_id": 4, "title": "Need", "counterparty": "ACME"}, context(session, bus=bus))
    assert session.added[-1].number == "CRM-LEAD-4"
    assert bus.calls[-1][1] == "sales.deal.created"
    await events.on_lead_converted({}, context(session, bus=bus))

    doc = SimpleNamespace(status="issued", reserve_status="reserved")
    session = Session(Result([doc]))
    await events.on_payment_paid({"ref": "INV-1"}, context(session))
    assert (doc.status, doc.reserve_status) == ("paid", "consumed")
    await events.on_payment_paid({}, context(session))

    deal = SimpleNamespace(stage="new", closed_date=None)
    session = Session(objects={})
    # repository is imported inside the handler, therefore patch its public function.
    monkeypatch.setattr("modules.sales.repository.record_stage", lambda *_args, **_kwargs: None)
    from modules.sales.models import Deal
    session.objects[(Deal, 9)] = deal
    await events.on_shipment_delivered({"deal_id": 9}, context(session))
    assert deal.closed_date is not None
    await events.on_shipment_delivered({}, context(session))


@pytest.mark.asyncio
async def test_handoff_is_idempotent_and_contains_items():
    from modules.sales.models import Deal

    deal = SimpleNamespace(
        id=7, number="D-7", counterparty="ACME", amount="100", owner="Ivan", funnel="main"
    )
    items = [SimpleNamespace(sku_id=1, qty="2")]
    skus = [SimpleNamespace(id=1, code="S-1", title="Battery")]
    bus = Bus()
    session = Session(Result([]), Result(items), Result(skus), objects={(Deal, 7): deal})
    await events.on_deal_won_handoff({"deal_id": 7, "number": "D-7"}, context(session, bus=bus))
    payload = bus.calls[-1][2]
    assert payload["items"] == [{"sku_code": "S-1", "title": "Battery", "qty": 2.0}]
    assert payload["gross_profit"] is None

    existing = SimpleNamespace(payload={"deal_id": 7})
    session = Session(Result([existing]))
    await events.on_deal_won_handoff({"deal_id": 7}, context(session, bus=bus))
    assert len(bus.calls) == 1
    await events.on_deal_won_handoff({}, context(session, bus=bus))


@pytest.mark.asyncio
async def test_ai_supply_and_plan_handlers_emit_only_valid_actions():
    llm = SimpleNamespace(enabled=True, complete=AsyncMock(return_value="draft"))
    bus = Bus()
    context_obj = context(Session(), bus=bus, llm=llm)
    await events.on_incoming_message_ai({"direction": "in", "deal_id": 3}, context_obj)
    assert bus.calls[-1][1] == "ai.draft.suggested"
    await events.on_incoming_message_ai({"direction": "out", "deal_id": 3}, context_obj)

    sku = SimpleNamespace(id=10, code="S-1")
    active = SimpleNamespace(id=4, stage="new")
    session = Session(Result([sku]), Result([4]), Result([active]))
    bus = Bus()
    await events.on_procurement_received(
        {"sku_code": "S-1", "qty": 2, "warehouse": "Main"}, context(session, bus=bus)
    )
    assert bus.calls[-1][1] == "sales.supply.arrived"
    await events.on_procurement_received({}, context(session, bus=bus))

    target = SimpleNamespace(target=0)
    session = Session(Result([target]))
    await events.on_plan_approved({"metric": "won_sum", "target": "220", "period_type": "month"}, context(session))
    assert target.target == 10
    await events.on_plan_approved({"metric": "won_sum", "target": "nan"}, context(session))
    await events.on_plan_approved({"metric": "missing", "target": 1}, context(Session(Result([]))))
