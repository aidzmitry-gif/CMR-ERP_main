from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from modules.wms import routes
from modules.wms.models import (
    InventoryCount,
    InventoryLine,
    Receipt,
    ReceiptLine,
    StockThreshold,
    Task,
)
from modules.wms.schemas import (
    InventoryLineCreate,
    QcDecisionIn,
    QcLineDecision,
    ReceiptCreate,
    ReceiptLineIn,
    TaskUpdate,
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
        if isinstance(value, InventoryLine) and value.note is None:
            value.note = ""
        if isinstance(value, Receipt) and value.decided_by is None:
            value.decided_by = ""
        self.added.append(value)

    def add_all(self, values):
        for value in values:
            if getattr(value, "id", None) is None:
                value.id = 100 + len(self.added) + len(self.added_many)
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
async def test_snapshot_and_valued_rows_are_honest_about_missing_gateway_and_cost():
    assert await routes._snapshot_from_1c(core(), Session(), "A", "Главный") == (Decimal("0"), None)
    gateway = SimpleNamespace(stock_by_sku=AsyncMock(return_value=None))
    assert await routes._snapshot_from_1c(core(gateway), Session(), "A", "Главный") == (Decimal("0"), None)
    gateway.stock_by_sku.return_value = {"rows": [{"warehouse": "Другой", "qty_available": 2, "cost": 4}]}
    assert await routes._snapshot_from_1c(core(gateway), Session(), "A", "Главный") == (Decimal("0"), None)
    gateway.stock_by_sku.return_value = {"rows": [{"warehouse": "Главный", "qty_available": 2, "cost": 4.5}]}
    assert await routes._snapshot_from_1c(core(gateway), Session(), "A", "Главный") == (Decimal("2"), Decimal("4.5"))

    assert await routes._valued_rows(Session(), core()) == ([], 0.0, False)
    gateway = SimpleNamespace(stock_by_sku=AsyncMock())
    session = Session(Result([("A", "Главный", Decimal("5")), ("B", "Главный", Decimal("-2"))]), Result([("A", "Альфа"), ("B", "Бета")]))
    # Patch through the module attribute so the test isolates the 1C boundary.
    original = routes._snapshot_from_1c
    routes._snapshot_from_1c = AsyncMock(side_effect=[(Decimal("10"), Decimal("3")), (Decimal("0"), None)])
    try:
        rows, total, available = await routes._valued_rows(session, core(gateway))
    finally:
        routes._snapshot_from_1c = original
    assert [(row.sku_code, row.value) for row in rows] == [("A", 15.0), ("B", None)]
    assert (total, available) == (15.0, True)


@pytest.mark.asyncio
async def test_deficit_rows_deduplicate_thresholds_clamp_free_and_sort_by_deficit():
    first = StockThreshold(id=1, sku_code="A", warehouse="Главный", min_qty=5, reorder_qty=-2, active=True)
    duplicate = StockThreshold(id=2, sku_code="A", warehouse="Главный", min_qty=99, reorder_qty=50, active=True)
    second = StockThreshold(id=3, sku_code="B", warehouse="Главный", min_qty=2, reorder_qty=4, active=True)
    session = Session(Result([first, duplicate, second]), Result([("A", "Альфа"), ("B", "Бета")]))
    gateway = SimpleNamespace(stock_by_sku=AsyncMock(side_effect=[
        {"rows": [{"warehouse": "Главный", "qty_available": 1, "qty_reserved": 3, "cost": 10}]},
        {"rows": [{"warehouse": "Главный", "qty_available": 1, "qty_reserved": 0, "cost": None}]},
    ]))

    rows = await routes._deficit_rows(session, gateway)

    assert [(row.sku_code, row.free_qty, row.deficit, row.severity, row.reorder_qty, row.unit_cost) for row in rows] == [
        ("A", 0.0, 5.0, "out_of_stock", 0.0, 10.0),
        ("B", 1.0, 1.0, "below_min", 4.0, None),
    ]


@pytest.mark.asyncio
async def test_stock_mirror_and_reconciliation_project_gateway_rows_and_money_diffs():
    assert (await routes.stock_mirror(session=Session(), core=core())).gateway is False
    skus = [SimpleNamespace(code="A", title="Альфа", unit="шт"), SimpleNamespace(code="B", title="Бета", unit="шт")]
    gateway = SimpleNamespace(stock_by_sku=AsyncMock(side_effect=[
        {"rows": [{"warehouse": "Главный", "qty_available": 10, "qty_reserved": 3, "qty_forecast": 2, "updated_at": None}]},
        None,
    ]))
    mirror = await routes.stock_mirror(session=Session(Result(skus)), core=core(gateway), limit=1)
    assert mirror.truncated is True
    assert mirror.rows[0].qty_free == 7 and mirror.total_available == 10

    reconciliation = await routes.reconciliation(session=Session(), core=core())
    assert reconciliation.gateway is False
    gateway = SimpleNamespace(stock_by_sku=AsyncMock(return_value={"rows": [{"warehouse": "Главный", "qty_available": 8, "cost": 4}]}))
    session = Session(Result([("A", "Главный", 10)]), Result([("A", "Альфа")]))
    result = await routes.reconciliation(session=session, core=core(gateway))
    assert result.rows[0].diff == 2 and result.rows[0].diff_value == 8 and result.total_abs_diff_value == 8


@pytest.mark.asyncio
async def test_inventory_fill_skips_existing_and_zero_stock_skus():
    class Gateway:
        async def stock_by_sku(self, session, code):
            return {
                "A": {"rows": [{"warehouse": "Главный", "qty_available": 5, "cost": 2}]},
                "B": {"rows": [{"warehouse": "Главный", "qty_available": 0, "cost": 3}]},
            }.get(code)

    skus = [SimpleNamespace(code="A", title="А", unit="шт"), SimpleNamespace(code="B", title="Б", unit="шт")]
    doc = SimpleNamespace(id=7, warehouse="Главный")
    session = Session(Result(["A"]), Result(skus))
    await routes._fill_inventory_from_1c(session, core(Gateway()), doc)
    assert len(session.added) == 0

    session = Session(Result([]), Result(skus))
    await routes._fill_inventory_from_1c(session, core(Gateway()), doc)
    assert len(session.added) == 1
    assert (session.added[0].sku_code, session.added[0].expected_qty, session.added[0].unit_cost) == (
        "A", Decimal("5"), Decimal("2")
    )


@pytest.mark.asyncio
async def test_inventory_line_and_complete_create_adjustments_and_respect_open_guard():
    doc = InventoryCount(id=7, warehouse="Главный", status="open", number="ИНВ-7", note="", created_at=None, completed_at=None)
    line = InventoryLine(id=8, count_id=7, sku_code="A", sku_title="А", unit="шт", expected_qty=10, counted_qty=8, unit_cost=2, note="")
    session = Session(Result([SimpleNamespace(title="А", unit="шт")]), gets={(InventoryCount, 7): doc})
    added = await routes.add_inventory_line(7, InventoryLineCreate(sku_code="A", counted_qty=8), session, core(), None)
    assert added.counted_qty == 8 and session.commits == 1

    session = Session(Result([line]), gets={(InventoryCount, 7): doc})
    await routes.complete_inventory(7, session)
    assert doc.status == "done" and len(session.added) == 1
    assert session.added[0].kind == "out" and session.added[0].qty == Decimal("2")

    with pytest.raises(HTTPException) as closed:
        await routes._open_count(Session(gets={(InventoryCount, 7): SimpleNamespace(status="done")}), 7)
    assert closed.value.status_code == 409


@pytest.mark.asyncio
async def test_receipt_qc_accept_and_tasks_write_only_expected_wms_movements():
    receipt = Receipt(id=4, number="ПРМ-4", source="manual", entity_ref="", warehouse="Главный", status="pending_qc", counterparty="Альфа", created_at=None, decided_at=None, decided_by="")
    line = ReceiptLine(id=9, receipt_id=4, sku_code="A", sku_title="А", expected_qty=5, accepted_qty=None, rejected_qty=None, reject_reason="", location_id=2, batch_ref="B")
    session = Session(Result([SimpleNamespace(title="А")]), Result([line]), Result([line]), gets={(Receipt, 4): receipt})
    created = await routes.create_receipt(
        ReceiptCreate(warehouse="Главный", lines=[ReceiptLineIn(sku_code="A", expected_qty=5, location_id=2)]), session
    )
    assert receipt.status == "pending_qc" and created.number == "ПРМ-2026-0100"

    session = Session(Result([line]), Result([line]), gets={(Receipt, 4): receipt})
    await routes.qc_receipt(4, QcDecisionIn(decisions=[QcLineDecision(line_id=9, accepted_qty=4, rejected_qty=1, reject_reason="брак")], decided_by="qc"), session)
    assert (line.accepted_qty, line.rejected_qty, receipt.decided_by) == (Decimal("4"), Decimal("1"), "qc")

    session = Session(Result([line]), Result([line]), gets={(Receipt, 4): receipt})
    await routes.accept_receipt(4, session)
    assert receipt.status == "accepted"
    assert [type(item) for item in session.added] == [routes.StockMovement, Task]

    task = Task(id=12, kind="putaway", status="open", sku_code="A", qty=4, warehouse="Главный", from_location_id=1, to_location_id=None, doc_ref="", assignee="", priority="normal", note="", done_at=None)
    with pytest.raises(HTTPException) as no_destination:
        await routes.update_task(12, TaskUpdate(status="done"), Session(gets={(Task, 12): task}))
    assert no_destination.value.status_code == 400
    task.to_location_id = 3
    task_session = Session(gets={(Task, 12): task})
    await routes.update_task(12, TaskUpdate(status="done"), task_session)
    assert task.status == "done" and len(task_session.added_many) == 2


@pytest.mark.asyncio
async def test_alerts_return_gateway_state_and_emit_each_deficit(monkeypatch):
    deficit = routes._Deficit(1, "A", "А", "Главный", 0, 3, 3, 5, "out_of_stock", 10)
    monkeypatch.setattr(routes, "_deficit_rows", AsyncMock(return_value=[deficit]))
    assert (await routes.alerts(Session(), core())).gateway is False
    gateway = SimpleNamespace()
    result = await routes.alerts(Session(), core(gateway), None)
    assert result.gateway is True and result.rows[0].deficit == 3

    with pytest.raises(HTTPException) as missing:
        await routes.emit_alerts(Session(), core(), None)
    assert missing.value.status_code == 503
    calls = []
    bus = SimpleNamespace(emit=lambda *args: calls.append(args))
    app_core = core(gateway, bus)
    session = Session()
    emitted = await routes.emit_alerts(session, app_core, None)
    assert emitted.emitted == 1 and session.commits == 1
    assert len(calls) == 1
