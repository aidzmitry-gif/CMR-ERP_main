from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from modules.sales import routes
from modules.sales.schemas import StageCreate, StageUpdate, TaskCreate, TaskUpdate


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
        self.added_many = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, _statement):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        if isinstance(value, routes.DealTask) and value.id is None:
            value.id = 101
            value.status = "open"
            value.result = None
            self.objects[(routes.DealTask, value.id)] = value
        self.added.append(value)

    def add_all(self, values):
        self.added_many.extend(values)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class EventBus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((session, event_type, payload))


def _deal(**overrides) -> SimpleNamespace:
    values = {
        "id": 11,
        "number": "D-11",
        "title": "Battery supply",
        "counterparty": "ACME",
        "amount": Decimal("100"),
        "priority": "Средний",
        "stage": "new",
        "owner": "Manager",
        "next_step": None,
        "next_step_at": None,
        "deal_date": None,
        "closed_date": None,
        "focus": False,
        "starred": False,
        "probability": 40,
        "expected_close_date": None,
        "created_at": None,
        "stage_changed_at": None,
        "lost_reason_code": None,
        "lost_comment": None,
        "funnel": "new_clients",
        "ship_deadline": None,
        "penalty_rate_pct": None,
        "penalty_cap_pct": None,
        "penalty_terms": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_ping_and_board_return_real_dtos_from_fake_query_results():
    deal = _deal()
    stage = SimpleNamespace(code="new", title="Новая", color="#fff", probability=25)
    out = await routes.board(session=Session(Result([deal]), Result([stage]), Result([])))

    assert await routes.ping() == {"module": "sales", "status": "ok"}
    assert out.stages[0].model_dump(exclude={"deals"}) == {
        "id": "new",
        "title": "Новая",
        "color": "#fff",
        "count": 1,
        "sum": 100.0,
        "weighted": 40.0,  # deal-specific probability overrides the stage default
    }
    assert out.stages[0].deals[0].number == "D-11"


@pytest.mark.asyncio
async def test_funnels_support_extra_codes_and_legacy_schema_fallback():
    rows = await routes.list_funnels(
        Session(Result([("new_clients", 3), ("custom", 2)]), Result(["custom"]))
    )
    assert [(row.code, row.active_deals) for row in rows][-1] == ("custom", 2)
    assert next(row for row in rows if row.code == "new_clients").active_deals == 3

    legacy = Session(OperationalError("SELECT", {}, RuntimeError("missing funnel")))
    fallback = await routes.list_funnels(legacy)
    assert legacy.rollbacks == 1
    assert all(row.active_deals == 0 for row in fallback)


@pytest.mark.asyncio
async def test_list_stages_loss_reasons_history_and_tasks_keep_domain_data():
    active = SimpleNamespace(code="new", funnel="new_clients")
    other = SimpleNamespace(code="rp_new", funnel="repeat_clients")
    assert await routes.list_stages("new_clients", Session(Result([active, other]))) == [active]

    reason = SimpleNamespace(code="price", title="Price")
    assert await routes.loss_reasons(Session(Result([reason]))) == [reason]

    history = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    assert await routes.deal_history(11, Session(Result(history))) == history

    task = SimpleNamespace(
        id=7,
        deal_id=11,
        title="Call",
        kind="call",
        assignee_id=None,
        due_at=None,
        status="open",
        result=None,
    )
    out = await routes.list_tasks(11, Session(Result([task])))
    assert [(item.id, item.overdue) for item in out] == [(7, False)]


@pytest.mark.asyncio
async def test_stage_crud_applies_payload_and_reports_conflicts_or_missing_stage():
    payload = StageCreate(code="qual", title="Qualification", probability=20)
    created_session = Session(Result([]))
    created = await routes.create_stage(payload, created_session)
    assert created.code == "qual" and created.probability == 20
    assert created_session.added == [created] and created_session.commits == 1

    existing = SimpleNamespace(code="qual")
    with pytest.raises(HTTPException, match="уже есть"):
        await routes.create_stage(payload, Session(Result([existing])))

    stage = SimpleNamespace(code="qual", title="Old", probability=20, is_active=True)
    updated = await routes.update_stage(
        "qual", StageUpdate(title="New", probability=65, is_active=False), Session(Result([stage]))
    )
    assert (updated.title, updated.probability, updated.is_active) == ("New", 65, False)
    with pytest.raises(HTTPException, match="не найдена"):
        await routes.update_stage("gone", StageUpdate(title="Unused"), Session(Result([])))


@pytest.mark.asyncio
async def test_task_create_and_completion_emit_precise_events(monkeypatch):
    deal = _deal()
    bus = EventBus()
    core = SimpleNamespace(event_bus=bus)
    session = Session(objects={(routes.Deal, 11): deal})
    due_at = datetime(2026, 9, 18, 9, 0)

    created = await routes.create_task(11, TaskCreate(title="Call", kind="call", due_at=due_at), core, session)
    task = session.added[0]
    assert created.model_dump() == {
        "id": 101,
        "deal_id": 11,
        "title": "Call",
        "kind": "call",
        "assignee_id": None,
        "due_at": due_at,
        "status": "open",
        "result": None,
        "overdue": False,
    }
    assert bus.events[0][1:] == ("sales.task.created", {"task_id": 101, "deal_id": 11, "entity_ref": "deal:11"})

    monkeypatch.setattr(routes, "_utcnow", lambda: datetime(2026, 9, 17, 12, 0))
    completed = await routes.update_task(
        101, TaskUpdate(status="done", result="Called"), core, session
    )
    assert (completed.status, completed.result, task.done_at) == ("done", "Called", datetime(2026, 9, 17, 12, 0))
    assert bus.events[1][1:] == (
        "sales.task.completed",
        {"task_id": 101, "deal_id": 11, "entity_ref": "deal:11"},
    )
    assert session.commits == 2
