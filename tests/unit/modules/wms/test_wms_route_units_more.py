from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from modules.wms import routes
from modules.wms.models import (
    CycleCountPlan,
    InventoryCount,
    InventoryLine,
    Location,
    StockThreshold,
    Task,
    WarehouseOp,
)
from modules.wms.schemas import (
    AdjustmentIn,
    CyclePlanCreate,
    CyclePlanUpdate,
    InventoryCountCreate,
    LocationCreate,
    LocationUpdate,
    MovementOpIn,
    StageUpdate,
    StockMovementCreate,
    TaskCreate,
    TaskUpdate,
    ThresholdCreate,
    TransferIn,
    WarehouseOpCreate,
)


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar_value = scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.scalar_value


class Session:
    def __init__(self, *results, gets=None):
        self.results = list(results)
        self.gets = gets or {}
        self.added = []
        self.added_many = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()

    async def get(self, model, identity):
        return self.gets.get((model, identity), self.gets.get(identity))

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = 100 + len(self.added) + len(self.added_many)
        self.added.append(value)

    def add_all(self, values):
        for value in values:
            self.add(value)
            self.added_many.append(value)

    async def flush(self):
        for value in [*self.added, *self.added_many]:
            if getattr(value, "id", None) is None:
                value.id = 100

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        self.refreshed.append(value)


def core(stock=None, bus=None):
    return SimpleNamespace(
        services=SimpleNamespace(stock=stock),
        event_bus=bus or SimpleNamespace(emit=lambda *args: None),
    )


@pytest.mark.asyncio
async def test_movements_operations_validate_quantity_emit_shipment_and_preserve_doc_refs():
    created = await routes.create_movement(
        StockMovementCreate(sku_code="A", qty=2.5, reason="manual"), Session()
    )
    assert (created.kind, created.qty, created.reason) == ("in", Decimal("2.5"), "manual")

    received = await routes.receipt(MovementOpIn(sku_code="A", qty=4), Session())
    assert (received.kind, received.reason, received.qty) == ("in", "receipt", Decimal("4"))

    calls = []
    shipment_session = Session()
    shipped = await routes.shipment(
        MovementOpIn(sku_code="A", qty=3, doc_ref="ЗАКАЗ-1"),
        shipment_session,
        core(bus=SimpleNamespace(emit=lambda *args: calls.append(args))),
    )
    assert (shipped.kind, shipped.reason, shipped.doc_ref) == ("out", "shipment", "ЗАКАЗ-1")
    assert calls[0][1] == "wms.shipment.completed"
    assert calls[0][2]["sales_ref"] == "ЗАКАЗ-1"

    no_event = []
    await routes.shipment(
        MovementOpIn(sku_code="A", qty=1), Session(), core(bus=SimpleNamespace(emit=lambda *args: no_event.append(args)))
    )
    assert no_event == []

    transferred = await routes.transfer(
        TransferIn(sku_code="A", qty=5, from_location_id=1, to_location_id=2), Session()
    )
    assert len(transferred) == 2
    assert {item.kind for item in transferred} == {"in", "out"}
    assert transferred[0].doc_ref == transferred[1].doc_ref

    with pytest.raises(HTTPException, match="больше нуля"):
        await routes.transfer(TransferIn(sku_code="A", qty=0, from_location_id=1, to_location_id=2), Session())
    with pytest.raises(HTTPException, match="совпадают"):
        await routes.transfer(TransferIn(sku_code="A", qty=1, from_location_id=1, to_location_id=1), Session())

    positive = await routes.adjustment(AdjustmentIn(sku_code="A", qty=2), Session())
    negative = await routes.adjustment(AdjustmentIn(sku_code="A", qty=-3), Session())
    assert (positive.kind, positive.qty, negative.kind, negative.qty) == ("in", Decimal("2"), "out", Decimal("3"))
    with pytest.raises(HTTPException, match="ноль"):
        await routes.adjustment(AdjustmentIn(sku_code="A", qty=0), Session())


