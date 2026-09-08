"""Локальный контракт click-to-call без сетевого вызова реального провайдера."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.integrations import telephony
from modules.integrations.telephony import ZruchnaClient


class _FakeResponse:
    status_code = 202

    def raise_for_status(self):
        return None


class _FakeAsyncClient:
    calls: list[tuple[str, dict]] = []
    constructed = 0

    def __init__(self, **_kwargs):
        self.__class__.constructed += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url: str, **kwargs):
        self.__class__.calls.append((url, kwargs))
        return _FakeResponse()


@pytest.fixture
def fake_http(monkeypatch):
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.constructed = 0
    monkeypatch.setattr(telephony.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


@pytest.mark.unit
async def test_successful_post_preserves_query_params_and_leading_zeroes(fake_http):
    url = "https://user:pass@pbx.test:65535/client_call_gen.php?token=query-secret"
    client = ZruchnaClient(url)

    result = await client.originate("001", "375291234567")

    assert result == {"ok": True, "status": 202, "vnut": "001", "number": "+375291234567"}
    assert fake_http.calls == [
        (
            url,
            {"params": {"vnut": "001", "number": "+375291234567"}},
        )
    ]


@pytest.mark.unit
@pytest.mark.parametrize("vnut", ["", "1234", "1 01", "ABC", "١٠١", 101])
async def test_invalid_extension_fails_before_http(fake_http, vnut):
    client = ZruchnaClient("https://pbx.test/client_call_gen.php")

    with pytest.raises(ValueError):
        await client.originate(vnut, "375291234567")

    assert fake_http.constructed == 0
    assert fake_http.calls == []


@pytest.mark.unit
@pytest.mark.parametrize("number", [None, "", "   ", "no-number"])
async def test_invalid_number_fails_before_http(fake_http, number):
    client = ZruchnaClient("https://pbx.test/client_call_gen.php")

    with pytest.raises(ValueError):
        await client.originate("101", number)

    assert fake_http.constructed == 0
    assert fake_http.calls == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "",
        "client_call_gen.php",
        "/client_call_gen.php",
        "ftp://pbx.test/call",
        "https://",
        " https://pbx.test/call ",
        "https://pbx.test/\x00call",
        "https://pbx.test:bad/call",
        "https://[bad/call",
        "https://pbx.test:0/call",
        "https://pbx.test:65536/call",
    ],
)
async def test_invalid_config_fails_before_http(fake_http, url):
    client = ZruchnaClient(url)

    assert client.configured is False
    with pytest.raises(RuntimeError):
        await client.originate("101", "375291234567")

    assert fake_http.constructed == 0
    assert fake_http.calls == []


class _FailingGateway:
    configured = True

    async def originate(self, _vnut: str, _number: str) -> dict:
        raise RuntimeError(
            "POST https://user:synthetic-secret@pbx.test/client_call_gen.php?token=query-secret failed"
        )


@pytest.mark.api
async def test_route_sanitizes_provider_failure(api):
    app = api._transport.app
    app.state.core.services.telephony = _FailingGateway()

    response = await api.post(
        "/integrations/telephony/originate",
        json={"vnut": "101", "number": "375291234567"},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "АТС недоступна"}
    assert "synthetic-secret" not in response.text
    assert "query-secret" not in response.text
    assert "client_call_gen.php" not in response.text


@pytest.mark.api
async def test_route_rejects_invalid_extension_without_http(api, monkeypatch):
    class _UnexpectedHTTPClient:
        def __init__(self, **_kwargs):
            raise AssertionError("HTTP client must not be constructed")

    monkeypatch.setattr(telephony.httpx, "AsyncClient", _UnexpectedHTTPClient)
    app = api._transport.app
    app.state.core.services.telephony = ZruchnaClient("https://pbx.test/client_call_gen.php")

    response = await api.post(
        "/integrations/telephony/originate",
        json={"vnut": "1234", "number": "375291234567"},
    )

    assert response.status_code == 422


@pytest.mark.api
async def test_route_invalid_config_returns_503_without_http(api, monkeypatch):
    class _UnexpectedHTTPClient:
        def __init__(self, **_kwargs):
            raise AssertionError("HTTP client must not be constructed")

    monkeypatch.setattr(telephony.httpx, "AsyncClient", _UnexpectedHTTPClient)
    app = api._transport.app
    app.state.core.services.telephony = ZruchnaClient("ftp://pbx.test/client_call_gen.php")

    response = await api.post(
        "/integrations/telephony/originate",
        json={"vnut": "101", "number": "375291234567"},
    )

    assert response.status_code == 503


@pytest.mark.api
@pytest.mark.parametrize(
    "url",
    [
        " https://pbx.test/call ",
        "https://pbx.test/\x00call",
        "https://pbx.test:bad/call",
        "https://[bad/call",
        "https://pbx.test:0/call",
        "https://pbx.test:65536/call",
    ],
)
async def test_route_invalid_url_returns_503_before_http(api, monkeypatch, url):
    class _UnexpectedHTTPClient:
        def __init__(self, **_kwargs):
            raise AssertionError("HTTP client must not be constructed")

    monkeypatch.setattr(telephony.httpx, "AsyncClient", _UnexpectedHTTPClient)
    app = api._transport.app
    app.state.core.services.telephony = ZruchnaClient(url)

    response = await api.post(
        "/integrations/telephony/originate",
        json={"vnut": "101", "number": "375291234567"},
    )

    assert response.status_code == 503


@pytest.mark.api
async def test_route_permission_remains_required(api):
    app = api._transport.app
    app.state.core.services.telephony = SimpleNamespace(configured=True, originate=lambda *_args: None)

    response = await api.post(
        "/integrations/telephony/originate",
        json={"vnut": "101", "number": "375291234567"},
        headers={"X-User-Roles": "sales"},
    )

    assert response.status_code == 403
