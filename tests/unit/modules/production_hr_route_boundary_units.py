from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modules.hr import routes as hr_routes
from modules.hr.models import Employee
from modules.hr.schemas import CandidateCreate, OkkScoreCreate, PayrollAccrueIn, PayrollPayIn
from modules.production import routes as production_routes
from modules.production.models import ProductionBom, ProductionNorm, ProductionWorker
from modules.production.schemas import (
    BomItemCreate,
    NormCreate,
    NormUpdate,
    QcDecisionIn,
    WorkerCreate,
)


class Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class Session:
    def __init__(self, *, gets=None, results=()):
        self.gets = gets or {}
        self.results = list(results)
        self.added = []
        self.deleted = []
        self.commits = 0
        self.flushes = 0
        self.refreshed = []
        self._next_id = 40

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = self._next_id
            self._next_id += 1
        self.added.append(value)

    async def get(self, model, identity):
        return self.gets.get((model, identity))

    async def execute(self, _statement):
        return self.results.pop(0)

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        self.refreshed.append(value)

    async def delete(self, value):
        self.deleted.append(value)


class EventBus:
    def __init__(self):
        self.events = []

    def emit(self, session, topic, payload):
        self.events.append((session, topic, payload))


@pytest.mark.asyncio
async def test_production_norm_and_worker_creates_set_dto_fields_and_commit():
    session = Session()

    norm = await production_routes.create_norm(NormCreate(title="Сборка", nh=2.5), session)
    worker = await production_routes.create_worker(
        WorkerCreate(name="Иван", salary=1200, days_worked=11, nh_output=7.5), session
    )

    assert isinstance(norm, ProductionNorm)
    assert (norm.title, norm.nh, norm.status) == ("Сборка", 2.5, "pending")
    assert isinstance(worker, ProductionWorker)
    assert (worker.name, worker.salary, worker.nh_output) == ("Иван", 1200, 7.5)
    assert session.commits == 2
    assert session.refreshed == [norm, worker]


@pytest.mark.asyncio
async def test_production_norm_update_and_qc_scrap_preserve_failure_and_event_contracts():
    norm = SimpleNamespace(id=5, title="Сборка", nh=2.5, note="", status="approved")
    session = Session(gets={(ProductionNorm, 5): norm})

    updated = await production_routes.update_norm(5, NormUpdate(nh=0), session)

    assert updated is norm
    assert (norm.nh, norm.status) == (0, "none")

    bus = EventBus()
    core = SimpleNamespace(event_bus=bus)
    qc = await production_routes.create_qc(
        QcDecisionIn(
            decision="scrap", order_code="PZ-7", product="Корпус", reason="Трещина"
        ),
        core,
        session,
    )

    assert qc.id == 40
    assert session.flushes == 1
    assert bus.events == [
        (
            session,
            "production.scrap",
            {
                "item": "Корпус",
                "reason": "Трещина",
                "order_code": "PZ-7",
                "entity_ref": "production:qc:40",
            },
        )
    ]
    with pytest.raises(HTTPException, match="Решение должно быть") as error:
        await production_routes.create_qc(QcDecisionIn(decision="discard"), core, session)
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_production_bom_requires_items_to_approve_and_resets_to_draft_on_add():
    bom = SimpleNamespace(id=8, product="Батарея", version="v1", note="", status="approved")
    empty_session = Session(gets={(ProductionBom, 8): bom}, results=[Result()])

    with pytest.raises(HTTPException, match="пустую спецификацию") as error:
        await production_routes.approve_bom(8, empty_session)
    assert error.value.status_code == 409

    add_session = Session(gets={(ProductionBom, 8): bom})
    item = await production_routes.add_bom_item(
        8,
        BomItemCreate(component="Корпус", norm_qty=2, stock=3, reserved=2),
        add_session,
    )

    assert item.model_dump() == {
        "id": 40,
        "bom_id": 8,
        "component": "Корпус",
        "norm_qty": 2.0,
        "unit": "шт",
        "stock": 3.0,
        "reserved": 2.0,
        "status": "short",
    }
    assert bom.status == "draft"
    assert add_session.commits == 1


@pytest.mark.asyncio
async def test_hr_candidate_payroll_and_okk_handlers_emit_and_mutate_real_models():
    session = Session(gets={(Employee, 7): SimpleNamespace(id=7, full_name="Иван Иванов")})
    bus = EventBus()
    core = SimpleNamespace(event_bus=bus)

    candidate = await hr_routes.create_candidate(
        CandidateCreate(name="Анна", position="HR", salary=1250.5), session
    )
    accrued = await hr_routes.payroll_accrue(
        PayrollAccrueIn(employee_id=7, period="2026-09", amount_byn="1200.50"), core, session
    )
    score = await hr_routes.create_okk_score(
        OkkScoreCreate(employee_id=7, period="2026-09", discipline=25, quality=20, service=15, teamwork=10),
        session,
    )

    assert (candidate.number, candidate.salary) == ("CAND-2026-0040", Decimal("1250.5"))
    assert (accrued.id, accrued.status) == (41, "pending")
    assert score.total == 70
    assert bus.events == [
        (
            session,
            "hr.payroll.accrued",
            {
                "employee_id": 7,
                "employee_name": "Иван Иванов",
                "period": "2026-09",
                "amount_byn": "1200.50",
                "entity_ref": "payroll:41",
            },
        )
    ]
    assert session.flushes == 2
    assert session.commits == 3


@pytest.mark.asyncio
async def test_hr_payroll_pay_marks_pending_entry_or_returns_idempotent_not_found():
    entry = SimpleNamespace(id=12, employee_id=7, period="2026-09", amount_byn="1200.50", status="pending")
    session = Session(results=[Result([entry])])
    bus = EventBus()

    paid = await hr_routes.payroll_pay(
        PayrollPayIn(employee_id=7, period="2026-09"), SimpleNamespace(event_bus=bus), session
    )

    assert paid is entry
    assert entry.status == "paid"
    assert bus.events[0][1:] == (
        "hr.payroll.paid",
        {
            "employee_id": 7,
            "period": "2026-09",
            "amount_byn": "1200.50",
            "entity_ref": "payroll:12",
        },
    )

    with pytest.raises(HTTPException, match="Начисление не найдено") as error:
        await hr_routes.payroll_pay(
            PayrollPayIn(employee_id=7, period="2026-10"),
            SimpleNamespace(event_bus=EventBus()),
            Session(results=[Result()]),
        )
    assert error.value.status_code == 404
