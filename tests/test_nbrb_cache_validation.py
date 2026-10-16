from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest


def test_parse_quote_preserves_official_scale():
    from core.services.nbrb import parse_quote

    result = parse_quote({
        "Cur_Abbreviation": "USD", "Date": "2026-09-12T00:00:00", "Cur_OfficialRate": "3.1234",
        "Cur_Scale": 100,
    }, "USD", date(2026, 9, 12))
    assert result == {
        "currency": "USD", "date": "2026-09-12", "official_rate": "3.1234",
        "scale": 100, "rate": "0.031234", "source": "NBRB",
    }


@pytest.mark.parametrize("data", [
    {"Cur_Abbreviation": "EUR", "Date": "2026-09-12", "Cur_OfficialRate": "3", "Cur_Scale": 1},
    {"Cur_Abbreviation": "USD", "Date": "2026-09-13", "Cur_OfficialRate": "3", "Cur_Scale": 1},
    {"Cur_Abbreviation": "USD", "Date": "2026-09-12", "Cur_OfficialRate": "0", "Cur_Scale": 1},
])
def test_parse_quote_rejects_mismatched_or_invalid_payload(data):
    from core.services.nbrb import RateUnavailable, parse_quote

    with pytest.raises(RateUnavailable):
        parse_quote(data, "USD", date(2026, 9, 12))


def test_validate_rejects_future_and_bad_currency():
    from core.services.nbrb import RateUnavailable, validate

    with pytest.raises(RateUnavailable):
        validate("US", date(2026, 9, 12))
    with pytest.raises(RateUnavailable):
        validate("USD", date(2099, 1, 1))


def test_byn_quote_is_identity():
    from core.services.nbrb import quote

    class Bind:
        class Dialect:
            name = "sqlite"

        dialect = Dialect()

    class Session:
        def get_bind(self):
            return Bind()

    # BYN is handled locally and does not require a network request or a demo rate.
    import asyncio

    result = asyncio.run(quote(Session(), "BYN", date(2026, 9, 12)))
    assert result["official_rate"] == "1" and result["scale"] == 1


def rate_session(cached=None):
    return SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: cached)),
        add=Mock(), flush=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_provider_precision_and_cache_replay():
    from core.services.nbrb import quote

    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.params["ondate"] == "2026-09-12"
        assert request.url.params["parammode"] == "2"
        return httpx.Response(200, text='{"Cur_Abbreviation":"USD",'
                              '"Date":"2026-09-12T00:00:00",'
                              '"Cur_OfficialRate":3.1234567890123456789,"Cur_Scale":100}')

    session = rate_session()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        first = await quote(session, "USD", date(2026, 9, 12), client=client)
        assert first["official_rate"] == "3.1234567890123456789"
        stored = session.add.call_args.args[0]
        session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: stored)
        second = await quote(session, "USD", date(2026, 9, 12), client=client)
    assert second == first
    assert len(requests) == 1
    session.add.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("currency", "EUR"), ("date", "2026-09-11"),
    ("official_rate", "NaN"), ("scale", 0), ("scale", True),
    ("source", "demo"), ("rate", "999"),
])
async def test_corrupt_cache_blocks_without_fetch_or_write(field, value):
    from core.services.nbrb import RateUnavailable, quote

    detail = {"currency": "USD", "date": "2026-09-12", "official_rate": "3",
              "scale": 1, "rate": "3", "source": "NBRB"}
    detail[field] = value
    session = rate_session(SimpleNamespace(detail=detail))
    client = SimpleNamespace(get=AsyncMock())
    with pytest.raises(RateUnavailable):
        await quote(session, "USD", date(2026, 9, 12), client=client)
    client.get.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_provider_error_never_saves_fallback_rate():
    from core.services.nbrb import RateUnavailable, quote

    session = rate_session()
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(503)
    )) as client:
        with pytest.raises(RateUnavailable):
            await quote(session, "USD", date(2026, 9, 12), client=client)
    session.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", ["invalid", True, None, "NaN", "Infinity"])
async def test_conversion_rejects_invalid_money_before_fetch(amount):
    from core.services.nbrb import RateUnavailable, convert

    session = rate_session()
    with pytest.raises(RateUnavailable):
        await convert(session, amount, "USD", date(2026, 9, 12))
    session.execute.assert_not_awaited()
