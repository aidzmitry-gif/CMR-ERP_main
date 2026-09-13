from datetime import date

import httpx
import pytest
from sqlalchemy import select

from core.domain.models import AuditLog
from core.services import nbrb


@pytest.mark.asyncio
async def test_finance_quote_cache_conversion_and_guest_denial(api, session, monkeypatch):
    original_get = httpx.AsyncClient.get
    provider_calls = []

    async def get(client, url, **kwargs):
        if str(url).startswith(nbrb.URL):
            provider_calls.append((url, kwargs))
            return httpx.Response(200, request=httpx.Request("GET", url), json={
                "Cur_Abbreviation": "RUB", "Date": "2026-09-12T00:00:00",
                "Cur_OfficialRate": "3.1234", "Cur_Scale": 100,
            })
        return await original_get(client, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    headers = {"X-User-Roles": "finance"}
    url = "/system/fx/RUB?on=2026-09-12"
    response = await api.get(url, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["scale"] == 100
    assert (await api.get(url, headers=headers)).json() == response.json()
    converted = await api.post("/system/fx/convert", headers=headers, json={
        "amount": "1000", "currency": "RUB", "on": "2026-09-12",
    })
    assert converted.status_code == 200, converted.text
    assert converted.json()["amount_byn"] == "31.23"
    refund = await api.post("/system/fx/convert", headers=headers, json={
        "amount": "-1000", "currency": "RUB", "on": "2026-09-12",
    })
    assert refund.status_code == 200, refund.text
    assert refund.json()["amount_byn"] == "-31.23"
    assert len(provider_calls) == 1
    rows = (await session.scalars(select(AuditLog).where(AuditLog.action == nbrb.ACTION))).all()
    assert len(rows) == 1
    assert (await api.get(url, headers={"X-User-Roles": "unknown-role"})).status_code == 403
    assert len(provider_calls) == 1


@pytest.mark.asyncio
async def test_invalid_quote_request_is_422_and_provider_failure_is_503(api, monkeypatch):
    monkeypatch.setattr(nbrb, "today", lambda: date(2026, 9, 13))
    headers = {"X-User-Roles": "finance"}
    for url in ["/system/fx/USD?on=2026-09-30", "/system/fx/US?on=2026-09-12"]:
        response = await api.get(url, headers=headers)
        assert response.status_code == 422, response.text
    response = await api.post("/system/fx/convert", headers=headers, json={
        "amount": "10", "currency": "USD", "on": "2026-09-30",
    })
    assert response.status_code == 422

    async def unavailable(*args, **kwargs):
        raise nbrb.RateUnavailable("Курс НБРБ недоступен")

    monkeypatch.setattr(nbrb, "quote", unavailable)
    response = await api.get("/system/fx/USD?on=2026-09-12", headers=headers)
    assert response.status_code == 503
    assert response.json()["detail"] == "Курс НБРБ недоступен"
