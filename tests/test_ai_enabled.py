"""API-тесты AI-эндпоинтов при ВКЛЮЧЁННОМ AI-слое (mock-режим шлюза).

Дополняют тесты с выключенным AI (503): покрывают рабочие ветки генерации и
фиксацию AI-действий событиями (трассировка в audit, §3.3).
"""
from sqlalchemy import select

from core.domain.models import OutboxEvent


async def test_ai_draft_reply_enabled(ai_api):
    deal = (
        await ai_api.post("/sales/deals", json={"number": "AID-1", "title": "t", "counterparty": "c"})
    ).json()
    r = await ai_api.post(f"/sales/deals/{deal['id']}/ai/draft-reply")
    assert r.status_code == 200
    body = r.json()
    assert body["text"] and body["model"] == "qwen2.5"


async def test_ai_draft_reply_uses_last_inbound(session, ai_api):
    deal = (
        await ai_api.post("/sales/deals", json={"number": "AID-3", "title": "t", "counterparty": "c"})
    ).json()
    await ai_api.post(
        f"/sales/deals/{deal['id']}/messages",
        json={"channel": "whatsapp", "text": "Когда отгрузка?", "direction": "in"},
    )
    r = await ai_api.post(f"/sales/deals/{deal['id']}/ai/draft-reply")
    assert r.status_code == 200
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "ai.draft.generated" in types


async def test_ai_assist_enabled_both_kinds(session, ai_api):
    deal = (
        await ai_api.post("/sales/deals", json={"number": "AID-2", "title": "t", "counterparty": "c"})
    ).json()
    for kind in ("summary", "next_step"):
        r = await ai_api.post(f"/sales/deals/{deal['id']}/ai/assist", json={"kind": kind})
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == kind and body["text"]

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "ai.summary.generated" in types
    assert "ai.next_step.generated" in types


async def test_ai_lead_qualify_with_rationale(session, ai_api):
    lead = (
        await ai_api.post(
            "/leads",
            json={"source": "site", "company": "ООО AI", "product": "лист", "phone": "+375290000000"},
        )
    ).json()
    r = await ai_api.post(f"/leads/{lead['id']}/qualify")
    assert r.status_code == 200
    body = r.json()
    assert body["ai_rationale"] and body["model"] == "qwen2.5"
    assert body["score"] > 0

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "ai.lead.qualified" in types  # AI-ветка эмитит именно это событие


async def test_owner_ai_insight_enabled(ai_api):
    r = await ai_api.get("/system/owner/insight")
    assert r.status_code == 200
    assert r.json()["text"]
