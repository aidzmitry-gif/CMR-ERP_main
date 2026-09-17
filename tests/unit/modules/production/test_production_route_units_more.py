from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from modules.production import routes
from modules.production.models import (
    ProductionBom,
    ProductionBomItem,
    ProductionNorm,
    ProductionOrder,
    ProductionPlan,
    ProductionWorker,
)
from modules.production.schemas import (
    BomCreate,
    BomItemCreate,
    BomItemUpdate,
    BomUpdate,
    NormCreate,
    NormUpdate,
    PlanCellUpdate,
    PlanPositionUpsert,
    ProductionOrderCreate,
    QcDecisionIn,
    StageUpdate,
    WorkerCreate,
    WorkerUpdate,
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

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self, *results, objects=None, scalar_values=()):
        self.results = list(results)
        self.objects = objects or {}
        self.scalar_values = list(scalar_values)
        self.added = []
        self.deleted = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else 0

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = 100 + len(self.added)
        if isinstance(value, ProductionBom):
            value.version = value.version or "v1"
            value.status = value.status or "draft"
            value.note = value.note or ""
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = 100

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        self.refreshed.append(value)

    async def delete(self, value):
        self.deleted.append(value)


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def core_with(bus: Bus):
    return SimpleNamespace(event_bus=bus)


def bom(bom_id=1, status="draft"):
    return ProductionBom(id=bom_id, product="Контроллер", version="v1", status=status, note="")


def item(item_id=1, bom_id=1, stock=10, reserved=2, norm_qty=5):
    return ProductionBomItem(
        id=item_id, bom_id=bom_id, component="Плата", norm_qty=norm_qty, unit="шт",
        stock=stock, reserved=reserved,
    )


@pytest.mark.asyncio
async def test_orders_norms_workers_payroll_and_qc_cover_state_transitions_and_events(monkeypatch):
    norm = ProductionNorm(id=2, kind="product", title="Контроллер", nh=4.5, status="approved", note="")
    created = await routes.create_order(
        ProductionOrderCreate(product="Контроллер", qty=3),
        Session(Result([norm])),
    )
    assert (created.number, created.nh_per_unit) == ("ПЗ-2026-0100", 4.5)

    order = ProductionOrder(
        id=3, number="ПЗ-3", product="Контроллер", qty=3, progress=20,
        priority="Средний", owner="Мастер", stage="queue", due_date="2026-09-20",
        insight="", nh_per_unit=4.5, made_qty=0,
    )
    bus = Bus()
    updated = await routes.update_order(3, StageUpdate(stage="done"), core_with(bus), Session(objects={(ProductionOrder, 3): order}))
    assert (updated.progress, updated.made_qty, updated.stage) == (100, 3, "done")
    assert bus.calls[0][1] == "production.completed"
    with pytest.raises(HTTPException, match="Наряд не найден"):
        await routes.update_order(404, StageUpdate(stage="done"), core_with(Bus()), Session())
    assert await routes.list_orders(Session(Result([order]))) == [order]
    assert (await routes.board(Session(Result([order])))).stages

    pending = await routes.create_norm(NormCreate(title="Сварка", nh=0), Session())
    assert pending.status == "none"
    approved = await routes.create_norm(NormCreate(title="Сборка", nh=2.5), Session())
    assert approved.status == "pending"
    editable = ProductionNorm(id=4, kind="operation", title="Сварка", nh=1, status="approved", note="")
    changed = await routes.update_norm(4, NormUpdate(nh=0), Session(objects={(ProductionNorm, 4): editable}))
    assert changed.status == "none"
    with pytest.raises(HTTPException, match="без значения"):
        await routes.approve_norm(4, Session(objects={(ProductionNorm, 4): editable}))
    editable.nh = 2
    assert (await routes.approve_norm(4, Session(objects={(ProductionNorm, 4): editable}))).status == "approved"
    delete_session = Session(objects={(ProductionNorm, 4): editable})
    await routes.delete_norm(4, delete_session)
    assert delete_session.deleted == [editable]

    worker = await routes.create_worker(WorkerCreate(name="Анна", salary=2200, days_worked=22, nh_output=100), Session())
    assert worker.name == "Анна"
    stored_worker = ProductionWorker(id=5, name="Борис", salary=1760, days_worked=22, nh_output=80)
    changed_worker = await routes.update_worker(5, WorkerUpdate(nh_output=90), Session(objects={(ProductionWorker, 5): stored_worker}))
    assert changed_worker.nh_output == 90
    payroll = await routes.payroll(Session(Result([stored_worker, ProductionWorker(id=6, name="Анна", salary=2200, days_worked=22, nh_output=100)])))
    assert payroll.rows[0].name == "Анна" and payroll.total_premium == 1187.5
    assert await routes.list_workers(Session(Result([stored_worker]))) == [stored_worker]

    scrap_bus = Bus()
    scrap = await routes.create_qc(QcDecisionIn(decision="scrap", product="Контроллер", order_code="ПЗ-3", reason="трещина"), core_with(scrap_bus), Session())
    assert scrap.decision == "scrap" and scrap_bus.calls[0][1] == "production.scrap"
    with pytest.raises(HTTPException, match="Решение должно"):
        await routes.create_qc(QcDecisionIn(decision="unknown"), core_with(Bus()), Session())
    stats = await routes.qc_stats(Session(Result([
        SimpleNamespace(decision="accept"), SimpleNamespace(decision="rework"), SimpleNamespace(decision="scrap")
    ])))
    assert stats.model_dump() == {"accepted": 1, "rework": 1, "scrap": 1, "total": 3, "pass_rate": 33.3}


