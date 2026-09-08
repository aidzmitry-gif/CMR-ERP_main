"""Контракт ГРП МНС. MockTransport проверяет клиент, но не доступность live-источника."""
from datetime import UTC, datetime

import httpx
import pytest

from core.services.registry import RegistryError
from modules.integrations.registry import MNS_ENDPOINT, RegistryClient

ROW = {
    "vunp": "100582333", "vnaimp": "Министерство по налогам и сборам Республики Беларусь",
    "vnaimk": "МНС", "vpadres": "г.Минск,ул.Советская,9", "dreg": "1994-06-30",
    "ckodsost": 1, "vkods": "Действующий", "dlikv": None,
}


@pytest.fixture
def remote(monkeypatch):
    original = httpx.AsyncClient
    requests = []

    def install(response):
        def handle(request):
            requests.append(request)
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(
            httpx, "AsyncClient",
            lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
        )
        return requests

    return install


async def test_demo_is_explicit_and_visible():
    client = RegistryClient(allow_demo=True)
    found = await client.lookup("191234567")
    assert found is not None
    assert found["unp"] == "191234567"
    assert found["source"] == "demo" and found["source_url"] is None
    assert datetime.fromisoformat(found["fetched_at"]).utcoffset().total_seconds() == 0
    assert await client.lookup("000000000") is None
    assert await client.lookup("  ") is None


async def test_default_client_fails_closed():
    with pytest.raises(RegistryError) as failure:
        await RegistryClient().lookup_strict("191234567")
    assert (failure.value.code, failure.value.status_code) == ("unconfigured", 503)
    assert await RegistryClient().lookup("191234567") is None


@pytest.mark.parametrize("unp", ["", "12", "a100582333", "100582333x", "100 582333", "１００５８２３３３", "١٠٠٥٨٢٣٣٣"])
async def test_bad_input_does_not_call_provider(remote, unp):
    requests = remote(httpx.Response(200, json={"row": ROW}))
    with pytest.raises(RegistryError) as failure:
        await RegistryClient(MNS_ENDPOINT).lookup_strict(unp)
    assert (failure.value.code, failure.value.status_code) == ("bad_input", 422)
    assert not requests


async def test_only_verified_endpoint_can_claim_mns_source(remote):
    requests = remote(httpx.Response(200, json={"row": ROW}))
    with pytest.raises(RegistryError) as failure:
        await RegistryClient("https://example.com", allow_demo=True).lookup_strict("191234567")
    assert failure.value.code == "unconfigured"
    assert not requests


@pytest.mark.parametrize("returned_unp", ["100582333", 100582333, " 100582333 "])
async def test_exact_provider_mapping_and_utc_metadata(remote, returned_unp):
    requests = remote(httpx.Response(200, json={"row": {**ROW, "vunp": returned_unp}}))
    before = datetime.now(UTC)
    result = await RegistryClient(MNS_ENDPOINT).lookup_strict(" 100582333 ")
    assert result == {
        "unp": "100582333", "name": ROW["vnaimp"], "short_name": "МНС",
        "address": ROW["vpadres"], "status": "Действующий", "status_code": "1",
        "registered_at": "1994-06-30", "closed_at": None,
        "source": "mns_grp", "source_url": str(requests[0].url), "fetched_at": result["fetched_at"],
    }
    assert before <= datetime.fromisoformat(result["fetched_at"]) <= datetime.now(UTC)
    assert dict(requests[0].url.params) == {"unp": "100582333", "charset": "UTF-8", "type": "json"}
    assert requests[0].url.path == "/api/grp-public/data"
    assert len(requests) == 1


async def test_missing_optional_fields_are_not_invented(remote):
    remote(httpx.Response(200, json={"row": {"vunp": "100582333", "vnaimp": " МНС "}}))
    result = await RegistryClient(MNS_ENDPOINT).lookup_strict("100582333")
    assert result["name"] == "МНС"
    assert result["address"] == result["status"] == ""
    assert result["short_name"] is result["status_code"] is result["registered_at"] is None
    assert not {"bank_account", "phone", "email"} & result.keys()