@pytest.mark.asyncio
async def test_locations_balances_and_operations_cover_crud_and_projection_paths():
    locations = [SimpleNamespace(id=1, warehouse="Главный", zone="A", code="A-01", title="Полка", is_active=True)]
    assert await routes.list_locations("Главный", True, Session(Result(locations))) == locations

    created_location = await routes.create_location(LocationCreate(code="B-01", zone="B"), Session())
    assert (created_location.code, created_location.zone) == ("B-01", "B")
    location = Location(id=1, warehouse="Главный", zone="A", code="A-01", title="old", is_active=True)
    updated = await routes.update_location(
        1, LocationUpdate(title="new", is_active=False), Session(gets={(Location, 1): location})
    )
    assert (updated.title, updated.is_active) == ("new", False)
    with pytest.raises(HTTPException, match="Ячейка не найдена"):
        await routes.update_location(404, LocationUpdate(), Session())

    balance = await routes.balances(
        sku="A",
        warehouse="Главный",
        session=Session(
            Result([("A", "Главный", 1, "B1", Decimal("4")), ("B", "Главный", None, None, Decimal("-2"))]),
            Result([("A", "Альфа"), ("B", "Бета")]),
            Result([(1, "A-01")]),
        ),
    )
    assert balance.sku_count == 2
    assert [(row.sku_code, row.location_code, row.qty) for row in balance.rows] == [
        ("A", "A-01", 4.0), ("B", "", -2.0)
    ]

    op = await routes.create_op(
        WarehouseOpCreate(counterparty="Альфа", title="Приёмка", amount=10, items_count=2), Session()
    )
    assert (op.number, op.amount) == ("ОП-2026-0100", Decimal("10"))
    stored = WarehouseOp(id=7, counterparty="Альфа", title="Приёмка", items_count=2, amount=Decimal("10"), zone="A", priority="Высокий", owner="Иван", stage="inbound", number="ОП-7", op_date="2026-09-17")
    listed = await routes.list_ops(Session(Result([stored])))
    board = await routes.board(Session(Result([stored])))
    assert listed == [stored] and board.stages
    moved = await routes.update_op(7, StageUpdate(stage="receiving"), Session(gets={(WarehouseOp, 7): stored}))
    assert moved.stage == "receiving"
    with pytest.raises(HTTPException, match="Операция не найдена"):
        await routes.update_op(404, StageUpdate(stage="qc"), Session())


@pytest.mark.asyncio
async def test_inventory_creation_population_and_line_update_keep_1c_gateway_as_boundary():
    doc = await routes.create_inventory(InventoryCountCreate(warehouse="Главный", note="сентябрь"), Session())
    assert doc.number == "ИНВ-2026-0100"

    existing = InventoryCount(id=7, number="ИНВ-7", warehouse="Главный", status="open", note="", created_at=None, completed_at=None)
    gateway = SimpleNamespace(stock_by_sku=AsyncMock(return_value={"rows": [{"warehouse": "Главный", "qty_available": 5, "cost": 2}]}))
    sku = SimpleNamespace(code="A", title="Альфа", unit="шт")
    populate_session = Session(Result([]), Result([sku]), Result([]), gets={(InventoryCount, 7): existing})
    # The final empty result is consumed by _inventory_detail after filling.
    populated = await routes.populate_inventory(7, populate_session, core(gateway))
    assert populated.id == 7
    assert len(populate_session.added) == 1

    line = InventoryLine(id=8, count_id=7, sku_code="A", sku_title="Альфа", unit="шт", expected_qty=5, counted_qty=None, unit_cost=2, note="")
    line_session = Session(gets={(InventoryLine, 8): line, (InventoryCount, 7): existing})
    changed = await routes.update_inventory_line(8, routes.InventoryLineUpdate(counted_qty=4, note="пересчитано"), line_session)
    assert (changed.counted_qty, changed.note) == (4.0, "пересчитано")
    with pytest.raises(HTTPException, match="Строка инвентаризации не найдена"):
        await routes.update_inventory_line(404, routes.InventoryLineUpdate(), Session())


