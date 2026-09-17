from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from modules.leads import events


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

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result([])

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for index, value in enumerate(self.added, start=1):
            if getattr(value, "id", None) is None:
                value.id = index


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def ctx(session, bus=None):
    return SimpleNamespace(
        session=session,
        services=SimpleNamespace(event_bus=bus or Bus()),
    )


@pytest.mark.asyncio
async def test_campaign_event_creates_scored_leads_with_valid_source_and_utm(monkeypatch):
    async def score(_lead, _session):
        return None

    monkeypatch.setattr("modules.leads.leads.apply_initial_score", score)
    session = Session()
    bus = Bus()
    await events.on_campaign_launched(
        {
            "name": "Осень",
            "channel": "unknown-channel",
            "leads": 2,
            "utm_source": " ads ",
            "utm_medium": "cpc",
            "utm_campaign": "autumn",
        },
        ctx(session, bus),
    )
    assert len(session.added) == 2
    assert all(lead.source == "site" for lead in session.added)
    assert session.added[0].utm_source == "ads"
    assert len(bus.calls) == 2
    assert bus.calls[0][1] == "leads.lead.received"
    assert bus.calls[0][2]["entity_ref"] == "lead:1"


@pytest.mark.asyncio
async def test_unknown_incoming_call_creates_lead_and_revives_rejected_contact(monkeypatch):
    async def score(_lead, _session):
        return None

    rejected = SimpleNamespace(id=77)
    monkeypatch.setattr("modules.leads.leads.apply_initial_score", score)
    monkeypatch.setattr("modules.leads.leads.find_open_lead_by_phone", AsyncMockResult(None))
    monkeypatch.setattr("modules.leads.leads.find_last_rejected_by_contact", AsyncMockResult(rejected))
    cancel = Mock()
    monkeypatch.setattr("modules.leads.leads.cancel_pending_wake", cancel)

    session = Session(Result([]))  # no known CRM contact
    bus = Bus()
    await events.on_call_logged(
        {"direction": "in", "phone": "+375291234567", "agent_ext": "204"},
        ctx(session, bus),
    )
    lead = session.added[0]
    assert (lead.source, lead.phone, lead.message, lead.revived_from_id) == (
        "phone",
        "+375291234567",
        "Входящий звонок (доб. 204)",
        77,
    )
    cancel.assert_called_once_with(rejected)
    assert bus.calls[-1][1] == "leads.lead.received"


@pytest.mark.asyncio
async def test_repeated_call_with_two_companies_is_left_unchanged(monkeypatch):
    duplicate = SimpleNamespace(id=8, company="Alpha", message="old", last_touch_at=None)
    monkeypatch.setattr("modules.leads.leads.find_open_lead_by_phone", AsyncMockResult(duplicate))
    session = Session(Result([]), Result([SimpleNamespace(company="Alpha"), SimpleNamespace(company="Beta")]))
    await events.on_call_logged(
        {"direction": "in", "phone": "+375291234567", "agent_ext": "204"},
        ctx(session),
    )
    assert (duplicate.message, duplicate.last_touch_at) == ("old", None)
    assert session.added == []


@pytest.mark.asyncio
async def test_intake_event_deduplicates_and_new_lead_keeps_attribution(monkeypatch):
    async def score(_lead, _session):
        return None

    async def resolve(_session, _lead):
        return None

    rejected = SimpleNamespace(id=21)
    monkeypatch.setattr("modules.leads.leads.apply_initial_score", score)
    monkeypatch.setattr("modules.leads.leads.resolve_customer", resolve)
    monkeypatch.setattr("modules.leads.leads.find_open_lead_by_phone", AsyncMockResult(None))
    monkeypatch.setattr("modules.leads.leads.find_open_lead_by_email", AsyncMockResult(None))
    monkeypatch.setattr("modules.leads.leads.find_last_rejected_by_contact", AsyncMockResult(rejected))
    cancel = Mock()
    monkeypatch.setattr("modules.leads.leads.cancel_pending_wake", cancel)

    session = Session()
    bus = Bus()
    await events.on_intake_lead(
        {
            "source": "invalid",
            "name": " Иван ",
            "company": " Альфа ",
            "phone": " +37529 ",
            "email": " a@example.test ",
            "message": " Нужно КП ",
            "utm_source": "google",
            "landing_url": "https://example.test/landing",
        },
        ctx(session, bus),
    )
    lead = session.added[0]
    assert (lead.source, lead.name, lead.company, lead.email, lead.message) == (
        "site",
        "Иван",
        "Альфа",
        "a@example.test",
        "Нужно КП",
    )
    assert (lead.revived_from_id, bus.calls[-1][2]["landing_url"]) == (21, "https://example.test/landing")
    cancel.assert_called_once_with(rejected)

    duplicate = SimpleNamespace(
        id=31,
        message="старое",
        last_touch_at=None,
        customer_kind="",
    )
    monkeypatch.setattr("modules.leads.leads.find_open_lead_by_phone", AsyncMockResult(duplicate))
    await events.on_intake_lead(
        {"source": "email", "phone": "+37529", "company": "Альфа", "message": "новое"},
        ctx(Session(), bus),
    )
    assert "новое" in duplicate.message


@pytest.mark.asyncio
async def test_deal_created_event_links_existing_lead_only_when_both_ids_exist(monkeypatch):
    from modules.leads.models import Lead

    lead = SimpleNamespace(deal_id=None)
    session = Session(objects={(Lead, 5): lead})
    await events.on_deal_created_from_lead({"lead_id": 5, "deal_id": 42}, ctx(session))
    assert lead.deal_id == 42
    await events.on_deal_created_from_lead({"lead_id": None, "deal_id": 42}, ctx(session))
    await events.on_deal_created_from_lead({"lead_id": 5, "deal_id": None}, ctx(session))


class AsyncMockResult:
    def __init__(self, value):
        self.value = value

    async def __call__(self, *_args, **_kwargs):
        return self.value
