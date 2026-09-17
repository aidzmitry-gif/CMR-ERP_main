from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modules.hr import routes
from modules.hr.models import Candidate, Employee, OkkScore, PayrollEntry
from modules.hr.schemas import (
    CandidateCreate,
    EmployeeCreate,
    OkkScoreCreate,
    PayrollAccrueIn,
    PayrollPayIn,
    StageUpdate,
)


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self, *results, objects=None):
        self.results = list(results)
        self.objects = objects or {}
        self.added = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = 100 + len(self.added)
        self.added.append(value)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        self.refreshed.append(value)


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


@pytest.mark.asyncio
async def test_hr_employees_candidates_and_payroll_cover_crud_summary_and_events():
    employee = await routes.create_employee(EmployeeCreate(full_name="Анна", position="Менеджер"), Session())
    assert employee.full_name == "Анна"
    assert await routes.list_employees(Session(Result([employee]))) == [employee]

    candidate = await routes.create_candidate(CandidateCreate(name="Иван", position="Сборщик", salary=1800), Session())
    assert (candidate.number, candidate.salary) == ("CAND-2026-0100", Decimal("1800"))
    stored = Candidate(id=2, number="CAND-2", name="Иван", position="Сборщик", salary=Decimal("1800"), recruiter="Ольга", priority="Высокий", stage="new", next_step="интервью")
    assert await routes.list_candidates(Session(Result([stored]))) == [stored]
    assert (await routes.board(Session(Result([stored])))).stages
    assert (await routes.update_candidate(2, StageUpdate(stage="offer"), Session(objects={(Candidate, 2): stored}))).stage == "offer"
    with pytest.raises(HTTPException, match="Кандидат не найден"):
        await routes.update_candidate(404, StageUpdate(stage="offer"), Session())

    entries = [
        PayrollEntry(id=1, employee_id=1, period="2026-09", amount_byn="100.00", status="pending"),
        PayrollEntry(id=2, employee_id=1, period="2026-09", amount_byn="50.50", status="paid"),
    ]
    assert await routes.list_payroll(1, "2026-09", "pending", Session(Result(entries))) == entries
    summary = await routes.payroll_summary(Session(Result(entries)))
    assert summary[0].model_dump() == {"period": "2026-09", "total_byn": "150.50", "count": 2, "pending_count": 1}
    assert await routes.get_payroll_entry(1, Session(objects={(PayrollEntry, 1): entries[0]})) is entries[0]
    with pytest.raises(HTTPException, match="Запись не найдена"):
        await routes.get_payroll_entry(404, Session())

    bus = Bus()
    emp = Employee(id=1, full_name="Анна", position="Менеджер", department="Продажи", status="active")
    accrued = await routes.payroll_accrue(PayrollAccrueIn(employee_id=1, period="2026-09", amount_byn="100.00"), SimpleNamespace(event_bus=bus), Session(objects={(Employee, 1): emp}))
    assert accrued.status == "pending" and bus.calls[0][1] == "hr.payroll.accrued"
    pending = PayrollEntry(id=3, employee_id=1, period="2026-09", amount_byn="100.00", status="pending")
    paid = await routes.payroll_pay(PayrollPayIn(employee_id=1, period="2026-09"), SimpleNamespace(event_bus=bus), Session(Result([pending])))
    assert paid.status == "paid" and bus.calls[-1][1] == "hr.payroll.paid"


@pytest.mark.asyncio
async def test_hr_okk_scores_and_payroll_missing_boundaries_are_explicit():
    score = await routes.create_okk_score(OkkScoreCreate(employee_id=1, period="2026-09", discipline=20, quality=22, service=21, teamwork=23), Session())
    assert score.total == 86
    stored = OkkScore(id=4, employee_id=1, period="2026-09", discipline=20, quality=22, service=21, teamwork=23, total=86, comment="")
    assert await routes.list_okk_scores(1, "2026-09", Session(Result([stored]))) == [stored]
    assert await routes.get_okk_score(4, Session(objects={(OkkScore, 4): stored})) is stored
    with pytest.raises(HTTPException, match="ОКК-оценка не найдена"):
        await routes.get_okk_score(404, Session())
    with pytest.raises(HTTPException, match="Сотрудник не найден"):
        await routes.payroll_accrue(PayrollAccrueIn(employee_id=404, period="2026-09", amount_byn="1"), SimpleNamespace(event_bus=Bus()), Session())
    with pytest.raises(HTTPException, match="Начисление не найдено"):
        await routes.payroll_pay(PayrollPayIn(employee_id=1, period="2026-09"), SimpleNamespace(event_bus=Bus()), Session(Result()))
