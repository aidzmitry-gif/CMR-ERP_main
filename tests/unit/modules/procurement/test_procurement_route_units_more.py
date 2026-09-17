from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from modules.procurement import routes
from modules.procurement.models import (
    LandedCost,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderMilestone,
    Rfq,
    RfqBid,
    ShipRequirement,
    Supplier,
    SupplierClaim,
    TransportMethod,
)
from modules.procurement.schemas import (
    OrderPlanIn,
    PurchaseOrderCreate,
    PurchaseOrderHeaderUpdate,
    PurchaseOrderLineIn,
    PurchaseOrderStatusUpdate,
    RfqAward,
    RfqBidIn,
    RfqCreate,
    SupplierClaimCreate,
    SupplierClaimUpdate,
    SupplierCreate,
    SupplierUpdate,
    TransportMethodUpdate,
)


class Scalars:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar_value = scalar

    def scalars(self):
        return Scalars(self.rows)

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar_value

    def scalar_one_or_none(self):
        return self.scalar_value


class Session:
    def __init__(self, *results, by_id=None):
        self.results = list(results)
        self.by_id = by_id or {}
        self.added = []
        self.deleted = []
        self.commits = 0
        self.flushes = 0
        self.refreshed = []
        self._next_id = 1

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()

    async def get(self, _model, identity):
        return self.by_id.get(identity)

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = self._next_id
            self._next_id += 1
        if isinstance(value, Rfq) and value.status is None:
            value.status = "open"
        if isinstance(value, Supplier) and value.status is None:
            value.status = "active"
        self.added.append(value)

    async def delete(self, value):
        self.deleted.append(value)

    async def flush(self):
        self.flushes += 1
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = self._next_id
                self._next_id += 1

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        self.refreshed.append(value)

    def begin_nested(self):
        return _Nested()


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((session, event_type, payload))


def _core(bus=None):
    return SimpleNamespace(event_bus=bus or Bus())


def _order(*, order_id=7, status="ordered", freight="20", eta=date(2026, 10, 1)):
    return PurchaseOrder(
        id=order_id,
        number=f"PO-{order_id}",
        supplier="ACME",
        supplier_id=11,
        status=status,
        eta_date=eta,
        freight_byn=Decimal(freight),
    )


def _line(line_id=9, order_id=7, sku="SKU-1", qty="2", goods="100", weight="4"):
    return PurchaseOrderLine(
        id=line_id,
        order_id=order_id,
        sku_code=sku,
        qty=Decimal(qty),
        goods_value_byn=Decimal(goods),
        weight=Decimal(weight),
        volume=Decimal("0.2"),
    )


@pytest.mark.asyncio
async def test_on_time_and_board_scores_use_batched_rows_and_ignore_rejected_claims():
    assert routes._score_components(2, 1, 0.5)["score"] == 5.0
    assert routes._score_components(0, 0, None)["components"]["quality"] is None
    received = datetime(2026, 9, 10, 12, 0)
    session = Session(Result([(11, received, date(2026, 9, 10)), (11, received, date(2026, 9, 9))]))
    assert await routes._on_time_rates(session, {11, 22}) == {11: 0.5}

    session = Session(
        Result([(11, 2), (22, 1)]),
        Result([(11, 1), (22, 4)]),
        Result([(11, received, date(2026, 9, 10))]),
    )
    scores = await routes._board_scores(session, {11, 22})
    assert scores[11] == 7.0
    assert scores[22] == 0.0
    assert await routes._board_scores(Session(), set()) == {}


@pytest.mark.asyncio
async def test_orders_out_and_editing_handlers_keep_line_shape_and_terminal_guard():
    order = _order()
    line = _line()
    out = await routes._orders_out(Session(Result([line])), [order])
    assert out[0].model_dump()["lines"][0]["sku_code"] == "SKU-1"
    assert out[0].freight_byn == 20.0

    editable = _order(status="draft")
    session = Session(Result([line]), by_id={7: editable})
    added = await routes.add_order_line(7, PurchaseOrderLineIn(sku_code="SKU-2", qty=3), session)
    assert session.added[-1].sku_code == "SKU-2"
    assert added.id == 7

    session = Session(Result([]), by_id={7: editable, 9: line})
    await routes.delete_order_line(7, 9, session)
    assert session.deleted == [line]

    session = Session(Result([line]), by_id={7: editable})
    updated = await routes.update_order_header(
        7,
        PurchaseOrderHeaderUpdate(supplier="New supplier", freight_byn=35.5),
        session,
    )
    assert updated.id == 7
    assert (editable.supplier, editable.freight_byn) == ("New supplier", Decimal("35.5"))

    with pytest.raises(HTTPException) as closed:
        await routes._require_editable_order(Session(by_id={7: _order(status="received")}), 7)
    assert closed.value.status_code == 409


