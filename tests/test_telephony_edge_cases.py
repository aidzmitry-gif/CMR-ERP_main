"""Provider input and call-delivery regressions identified in the CI coverage report."""
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from core.domain.models import Contact, Counterparty, OutboxEvent
from core.services.eventbus import EventContext, OutboxEventBus
from modules.integrations.telephony import ZruchnaClient, normalize_e164, parse_event
from modules.sales import calls
from modules.sales.models import CallLog


@pytest.mark.parametrize("raw, expected", [
    ("01:02:03", 3723), ("02:03", 123), ("00:00", 0),
    ("1:2:3:4", None), ("bad:03", None), ("1:-2", None),
    ("-1", None), ("inf", None), ("NaN", None),
])
def test_provider_duration_formats_preserve_valid_values_and_reject_garbage(raw, expected):
    parsed = parse_event({"type": "hangup", "uniqueid": "DURATION", "duration": raw, "hold": raw})
    assert parsed["event_type"] == "telephony.call.ended"
    assert parsed["payload"]["duration_sec"] == expected
    assert parsed["payload"]["hold_sec"] == expected


@pytest.mark.parametrize("raw, expected", [("84951234567", "+74951234567"), ("441234567890", "+441234567890")])
def test_non_belarus_phone_keeps_country_code(raw, expected):
    assert normalize_e164(raw) == expected


@pytest.mark.parametrize("url", [None, 123, {"url": "https://pbx.test/call"}])
async def test_wrong_configuration_type_never_constructs_http_client(url, monkeypatch):
    def unexpected_client(**kwargs):
        pytest.fail("Invalid configuration must not reach the provider")

    monkeypatch.setattr("modules.integrations.telephony.httpx.AsyncClient", unexpected_client)
    gateway = ZruchnaClient(url)
    assert gateway.configured is False
    with pytest.raises(RuntimeError):
        await gateway.originate("101", "+375291234567")


@pytest.mark.parametrize("body", ["{broken", "[]"])
async def test_bad_json_body_preserves_authenticated_query_event(api, session, body, monkeypatch):
    monkeypatch.setattr(api._transport.app.state.core.config, "telephony_webhook_token", "synthetic-token")
    response = await api.post(
        "/integrations/telephony/zruchna",
        params={"token": "synthetic-token", "type": "in", "uniqueid": "QUERY-EVENT"},
        content=body, headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    event = (await session.execute(select(OutboxEvent))).scalar_one()
    assert event.event_type == "telephony.call.incoming"
    assert event.payload["call_id"] == "QUERY-EVENT"
    assert "token" not in event.payload


async def test_form_body_overrides_query_and_preserves_encoded_values(api, session, monkeypatch):
    monkeypatch.setattr(api._transport.app.state.core.config, "telephony_webhook_token", "synthetic-token")
    response = await api.post(
        "/integrations/telephony/zruchna?token=wrong&type=hangup&uniqueid=QUERY",
        data={"token": "synthetic-token", "type": "in", "uniqueid": "FORM",
              "phone": "+375291234567", "code": "001", "did": ""},
    )
    assert response.status_code == 200
    event = (await session.execute(select(OutboxEvent))).scalar_one()
    assert event.event_type == "telephony.call.incoming"
    assert event.payload["call_id"] == "FORM"
    assert event.payload["phone_e164"] == "+375291234567"
    assert event.payload["agent_ext"] == "001"
    assert event.payload["did"] is None
    assert "token" not in event.payload


def test_slow_sse_subscriber_does_not_drop_other_subscribers_or_old_cards(caplog):
    owner = "COVERAGE-SSE"
    slow, healthy = calls.subscribe(owner), calls.subscribe(owner)
    sentinel = {"call_id": "OLD"}
    try:
        assert calls.has_subscriber(owner)
        for _ in range(slow.maxsize):
            slow.put_nowait(sentinel)
        call = CallLog(call_id="NEW", direction="in", owner=owner, status="ringing")
        assert calls._push_card(call) is True
        card = healthy.get_nowait()
        call.status = "ended"
        assert card["call_id"] == "NEW"
        assert card["status"] == "ringing"  # queued snapshot does not follow later ORM mutations
        assert slow.qsize() == slow.maxsize
        assert slow.get_nowait() is sentinel
        assert "переполнена" in caplog.text
        calls.unsubscribe(owner, healthy)
        assert calls.has_subscriber(owner)
        slow.put_nowait(sentinel)
        assert calls._push_card(call) is False
    finally:
        calls.unsubscribe(owner, slow)
        calls.unsubscribe(owner, healthy)
    assert not calls.has_subscriber(owner)
    calls.unsubscribe(owner, healthy)  # disconnect retry is harmless


async def test_invalid_direct_handler_input_has_no_call_or_outbox_side_effects(session):
    ctx = EventContext(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    for handler in calls.EVENT_HANDLERS.values():
        await handler({"call_id": "VALID"}, None)  # legacy direct-call contract
        await handler({"call_id": "   "}, ctx)
    await session.flush()
    assert await session.scalar(select(func.count()).select_from(CallLog)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


async def test_answer_first_creates_one_log_and_late_metadata_fills_once(session):
    ctx = EventContext(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    await calls.on_call_answered({"call_id": "ANSWER-FIRST", "direction": "out"}, ctx)
    call = (await session.execute(select(CallLog))).scalar_one()
    answered_at = call.answered_at
    assert call.status == "answered"
    assert answered_at is not None
    await calls.on_call_answered({"call_id": "ANSWER-FIRST", "did": "LINE-A", "agent_ext": "001"}, ctx)
    await calls.on_call_answered({"call_id": "ANSWER-FIRST", "did": "LINE-B", "agent_ext": "002"}, ctx)
    await session.flush()
    assert call.did == "LINE-A"
    assert call.agent_ext == "001"
    assert call.answered_at == answered_at
    logged = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == "sales.call.logged"))).scalars().all()
    assert len(logged) == 1
    assert logged[0].payload["call_id"] == "ANSWER-FIRST"
    assert await session.scalar(select(func.count()).select_from(CallLog)) == 1


@pytest.mark.parametrize("status", ["busy", "failed"])
async def test_terminal_failure_keeps_zero_durations_in_call_and_event(session, status):
    ctx = EventContext(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    await calls.on_call_ended({"call_id": "FAILED-CALL", "event": "hangup", "status": status,
                               "duration_sec": 0, "hold_sec": 0}, ctx)
    call = (await session.execute(select(CallLog))).scalar_one()
    assert call.status == status
    assert call.duration_sec == 0
    assert call.hold_sec == 0
    assert call.ended_at is not None
    event = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == "sales.call.ended"))).scalar_one()
    assert event.payload["status"] == status
    assert event.payload["duration_sec"] == 0


@pytest.mark.parametrize("with_counterparty", [False, True])
async def test_contact_without_owned_deal_does_not_guess_employee(session, with_counterparty):
    cp = Counterparty(name="COVERAGE-UNASSIGNED", unp="190008812") if with_counterparty else None
    if cp is not None:
        session.add(cp)
        await session.flush()
    contact = Contact(full_name="Synthetic", phone="+375291234567", counterparty_id=cp.id if cp else None)
    session.add(contact)
    await session.flush()
    resolved = await calls.resolve_owner(session, "+375291234567")
    assert resolved == {"owner": "", "owner_id": None, "counterparty_id": cp.id if cp else None,
                        "contact_id": contact.id, "deal_id": None}
