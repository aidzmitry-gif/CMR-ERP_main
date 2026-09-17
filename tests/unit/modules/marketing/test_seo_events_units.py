from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.marketing.seo_events import on_lead_received


class Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class Session:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_seo_lead_handler_ignores_missing_context_and_empty_attribution():
    await on_lead_received({"lead_id": 1}, None)
    ctx = SimpleNamespace(session=Session())
    await on_lead_received({"lead_id": 1}, ctx)


@pytest.mark.asyncio
async def test_seo_lead_handler_matches_campaign_by_utm_campaign():
    campaign = SimpleNamespace(name="SEO", id=4, leads=2)
    ctx = SimpleNamespace(session=Session(Result(campaign)))

    await on_lead_received(
        {"lead_id": 1, "utmCampaign": "spring", "utmSource": "google"},
        ctx,
    )

    assert campaign.leads == 3


@pytest.mark.asyncio
async def test_seo_lead_handler_falls_back_to_latest_seo_campaign_and_can_miss():
    campaign = SimpleNamespace(name="SEO", id=5, leads=0)
    ctx = SimpleNamespace(session=Session(Result(campaign)))
    await on_lead_received({"lead_id": 2, "utm_source": "seo"}, ctx)
    assert campaign.leads == 1

    missed = SimpleNamespace(session=Session(Result(None)))
    await on_lead_received({"lead_id": 3, "utm_campaign": "unknown"}, missed)
