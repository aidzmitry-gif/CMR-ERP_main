from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from modules.integrations.alfa import AlfaBankClient
from modules.integrations.registry import RegistryClient
from modules.integrations.routes import _check_intake_token, _extract_utm, _parse_sender


def _core(*, token="", environment="dev"):
    return SimpleNamespace(
        config=SimpleNamespace(intake_webhook_token=token, environment=environment)
    )


def test_extract_utm_prefers_explicit_fields_and_supports_camel_case():
    assert _extract_utm(
        {
            "utm_source": "form",
            "utmSource": "ignored",
            "utm_medium": "cpc",
            "utm_campaign": "launch",
            "landingUrl": "https://site.example/form",
        }
    ) == {
        "utm_source": "form",
        "utm_medium": "cpc",
        "utm_campaign": "launch",
        "landing_url": "https://site.example/form",
    }


def test_extract_utm_reads_first_query_url_and_preserves_landing_url():
    result = _extract_utm(
        {
            "landing_url": "https://site.example/product?utm_source=google&utm_medium=cpc&utm_campaign=spring",
        }
    )
    assert result == {
        "utm_source": "google",
        "utm_medium": "cpc",
        "utm_campaign": "spring",
        "landing_url": "https://site.example/product?utm_source=google&utm_medium=cpc&utm_campaign=spring",
    }

    assert _extract_utm({"referrer": "https://google.example/?utm_source=ref"})["utm_source"] == "ref"
    assert _extract_utm({"name": "no campaign"}) == {
        "utm_source": "",
        "utm_medium": "",
        "utm_campaign": "",
        "landing_url": "",
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Иван Иванов <ivan@example.com>", ("Иван Иванов", "ivan@example.com")),
     ('  "ООО Альфа" < sales@example.com > ', ("ООО Альфа", "sales@example.com")),
     (" plain@example.com ", ("", "plain@example.com"))],
)
def test_parse_sender(raw, expected):
    assert _parse_sender(raw) == expected


def test_intake_token_is_fail_closed_in_prod_and_constant_time_validated():
    _check_intake_token(_core(token="secret"), {"token": "secret"})


def test_intake_token_rejects_missing_or_wrong_secret_and_allows_dev_without_one():
    with pytest.raises(Exception) as missing:
        _check_intake_token(_core(token="secret"), {})
    assert getattr(missing.value, "status_code", None) == 403

    with pytest.raises(Exception) as wrong:
        _check_intake_token(_core(token="secret"), {"token": "wrong"})
    assert getattr(wrong.value, "status_code", None) == 403

    with pytest.raises(Exception) as prod:
        _check_intake_token(_core(environment="prod"), {})
    assert getattr(prod.value, "status_code", None) == 403
    _check_intake_token(_core(environment="development"), {})


@pytest.mark.asyncio
async def test_registry_client_uses_honest_local_fallback_and_remote_contract(monkeypatch):
    local = RegistryClient()
    assert await local.lookup(" ") is None
    assert await local.lookup("191234567") == {
        "unp": "191234567",
        "name": "ООО «Аккумулятор»",
        "address": "г. Минск, ул. Промышленная, 5",
        "status": "Действующий",
    }
    assert await local.lookup("000000000") is None

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"vfullname": "ООО Remote", "vaddress": "Минск", "vstate": "active"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url):
            assert url == "https://egr.example/190000001"
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    assert await RegistryClient("https://egr.example/").lookup("190000001") == {
        "unp": "190000001",
        "name": "ООО Remote",
        "address": "Минск",
        "status": "active",
    }


@pytest.mark.asyncio
async def test_registry_remote_errors_and_404_are_graceful(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

        def raise_for_status(self):
            raise httpx.HTTPStatusError("bad", request=httpx.Request("GET", "https://egr"), response=self)

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, response):
            self.response = response

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url):
            return self.response

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient(FakeResponse(404)))
    assert await RegistryClient("https://egr.example").lookup("1") is None
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient(FakeResponse(500)))
    assert await RegistryClient("https://egr.example").lookup("1") is None


@pytest.mark.asyncio
async def test_alfa_client_distinguishes_unconfigured_from_unimplemented():
    assert AlfaBankClient().configured is False
    assert await AlfaBankClient().fetch_incoming() == []
    configured = AlfaBankClient("https://bank.example", "token")
    assert configured.configured is True
    with pytest.raises(NotImplementedError, match="host-to-host"):
        await configured.fetch_incoming()