@pytest.mark.parametrize("row", [
    {**ROW, "vunp": None}, {**ROW, "vunp": "999999999"}, {**ROW, "vunp": True},
    {**ROW, "vunp": 100582333.0}, {**ROW, "vnaimp": " "}, {**ROW, "vnaimp": ["МНС"]},
    {**ROW, "vpadres": {}}, {**ROW, "ckodsost": True}, {**ROW, "dreg": "invalid"},
    {"vnaimp": "Другая организация"}, [ROW], "unexpected",
])
async def test_mismatch_null_unp_and_malformed_fields_rejected(remote, row):
    remote(httpx.Response(200, json={"row": row}))
    with pytest.raises(RegistryError) as failure:
        await RegistryClient(MNS_ENDPOINT).lookup_strict("100582333")
    assert (failure.value.code, failure.value.status_code) == ("invalid_upstream", 502)


@pytest.mark.parametrize("payload", [{}, [], None, {"error": "failed"}])
async def test_missing_envelope_is_schema_error_not_notfound(remote, payload):
    remote(httpx.Response(200, json=payload))
    with pytest.raises(RegistryError) as failure:
        await RegistryClient(MNS_ENDPOINT).lookup_strict("100582333")
    assert failure.value.code == "invalid_upstream"


@pytest.mark.parametrize("row", [None, {}, []])
async def test_explicit_empty_row_is_not_found(remote, row):
    remote(httpx.Response(200, json={"row": row}))
    with pytest.raises(RegistryError) as failure:
        await RegistryClient(MNS_ENDPOINT).lookup_strict("100582333")
    assert (failure.value.code, failure.value.status_code) == ("not_found", 404)


async def test_invalid_json_is_schema_error(remote):
    remote(httpx.Response(200, content=b"<html>broken</html>"))
    with pytest.raises(RegistryError) as failure:
        await RegistryClient(MNS_ENDPOINT).lookup_strict("100582333")
    assert failure.value.code == "invalid_upstream"


@pytest.mark.parametrize(("status", "code", "expected"), [
    (404, "not_found", 404), (401, "upstream_access_denied", 502),
    (403, "upstream_access_denied", 502), (500, "upstream_error", 502),
    (503, "upstream_error", 502), (302, "upstream_error", 502),
])
async def test_upstream_statuses_are_distinct_without_demo_fallback(remote, status, code, expected):
    requests = remote(httpx.Response(status, headers={"Location": "https://example.com"}))
    with pytest.raises(RegistryError) as failure:
        await RegistryClient(MNS_ENDPOINT, allow_demo=True).lookup_strict("191234567")
    assert (failure.value.code, failure.value.status_code) == (code, expected)
    assert len(requests) == 1


@pytest.mark.parametrize(("header", "expected"), [("60", 60), ("99999", 300), ("0", 1), ("bad", None), ("9" * 30, None)])
async def test_rate_limit_bounded_retry_after_no_retry(remote, header, expected):
    requests = remote(httpx.Response(429, headers={"Retry-After": header}))
    with pytest.raises(RegistryError) as failure:
        await RegistryClient(MNS_ENDPOINT).lookup_strict("100582333")
    assert (failure.value.code, failure.value.status_code) == ("rate_limited", 429)
    assert failure.value.retry_after == expected
    assert len(requests) == 1


@pytest.mark.parametrize(("error", "code"), [(httpx.ReadTimeout("timeout"), "timeout"), (httpx.ConnectError("unreachable"), "unreachable")])
async def test_transport_failure_strict_and_graceful_legacy(remote, error, code):
    remote(error)
    client = RegistryClient(MNS_ENDPOINT)
    with pytest.raises(RegistryError) as failure:
        await client.lookup_strict("191234567")
    assert (failure.value.code, failure.value.status_code) == (code, 503)
    assert await client.lookup("191234567") is None