@pytest.mark.asyncio
async def test_create_order_and_status_received_fixate_cost_and_emit_events(monkeypatch):
    bus = Bus()
    fixed = AsyncMock()
    arrival = AsyncMock()
    monkeypatch.setattr(routes, "_fixate_landed_cost", fixed)
    monkeypatch.setattr(routes, "_mark_arrival_fact", arrival)

    session = Session(Result([_line(order_id=1)]))
    created = await routes.create_order(
        PurchaseOrderCreate(
            supplier="ACME",
            supplier_id=11,
            status="draft",
            freight_byn=12.5,
            lines=[PurchaseOrderLineIn(sku_code="SKU-1", qty=2)],
        ),
        _core(bus),
        session,
    )
    assert created.number == "PO-2026-0001"
    assert session.added[0].status == "draft"

    session = Session(Result([_line(order_id=8)]))
    await routes.create_order(
        PurchaseOrderCreate(supplier="ACME", status="received", lines=[]),
        _core(bus),
        session,
    )
    assert fixed.await_count == 1
    assert arrival.await_count == 1

    transition_order = _order(order_id=9, status="ordered")
    session = Session(Result([_line(order_id=9)]), by_id={9: transition_order})
    await routes.update_order_status(
        9,
        PurchaseOrderStatusUpdate(status="received"),
        _core(bus),
        session,
    )
    assert transition_order.received_at is not None
    assert any(event[1] == "procurement.order.status_changed" for event in bus.events)


@pytest.mark.asyncio
async def test_order_route_missing_and_invalid_status_errors_are_explicit():
    with pytest.raises(HTTPException) as missing:
        await routes.get_order(404, Session())
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as cancelled:
        await routes.create_order(PurchaseOrderCreate(status="cancelled"), _core(), Session())
    assert cancelled.value.status_code == 422

    with pytest.raises(HTTPException) as missing_update:
        await routes.update_order_status(404, PurchaseOrderStatusUpdate(status="ordered"), _core(), Session())
    assert missing_update.value.status_code == 404


@pytest.mark.asyncio
async def test_landed_preview_and_estimated_cost_apply_duty_without_fixing_actual_cost(monkeypatch):
    order = _order(order_id=7, status="ordered", freight="20")
    line = _line(order_id=7, goods="100", weight="4")
    monkeypatch.setattr(
        "core.services.sku_master.landed_inputs_batch",
        AsyncMock(return_value={"SKU-1": {"duty_pct": 10}}),
    )
    preview = await routes.landed_preview(7, Session(Result([line]), by_id={7: order}))
    assert preview["lines"][0]["unit_landed_cost_byn"] == 66.0
    assert preview["total_landed_byn"] == 132.0

    open_order = _order(order_id=8, freight="10")
    estimate_line = _line(order_id=8, goods="100", weight="2")
    monkeypatch.setattr(
        "core.services.sku_master.landed_inputs",
        AsyncMock(return_value={"duty_pct": 20}),
    )
    session = Session(Result([open_order]), Result([estimate_line]), Result([]))
    unit = await routes._recompute_estimated_landed(session, "SKU-1")
    assert unit == Decimal("66.0000")
    assert isinstance(session.added[0], LandedCost)
    assert session.added[0].stage == "estimated"


@pytest.mark.asyncio
async def test_fixate_landed_cost_upserts_actual_rows_and_emits_cost_and_receipt_events(monkeypatch):
    order = _order(order_id=14, status="received", freight="20")
    order.received_at = datetime(2026, 9, 18, 10, 0)
    lines = [_line(order_id=14, sku="A", qty="2", goods="100", weight="2"), _line(10, 14, "B", "1", "50", "0"), _line(11, 14, "", "0", "10", "1")]
    existing = LandedCost(
        id=30,
        sku_code="A",
        purchase_order_id=14,
        shipment_id="old",
        unit_landed_cost_byn=Decimal("1"),
        stage="estimated",
    )
    monkeypatch.setattr(
        "core.services.sku_master.landed_inputs_batch",
        AsyncMock(return_value={"A": {"duty_pct": 10}, "B": None}),
    )
    bus = Bus()
    session = Session(Result(lines), Result([existing]))
    await routes._fixate_landed_cost(session, order, bus)

    assert existing.stage == "actual"
    assert existing.shipment_id == "PO-14"
    assert any(isinstance(value, LandedCost) and value.sku_code == "B" for value in session.added)
    cost_events = [event for event in bus.events if event[1] == "procurement.landed_cost.calculated"]
    receipt_events = [event for event in bus.events if event[1] == "procurement.received"]
    assert [event[2]["sku_code"] for event in cost_events] == ["A", "B"]
    assert [event[2]["sku_code"] for event in receipt_events] == ["A", "B"]

    empty = Session(Result([]))
    await routes._fixate_landed_cost(empty, order, bus)
    assert empty.added == []


