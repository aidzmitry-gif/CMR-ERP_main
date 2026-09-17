from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from modules.leads import routes
from modules.leads.models import Lead
from modules.leads.schemas import LeadCreate, LeadPlanIn, RejectIn


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def scalars(self):
        return self


class Session:
    def __init__(self, *results, objects=None):
        self.results = list(results)
        self.objects = objects or {}
        self.added = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, _statement):
        return self.results.pop(0)

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for index, value in enumerate(self.added, start=1):
            if getattr(value, "id", None) is None:
                value.id = index

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        self.refreshed.append(value)


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def core_with(bus: Bus):
    return SimpleNamespace(
        event_bus=bus,
        services=SimpleNamespace(llm=SimpleNamespace(enabled=False, model=None)),
    )


@pytest.mark.asyncio
async def test_list_leads_returns_attached_leads_after_wake_cycle(monkeypatch):
    leads = [Lead(id=2, source="site"), Lead(id=1, source="email")]
    session = Session(Result(leads))
    wake = AsyncMock()
    attach = AsyncMock(return_value=leads)
    monkeypatch.setattr(routes, "_wake_due_snoozed", wake)
    monkeypatch.setattr(routes, "_attach_item_totals", attach)

    out = await routes.list_leads(status="new", session=session)

    assert out == leads
    wake.assert_awaited_once_with(session)
    attach.assert_awaited_once_with(session, leads)


@pytest.mark.asyncio
async def test_create_lead_scores_revives_and_emits_received_payload(monkeypatch):
    session = Session()
    bus = Bus()
    initial_score = AsyncMock()
    resolve = AsyncMock()
    rejected = SimpleNamespace(id=44, reject_reason="не сейчас", snooze_until=datetime(2026, 9, 20))
    cancel = Mock(return_value=True)
    monkeypatch.setattr(routes, "find_open_lead_by_phone", AsyncMock(return_value=None))
    monkeypatch.setattr(routes, "find_open_lead_by_email", AsyncMock(return_value=None))
    monkeypatch.setattr(routes, "apply_initial_score", initial_score)
    monkeypatch.setattr(routes, "resolve_customer", resolve)
    monkeypatch.setattr(routes, "find_last_rejected_by_contact", AsyncMock(return_value=rejected))
    monkeypatch.setattr(routes, "cancel_pending_wake", cancel)
    monkeypatch.setattr(routes, "is_key_lead", lambda lead: lead.source == "tender")
    payload = LeadCreate(
        source="tender",
        company="ООО Альфа",
        phone="+375291234567",
        utm_source="ads",
        utm_medium="cpc",
        utm_campaign="autumn",
    )

    lead = await routes.create_lead(payload, core_with(bus), session)

    assert lead is session.added[0]
    assert (lead.id, lead.revived_from_id, lead.is_key) == (1, 44, True)
    initial_score.assert_awaited_once_with(lead, session)
    resolve.assert_awaited_once_with(session, lead)
    cancel.assert_called_once_with(rejected)
    assert session.commits == 1 and session.refreshed == [lead]
    assert bus.calls == [
        (
            session,
            "leads.lead.received",
            {
                "lead_id": 1,
                "source": "tender",
                "entity_ref": "lead:1",
                "utm_source": "ads",
                "utm_medium": "cpc",
                "utm_campaign": "autumn",
            },
        )
    ]


@pytest.mark.asyncio
async def test_qualify_updates_lead_returns_dto_and_emits_non_ai_event(monkeypatch):
    now = datetime(2026, 9, 17, 9, 0)
    lead = Lead(id=7, source="site", status="new")
    session = Session(objects={(Lead, 7): lead})
    bus = Bus()
    monkeypatch.setattr(routes, "_utcnow", lambda: now)
    monkeypatch.setattr(routes, "_compute_score", AsyncMock(return_value=(70, "target", "есть телефон")))

    out = await routes.qualify(7, core_with(bus), session)

    assert out.model_dump() == {
        "id": 7,
        "status": "qualified",
        "score": 70,
        "qualification": "target",
        "reason": "есть телефон",
        "ai_rationale": None,
        "model": None,
    }
    assert lead.first_action_at == now
    assert session.commits == 1
    assert bus.calls == [
        (
            session,
            "leads.lead.qualified",
            {"lead_id": 7, "score": 70, "verdict": "target", "entity_ref": "lead:7"},
        )
    ]


@pytest.mark.asyncio
async def test_reject_not_now_sets_snooze_dto_and_emits_event(monkeypatch):
    now = datetime(2026, 9, 17, 9, 0)
    lead = Lead(id=8, source="site", status="qualified")
    session = Session(objects={(Lead, 8): lead})
    bus = Bus()
    monkeypatch.setattr(routes, "_utcnow", lambda: now)

    out = await routes.reject_lead(8, RejectIn(reason="не сейчас", snooze_days=30), core_with(bus), session)

    assert out.model_dump() == {"id": 8, "status": "rejected", "reject_reason": "не сейчас"}
    assert lead.first_action_at == now
    assert lead.snooze_until == now + timedelta(days=30)
    assert session.commits == 1
    assert bus.calls == [
        (session, "leads.lead.rejected", {"lead_id": 8, "reason": "не сейчас", "entity_ref": "lead:8"})
    ]


@pytest.mark.asyncio
async def test_plan_handlers_map_sql_boundary_results_to_dtos_and_persist_new_targets(monkeypatch):
    plan = SimpleNamespace(
        leads_target=20,
        qualified_target=8,
        converted_target=3,
        reaction_target_min=15,
        updated_at=None,
    )
    session = Session()
    monkeypatch.setattr(routes, "_get_plan", AsyncMock(return_value=plan))
    facts = AsyncMock(side_effect=[(19, 7, 2, None), (21, 9, 4, 12)])
    monkeypatch.setattr(routes, "_plan_facts", facts)
    updated_at = datetime(2026, 9, 17, 10, 0)
    monkeypatch.setattr(routes, "_utcnow", lambda: updated_at)

    initial = await routes.get_plan(session)
    updated = await routes.set_plan(
        LeadPlanIn(
            leads_target=30,
            qualified_target=12,
            converted_target=5,
            reaction_target_min=10,
        ),
        session,
    )

    assert initial.model_dump() == {
        "leads_target": 20,
        "qualified_target": 8,
        "converted_target": 3,
        "reaction_target_min": 15,
        "leads_fact": 19,
        "qualified_fact": 7,
        "converted_fact": 2,
        "reaction_fact_min": None,
    }
    assert updated.model_dump() == {
        "leads_target": 30,
        "qualified_target": 12,
        "converted_target": 5,
        "reaction_target_min": 10,
        "leads_fact": 21,
        "qualified_fact": 9,
        "converted_fact": 4,
        "reaction_fact_min": 12,
    }
    assert plan.updated_at == updated_at
    assert session.commits == 2
    assert facts.await_count == 2