@pytest.mark.asyncio
async def test_tasks_pack_thresholds_and_cycle_plan_cover_warehouse_alert_inputs():
    task = await routes.create_task(TaskCreate(kind="pick", sku_code="A", qty=2), Session())
    assert (task.kind, task.qty) == ("pick", Decimal("2"))
    pick = Task(id=5, kind="pick", status="open", sku_code="A", qty=Decimal("2"), warehouse="Главный", from_location_id=1, to_location_id=None, doc_ref="", assignee="", priority="normal", note="", done_at=None)
    pick_session = Session(gets={(Task, 5): pick})
    done = await routes.update_task(5, TaskUpdate(status="done"), pick_session)
    assert done.status == "done" and pick_session.added
    listed = await routes.list_tasks("pick", "done", "", Session(Result([pick])))
    assert listed == [pick]

    packed = await routes.pack(MovementOpIn(sku_code="A", qty=2, location_id=4), Session())
    assert packed[0].doc_ref == packed[1].doc_ref and packed[0].reason == "pack"
    with pytest.raises(HTTPException, match="больше нуля"):
        await routes.pack(MovementOpIn(sku_code="A", qty=0), Session())

    threshold = await routes.create_threshold(ThresholdCreate(sku_code="A", min_qty=5, reorder_qty=8), Session())
    assert (threshold.min_qty, threshold.reorder_qty) == (Decimal("5"), Decimal("8"))
    active = StockThreshold(id=1, sku_code="A", warehouse="Главный", min_qty=5, reorder_qty=8, active=True)
    assert await routes.list_thresholds("Главный", Session(Result([active]))) == [active]

    plan = await routes.create_cycle_plan(CyclePlanCreate(warehouse="Главный", zone="A", cadence_days=14), Session())
    assert (plan.warehouse, plan.cadence_days) == ("Главный", 14)
    stored = CycleCountPlan(id=2, warehouse="Главный", zone="A", cadence_days=14, next_due_date=date(2026, 9, 1), last_run_at=None, active=True, abc_class="A")
    changed = await routes.update_cycle_plan(2, CyclePlanUpdate(cadence_days=30, active=False), Session(gets={(CycleCountPlan, 2): stored}))
    assert (changed.cadence_days, changed.active) == (30, False)
    with pytest.raises(HTTPException, match="План не найден"):
        await routes.update_cycle_plan(404, CyclePlanUpdate(), Session())


@pytest.mark.asyncio
async def test_cycle_run_and_dashboard_join_inventory_gateway_and_operational_counts(monkeypatch):
    plan = CycleCountPlan(id=2, warehouse="Главный", zone="A", cadence_days=14, next_due_date=date(2026, 9, 1), last_run_at=None, active=True, abc_class="A")
    gateway = SimpleNamespace(stock_by_sku=AsyncMock(return_value={"rows": []}))
    # run: plan lookup, existing inventory lines, SKU list, then detail lines
    run_session = Session(Result([]), Result([]), gets={(CycleCountPlan, 2): plan})
    result = await routes.run_cycle_plan(2, run_session, core(gateway))
    assert result.number.startswith("ИНВ-2026-") and plan.next_due_date is not None
    with pytest.raises(HTTPException, match="Шлюз остатков"):
        await routes.run_cycle_plan(2, Session(gets={(CycleCountPlan, 2): plan}), core())

    monkeypatch.setattr(routes, "_deficit_rows", AsyncMock(return_value=[]))
    monkeypatch.setattr(routes, "_valued_rows", AsyncMock(return_value=([], 123.0, True)))
    monkeypatch.setattr(routes, "reconciliation", AsyncMock(return_value=SimpleNamespace(rows=[], total_abs_diff_value=0.0)))
    dashboard_session = Session(
        Result(scalar=2), Result(scalar=3), Result(scalar=1), Result(scalar=4),
        Result(scalar=5), Result(scalar=6),
    )
    dashboard = await routes.dashboard(dashboard_session, core(gateway))
    assert dashboard.model_dump() == {
        "receipts_pending_qc": 2,
        "tasks_putaway_open": 3,
        "tasks_pick_open": 1,
        "alerts_count": 0,
        "alerts_deficit_value": 0.0,
        "inventory_value": 123.0,
        "inventories_open": 4,
        "recon_max_diff_value": 0.0,
        "recon_total_diff_value": 0.0,
        "movements_today_in": 5.0,
        "movements_today_out": 6.0,
        "gateway": True,
    }