@pytest.mark.asyncio
async def test_supplier_crud_and_scorecard_preserve_empty_and_quality_semantics():
    supplier = Supplier(id=4, name="ACME", unp="123", status="active")
    assert (await routes.list_suppliers(Session(Result([supplier]))))[0] is supplier

    created_session = Session()
    created = await routes.create_supplier(SupplierCreate(name="New", unp="456"), created_session)
    assert created.name == "New" and created_session.commits == 1

    with pytest.raises(HTTPException) as missing:
        await routes.get_supplier(999, Session())
    assert missing.value.status_code == 404

    updated_session = Session(by_id={4: supplier})
    updated = await routes.update_supplier(4, SupplierUpdate(name="ACME 2", status="blocked"), updated_session)
    assert updated is supplier and (supplier.name, supplier.status) == ("ACME 2", "blocked")

    received = datetime(2026, 9, 10, 8, 0)
    score_session = Session(
        Result(scalar=3),
        Result([("open", 1), ("resolved", 2), ("rejected", 1)]),
        Result(scalar=Decimal("12.5")),
        Result([(4, received, date(2026, 9, 10))]),
        by_id={4: supplier},
    )
    score = await routes.supplier_scorecard(4, score_session)
    assert score["orders_count"] == 3
    assert score["claims_open"] == 1
    assert score["claims_closed"] == 3
    assert score["on_time_rate"] == 1.0
    assert score["avg_won_price_byn"] == 12.5


@pytest.mark.asyncio
async def test_rfq_lifecycle_sorts_bids_awards_winner_and_creates_draft_order():
    created = await routes.create_rfq(RfqCreate(item="Battery", sku_code="BAT", qty=2), Session())
    assert created.qty == 2.0

    rfq = Rfq(id=5, item="Battery", sku_code="BAT", qty=Decimal("2"), status="open")
    old_bid = RfqBid(
        id=2,
        rfq_id=5,
        supplier_id=20,
        price_byn=Decimal("120"),
        incoterms="FOB",
        note="old",
        is_winner=False,
    )
    new_bid = RfqBid(
        id=1,
        rfq_id=5,
        supplier_id=21,
        price_byn=Decimal("100"),
        incoterms="",
        note="",
        is_winner=False,
    )
    bid_session = Session(Result([old_bid, new_bid]), by_id={5: rfq})
    bid_out = await routes.add_rfq_bid(5, RfqBidIn(supplier_id=21, price_byn=100), bid_session)
    assert bid_out.best_bid_id == 1
    assert bid_session.added[-1].price_byn == Decimal("100")

    winner = RfqBid(
        id=1,
        rfq_id=5,
        supplier_id=21,
        price_byn=Decimal("100"),
        incoterms="FOB",
        note="winner",
        is_winner=False,
    )
    loser = RfqBid(
        id=2,
        rfq_id=5,
        supplier_id=20,
        price_byn=Decimal("120"),
        incoterms="CIF",
        note="loser",
        is_winner=False,
    )
    bus = Bus()
    award_session = Session(Result([winner, loser]), Result([winner, loser]), by_id={5: rfq})
    awarded = await routes.award_rfq(5, RfqAward(bid_id=1), _core(bus), award_session)
    assert (rfq.status, winner.is_winner, loser.is_winner) == ("awarded", True, False)
    assert awarded.created_order_id is not None
    assert [event[1] for event in bus.events] == ["procurement.rfq.awarded", "procurement.po.drafted"]
    draft = next(value for value in award_session.added if isinstance(value, PurchaseOrder))
    draft_line = next(value for value in award_session.added if isinstance(value, PurchaseOrderLine))
    assert (draft.status, draft.supplier_id, draft_line.goods_value_byn) == ("draft", 21, Decimal("200.00"))

    with pytest.raises(HTTPException) as closed:
        await routes.add_rfq_bid(5, RfqBidIn(price_byn=90), Session(by_id={5: SimpleNamespace(status="awarded")}))
    assert closed.value.status_code == 409


