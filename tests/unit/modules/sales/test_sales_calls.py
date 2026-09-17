import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.sales import calls


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []

    async def execute(self, _statement):
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for index, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = index

    async def get(self, _model, _identity):
        return None


def _call(**overrides):
    values = {
        "id": 1,
        "call_id": "CALL-1",
        "direction": "in",
        "phone_e164": "+375291234567",
        "did": "100",
        "agent_ext": "201",
        "owner": "Ivan",
        "counterparty_id": 3,
        "contact_id": 4,
        "deal_id": 5,
        "status": "ringing",
        "duration_sec": None,
        "recording_url": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_subscriber_registry_pushes_cards_and_unsubscribes_cleanly():
    calls._subscribers.clear()
    queue = calls.subscribe("Ivan")
    assert calls.has_subscriber("Ivan") is True
    call = _call()
    assert calls._push_card(call) is True
    assert queue.get_nowait()["call_id"] == "CALL-1"

    calls.unsubscribe("Ivan", queue)
    assert calls.has_subscriber("Ivan") is False
    assert calls._push_card(_call(owner="")) is False
    assert calls._push_card(_call(owner="Unknown")) is False


def test_digits_tail_and_card_are_stable_wire_helpers():
    assert calls._digits_tail("+375 (29) 123-45-67") == "291234567"
    assert calls._digits_tail(None) == ""
    assert calls._digits_tail("12345", 3) == "345"
    card = calls._card(_call())
    assert card == {
        "id": 1,
        "call_id": "CALL-1",
        "direction": "in",
        "phone": "+375291234567",
        "did": "100",
        "agent_ext": "201",
        "owner": "Ivan",
        "counterparty_id": 3,
        "contact_id": 4,
        "deal_id": 5,
        "status": "ringing",
        "duration_sec": None,
        "recording_url": None,
    }


@pytest.mark.asyncio
async def test_record_event_creates_unknown_call_and_applies_later_hangup_fields():
    session = Session(Result([]), Result([]))
    call, created = await calls.record_event(
        session,
        {"call_id": "CALL-2", "phone_e164": "+375291112233", "direction": "in"},
        "telephony.call.incoming",
    )
    assert created is True
    assert call.call_id == "CALL-2"
    assert call.owner == ""
    assert call.status == "ringing"

    existing = _call(call_id="CALL-2", status="ringing", ended_at=None, comment="", agent_ext=None)
    session = Session(Result([existing]))
    call, created = await calls.record_event(
        session,
        {
            "call_id": "CALL-2",
            "event": "misscall",
            "status": "no_answer",
            "duration_sec": 8,
            "recording_url": "https://rec/2",
            "agent_ext": "202",
        },
        "telephony.call.ended",
    )
    assert created is False
    assert (call.status, call.duration_sec, call.recording_url, call.agent_ext) == (
        "missed",
        8,
        "https://rec/2",
        "202",
    )


@pytest.mark.asyncio
async def test_record_event_handles_busy_and_transfer_without_fabricating_call_id():
    session = Session(Result([]), Result([]))
    assert await calls.record_event(session, {}, "telephony.call.incoming") == (None, False)

    busy = _call(call_id="CALL-3", status="ringing", ended_at=None, comment=None)
    session = Session(Result([busy]))
    call, created = await calls.record_event(
        session,
        {"call_id": "CALL-3", "status": "busy"},
        "telephony.call.ended",
    )
    assert (created, call.status) == (False, "busy")

    session = Session(Result([busy]))
    call, _ = await calls.record_event(
        session,
        {"call_id": "CALL-3", "to_ext": "205"},
        "telephony.call.transfer",
    )
    assert call.comment == "Перевод на 205"


@pytest.mark.asyncio
async def test_record_event_covers_answered_terminal_and_failed_statuses():
    answered = _call(call_id="CALL-A", status="ringing", ended_at=None, answered_at=None, agent_ext=None, did=None)
    session = Session(Result([answered]))
    call, created = await calls.record_event(
        session,
        {"call_id": "CALL-A", "agent_ext": "202", "did": "101"},
        "telephony.call.answered",
    )
    assert created is False
    assert call.status == "answered" and call.answered_at is not None
    assert (call.agent_ext, call.did) == ("202", "101")

    terminal = _call(call_id="CALL-T", status="ended", ended_at=datetime(2026, 9, 17), answered_at=None)
    call, _ = await calls.record_event(
        Session(Result([terminal])), {"call_id": "CALL-T"}, "telephony.call.answered"
    )
    assert call.status == "ended"

    for provider_status, expected in (("failed", "failed"), ("ok", "ended")):
        finished = _call(call_id=f"CALL-{provider_status}", status="ringing", ended_at=None)
        call, _ = await calls.record_event(
            Session(Result([finished])),
            {
                "call_id": finished.call_id,
                "status": provider_status,
                "hold_sec": 4,
                "duration_sec": 12,
            },
            "telephony.call.ended",
        )
        assert call.status == expected
        assert (call.hold_sec, call.duration_sec, call.ended_at is not None) == (4, 12, True)


@pytest.mark.asyncio
async def test_event_handlers_emit_once_and_ignore_missing_context(monkeypatch):
    class Bus:
        def __init__(self):
            self.events = []

        def emit(self, session, event_type, payload):
            self.events.append((session, event_type, payload))

    bus = Bus()
    services = SimpleNamespace(event_bus=bus)
    ctx = SimpleNamespace(session=Session(Result([]), Result([])), services=services)
    monkeypatch.setattr(
        calls,
        "resolve_owner",
        AsyncMock(
            return_value={"owner": "Ivan", "owner_id": None, "counterparty_id": 3, "contact_id": 4}
        ),
    )
    calls._subscribers.clear()
    queue = calls.subscribe("Ivan")

    await calls.on_incoming_call({"call_id": "CALL-H", "phone_e164": "+375291234567"}, ctx)
    assert len(bus.events) == 1
    assert queue.get_nowait()["call_id"] == "CALL-H"

    existing = _call(call_id="CALL-H", owner="Ivan", ended_at=None, comment=None, answered_at=None)
    await calls.on_call_answered({"call_id": "CALL-H"}, SimpleNamespace(session=Session(Result([existing])), services=services))
    await calls.on_call_ended({"call_id": "CALL-H", "status": "busy"}, SimpleNamespace(session=Session(Result([existing])), services=services))
    await calls.on_call_transfer({"call_id": "CALL-H", "to_ext": "205"}, SimpleNamespace(session=Session(Result([existing])), services=services))
    assert any(event[1] == "sales.call.ended" for event in bus.events)
    calls.unsubscribe("Ivan", queue)

    await calls.on_incoming_call({}, None)
    await calls.on_call_answered({}, None)
    await calls.on_call_ended({}, None)
    await calls.on_call_transfer({}, None)


def test_push_card_reports_queue_full_without_losing_registry():
    calls._subscribers.clear()
    queue = asyncio.Queue(maxsize=1)
    calls._subscribers["Ivan"].add(queue)
    queue.put_nowait({"old": True})
    assert calls._push_card(_call()) is False
    assert calls.has_subscriber("Ivan") is True
    calls._subscribers.clear()