@pytest.mark.asyncio
async def test_bom_crud_calculates_coverage_and_reverts_approved_composition_to_draft():
    created = await routes.create_bom(BomCreate(product="Контроллер"), Session())
    assert (created.item_count, created.coverage, created.status) == (0, 100, "draft")

    product_bom = bom(7, "draft")
    items = [item(1, 7, stock=10, reserved=2, norm_qty=5), item(2, 7, stock=2, reserved=1, norm_qty=5)]
    listing = await routes.list_boms(Session(Result([product_bom]), Result(items)))
    assert (listing[0].item_count, listing[0].coverage) == (2, 50)
    detail = await routes.get_bom(7, Session(Result(items), objects={(ProductionBom, 7): product_bom}))
    assert (detail.item_count, detail.items[0].status, detail.items[1].status) == (2, "ok", "short")

    updated = await routes.update_bom(7, BomUpdate(note="обновлено"), Session(Result(items), objects={(ProductionBom, 7): product_bom}))
    assert updated.note == "обновлено"
    with pytest.raises(HTTPException, match="пустую"):
        await routes.approve_bom(7, Session(Result(), objects={(ProductionBom, 7): product_bom}))
    approved = await routes.approve_bom(7, Session(Result(items), objects={(ProductionBom, 7): product_bom}))
    assert approved.status == "approved"

    added = await routes.add_bom_item(7, BomItemCreate(component="Корпус", norm_qty=1, stock=4), Session(objects={(ProductionBom, 7): product_bom}))
    assert added.status == "ok" and product_bom.status == "draft"
    changed_item = item(3, 7, stock=0, reserved=0, norm_qty=1)
    changed = await routes.update_bom_item(3, BomItemUpdate(stock=2), Session(objects={(ProductionBomItem, 3): changed_item, (ProductionBom, 7): product_bom}))
    assert changed.status == "ok" and changed_item.stock == 2
    delete_item_session = Session(objects={(ProductionBomItem, 3): changed_item, (ProductionBom, 7): product_bom})
    await routes.delete_bom_item(3, delete_item_session)
    assert delete_item_session.deleted == [changed_item]
    delete_bom_session = Session(Result(items), objects={(ProductionBom, 7): product_bom})
    await routes.delete_bom(7, delete_bom_session)
    assert delete_bom_session.deleted[-1] is product_bom


