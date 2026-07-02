"""tests/test_marketing_phase_e.py — Phase E: UTM-атрибуция и доска кампаний."""
from __future__ import annotations

import importlib
import os

import pytest

_CAMPAIGN = {
    "name": "Phase-E Test",
    "channel": "seo",
    "budget": 5000.50,
    "leads": 0,
    "utm_source": "google",
    "utm_medium": "organic",
    "utm_campaign": "test-phase-e",
    "goal": "увеличить лиды",
}


@pytest.mark.asyncio
async def test_attribution_empty(api):
    """GET /marketing/campaigns/attribution → 200, пустой список."""
    r = await api.get("/marketing/campaigns/attribution")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_attribution_counts_leads(session, api):
    """POST кампания → on_lead_received → attribution показывает leads=1."""
    r = await api.post("/marketing/campaigns", json=_CAMPAIGN)
    assert r.status_code == 201
    campaign_id = r.json()["id"]

    from modules.marketing.seo_events import on_lead_received

    class FakeCtx:
        def __init__(self, s):
            self.session = s

    await on_lead_received(
        {"utm_campaign": "test-phase-e", "lead_id": 42},
        FakeCtx(session),
    )
    await session.commit()

    r2 = await api.get("/marketing/campaigns/attribution")
    assert r2.status_code == 200
    data = r2.json()
    found = next((c for c in data if c["id"] == campaign_id), None)
    assert found is not None
    assert found["leads"] == 1


@pytest.mark.asyncio
async def test_campaigns_list_has_utm_fields(api):
    """GET /marketing/campaigns → поля utm_source, utm_medium, utm_campaign присутствуют."""
    r = await api.post("/marketing/campaigns", json=_CAMPAIGN)
    assert r.status_code == 201
    body = r.json()
    for field in ("utm_source", "utm_medium", "utm_campaign"):
        assert field in body, f"Поле {field} отсутствует в ответе POST /campaigns"

    listed = await api.get("/marketing/campaigns")
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) >= 1
    for field in ("utm_source", "utm_medium", "utm_campaign"):
        assert field in items[0], f"Поле {field} отсутствует в GET /campaigns"


@pytest.mark.asyncio
async def test_budget_is_string(api):
    """Поле budget в ответе — строка (не float), BYN-совместимо."""
    r = await api.post("/marketing/campaigns", json={**_CAMPAIGN, "budget": 1234.56})
    assert r.status_code == 201
    assert isinstance(r.json()["budget"], str), "budget в POST /campaigns должен быть строкой"

    attr = await api.get("/marketing/campaigns/attribution")
    assert attr.status_code == 200
    items = attr.json()
    if items:
        assert isinstance(items[0]["budget"], str), "budget в attribution должен быть строкой"

    listed = await api.get("/marketing/campaigns")
    assert listed.status_code == 200
    list_items = listed.json()
    if list_items:
        assert isinstance(list_items[0]["budget"], str), "budget в GET /campaigns должен быть строкой"


@pytest.mark.asyncio
async def test_import_main():
    """import main не падает — модели и роутеры marketing зарегистрированы корректно."""
    os.environ.setdefault("AIOS_AUTH_MODE", "dev")
    os.environ.setdefault("AIOS_ENVIRONMENT", "dev")
    importlib.import_module("main")
