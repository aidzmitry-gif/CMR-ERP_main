from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from modules.integrations import telephony


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("+375 (29) 123-45-67", "+375291234567"),
        ("00371291234567", "+371291234567"),
        ("8 029 123-45-67", "+375291234567"),
        ("8 912 345-67-89", "+79123456789"),
        ("29 123 45 67", "+375291234567"),
        ("12345", "+12345"),
        ("abc", None),
    ],
)
def test_normalize_e164_handles_local_international_and_invalid_numbers(raw, expected):
    assert telephony.normalize_e164(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("42", 42),
        ("42.9", 42),
        ("01:02", 62),
        ("1:02:03", 3723),
        ("1:2:3:4", None),
        ("1:x", None),
        ("-1", None),
        ("-1:00", None),
        ("inf", None),
    ],
)
def test_duration_parser_is_tolerant_but_does_not_guess_bad_values(raw, expected):
    assert telephony._to_seconds(raw) == expected


def test_parse_event_maps_fields_and_statuses():
    result = telephony.parse_event(
        {
            "type": "DiAl",
            "uniqueid": "call-7",
            "direct": "out",
            "phone": "8 029 123-45-67",
            "did": "103",
            "code": " 42 ",
            "totransfer": "51",
            "status": "bussy",
            "hold": "00:01:02",
            "duration": "2.9",
            "path": " https://recording.example/call-7 ",
            "date": "2026-09-17T09:00:00",
        }
    )

    assert result == {
        "event_type": "telephony.call.incoming",
        "payload": {
            "event": "dial",
            "call_id": "call-7",
            "direction": "out",
            "phone_e164": "+375291234567",
            "did": "103",
            "agent_ext": "42",
            "to_ext": "51",
            "status": "busy",
            "hold_sec": 62,
            "duration_sec": 2,
            "recording_url": "https://recording.example/call-7",
            "at": "2026-09-17T09:00:00",
            "actor": "telephony",
            "entity_ref": "call:call-7",
        },
    }


@pytest.mark.parametrize(
    "params",
    [{"type": "unknown", "uniqueid": "x"}, {"type": "hangup"}, {"type": "", "uniqueid": "x"}],
)
def test_parse_event_ignores_unknown_or_unjoinable_events(params):
    assert telephony.parse_event(params) is None


def test_ingest_emits_only_valid_events():
    bus = SimpleNamespace(events=[])

    def emit(session, event_type, payload):
        bus.events.append((session, event_type, payload))

    bus.emit = emit
    assert telephony.ingest("session", bus, {"type": "misscall", "uniqueid": "c-1"}) == {
        "ok": True,
        "event": "telephony.call.ended",
        "call_id": "c-1",
    }
    assert telephony.ingest("session", bus, {"type": "misscall"}) == {"ok": True, "ignored": True}
    assert bus.events[0][1] == "telephony.call.ended"


def test_originate_params_normalizes_internal_extension_and_number():
    assert telephony.originate_params(" ext-1234 ", "29 123 45 67") == {
        "vnut": "123",
        "number": "+375291234567",
    }
    assert telephony.originate_params("abc", "not-a-number") == {"vnut": "", "number": "not-a-number"}


@pytest.mark.asyncio
async def test_zruchna_client_refuses_unconfigured_originating():
    client = telephony.ZruchnaClient()
    assert client.configured is False
    with pytest.raises(RuntimeError, match="не задан"):
        await client.originate("101", "+375291234567")


@pytest.mark.asyncio
async def test_zruchna_client_posts_normalized_params_at_http_boundary(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 202

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 10.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, params):
            calls.append((url, params))
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    result = await telephony.ZruchnaClient("https://pbx.example/call").originate(
        "101", "29 123 45 67"
    )

    assert result == {
        "ok": True,
        "status": 202,
        "vnut": "101",
        "number": "+375291234567",
    }
    assert calls == [("https://pbx.example/call", {"vnut": "101", "number": "+375291234567"})]