@pytest.mark.asyncio
async def test_claims_resolve_once_and_publish_order_reference():
    create_session = Session()
    claim = await routes.create_claim(
        SupplierClaimCreate(supplier="ACME", item="Battery", amount_byn=12.5), create_session
    )
    assert claim.status == "open" and claim.source == "manual"

    obj = SupplierClaim(id=8, supplier="ACME", order_code="PO-8", status="open", amount_byn=Decimal("12.5"))
    bus = Bus()
    session = Session(Result(scalar=44), by_id={8: obj})
    updated = await routes.update_claim(
        8,
        SupplierClaimUpdate(status="resolved", resolution="refund"),
        _core(bus),
        session,
    )
    assert updated.status == "resolved"
    assert bus.events[0][2]["order_id"] == 44

    already_closed = SupplierClaim(id=9, status="resolved")
    bus = Bus()
    await routes.update_claim(9, SupplierClaimUpdate(resolution="done"), _core(bus), Session(by_id={9: already_closed}))
    assert bus.events == []

    with pytest.raises(HTTPException) as missing:
        await routes.update_claim(404, SupplierClaimUpdate(status="rejected"), _core(), Session())
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_transport_defaults_update_and_arrival_fact_are_idempotent():
    session = Session(Result(["container", "truck"]))
    await routes._ensure_default_methods(session)
    assert session.added == []

    session = Session(Result([]))
    await routes._ensure_default_methods(session)
    assert {item.code for item in session.added} == set(routes.DEFAULT_METHODS)

    method = TransportMethod(id=1, code="truck", name="Машина", durations={"collection": 20}, active=True)
    listed = await routes.list_transport_methods(
        Session(Result(["container", "truck"]), Result([method]))
    )
    assert listed[0].total_days == 20

    method_session = Session(Result(["container", "truck"]), Result([method]))
    changed = await routes.update_transport_method(
        "truck", TransportMethodUpdate(name="Авто", durations={"payment": 5}, active=False), method_session
    )
    assert (changed.name, changed.durations, changed.active) == (
        "Авто",
        {"collection": 20, "payment": 5},
        False,
    )

    milestone = PurchaseOrderMilestone(id=1, order_id=7, stage="customs", seq=5, duration_days=2, actual_date=None)
    await routes._mark_arrival_fact(Session(Result([milestone])), 7, date(2026, 9, 20))
    assert milestone.actual_date == date(2026, 9, 20)
    await routes._mark_arrival_fact(Session(Result([SimpleNamespace(actual_date=date(2026, 9, 20))])), 7, date(2026, 9, 21))


@pytest.mark.asyncio
async def test_order_plan_reads_requirements_and_rejects_missing_target(monkeypatch):
    order = _order(order_id=12, status="draft")
    requirement = ShipRequirement(
        id=1,
        deal_id=3,
        number="D-3",
        counterparty="ACME",
        sku_code="SKU-PLAN",
        ship_deadline="25.09.2026",
        ship_deadline_date=date(2026, 9, 25),
        penalty_rate_pct=Decimal("0.5"),
        penalty_cap_pct=Decimal("10"),
        penalty_terms="за день",
    )
    method = TransportMethod(id=1, code="truck", name="Машина", durations={"collection": 2, "customs": 1}, active=True)
    milestones = []
    session = Session(
        Result(["container", "truck"]),
        Result([method]),
        Result(["SKU-PLAN"]),
        Result([]),
        Result(milestones),
        by_id={12: order},
    )
    with pytest.raises(HTTPException) as missing_target:
        await routes.plan_order(12, OrderPlanIn(transport_method_code="truck"), session)
    assert missing_target.value.status_code == 422

    monkeypatch.setattr(routes, "_ensure_default_methods", AsyncMock())
    method_session = Session(
        Result([method]),
        Result(["SKU-PLAN"]),
        Result([requirement]),
        Result([]),
        Result([]),
        by_id={12: order},
    )
    result = await routes.plan_order(
        12,
        OrderPlanIn(transport_method_code="truck", target_arrival_date=date(2026, 9, 22)),
        method_session,
    )
    assert result.order_id == 12 and order.target_arrival_date == date(2026, 9, 22)