@pytest.mark.asyncio
async def test_plan_and_analytics_build_monthly_fact_capacity_and_kpi_read_model(monkeypatch):
    monkeypatch.setattr(routes, "_utcnow", lambda: datetime(2026, 9, 17, 12, 0))
    plan_rows = [
        ProductionPlan(id=1, year=2026, product="Контроллер", month=9, plan_qty=10),
        ProductionPlan(id=2, year=2026, product="Контроллер", month=10, plan_qty=5),
    ]
    orders = [
        ProductionOrder(id=1, product="Контроллер", qty=3, stage="done", made_qty=3, completed_at=datetime(2026, 9, 10), created_at=None, number="ПЗ-1", progress=100, priority="", owner="", due_date=None, insight="", nh_per_unit=4.0),
        ProductionOrder(id=2, product="Другой", qty=1, stage="queue", made_qty=0, completed_at=None, created_at=None, number="ПЗ-2", progress=0, priority="", owner="", due_date=None, insight="", nh_per_unit=2.0),
    ]
    norms = [ProductionNorm(id=1, kind="product", title="Контроллер", nh=4.0, status="approved", note="")]
    session = Session(Result(plan_rows), Result(orders), Result(norms), scalar_values=[2])
    board = await routes.plan_board(2026, session)
    assert board.capacity_nh == 352 and board.rows[0].months[8].fact_qty == 3
    assert board.totals.plan_ytd == 40.0

    existing = ProductionPlan(id=10, year=2026, product="Контроллер", month=9, plan_qty=1)
    cell_session = Session(Result([existing]))
    await routes.update_plan_cell(PlanCellUpdate(year=2026, product="Контроллер", month=9, plan_qty=12), cell_session)
    assert existing.plan_qty == 12 and cell_session.commits == 1

    delete_session = Session(Result([existing]))
    await routes.delete_plan_position(2026, "Контроллер", delete_session)
    assert delete_session.deleted == [existing]

    fake_board = await routes._build_plan_board(Session(Result(plan_rows), Result(orders), Result(norms), scalar_values=[2]), 2026)
    qc = [SimpleNamespace(decision="accept", reason=""), SimpleNamespace(decision="scrap", reason="трещина")]
    workers = [SimpleNamespace(name="Анна", nh_output=100, days_worked=22)]
    monkeypatch.setattr(routes, "_build_plan_board", AsyncMock(return_value=fake_board))
    stats = await routes.analytics(2026, Session(Result(qc), Result(workers)))
    assert stats.efficiency_pct == 56.8 and stats.scrap_reasons == [{"reason": "трещина", "count": 1}]


@pytest.mark.asyncio
async def test_production_read_filters_missing_guards_and_full_position_upsert():
    norm = ProductionNorm(id=8, kind="product", title="Контроллер", nh=2, status="approved", note="")
    assert await routes.list_norms("product", Session(Result([norm]))) == [norm]

    with pytest.raises(HTTPException, match="Норма не найдена"):
        await routes.update_norm(404, NormUpdate(nh=1), Session())
    with pytest.raises(HTTPException, match="Норма не найдена"):
        await routes.approve_norm(404, Session())
    with pytest.raises(HTTPException, match="Норма не найдена"):
        await routes.delete_norm(404, Session())

    qc = SimpleNamespace(id=1, decision="accept")
    assert await routes.list_qc(Session(Result([qc]))) == [qc]

    with pytest.raises(HTTPException, match="Спецификация не найдена"):
        await routes.get_bom(404, Session())
    with pytest.raises(HTTPException, match="Позиция состава не найдена"):
        await routes.update_bom_item(404, BomItemUpdate(stock=1), Session())
    with pytest.raises(HTTPException, match="Позиция состава не найдена"):
        await routes.delete_bom_item(404, Session())

    session = Session(scalar_values=[0])
    board = await routes.upsert_plan_position(
        PlanPositionUpsert(year=2026, product="Контроллер", monthly=[1] * 12), session
    )
    assert session.commits == 1 and len(session.added) == 12
    assert board.year == 2026 and board.rows == []
