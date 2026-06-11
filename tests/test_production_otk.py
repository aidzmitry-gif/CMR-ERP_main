"""Тесты ОТК: решения принять/доработка/брак и претензия в закупки при браке."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent

pytestmark = pytest.mark.asyncio

PRODUCT = "Аккумулятор LiFePO4 RADIAN 12V 100Ah"


async def _decide(api, decision, **extra):
    payload = {"decision": decision, "product": PRODUCT, "order_code": "№250"}
    payload.update(extra)
    return await api.post("/production/qc/decisions", json=payload)


async def test_accept_decision(api):
    r = await _decide(api, "accept", inspector="Никита")
    assert r.status_code == 201
    body = r.json()
    assert body["decision"] == "accept"
    assert body["inspector"] == "Никита"


async def test_rework_decision(api):
    r = await _decide(api, "rework", reason="Не держит ёмкость")
    assert r.status_code == 201
    assert r.json()["reason"] == "Не держит ёмкость"


async def test_invalid_decision_422(api):
    r = await _decide(api, "maybe")
    assert r.status_code == 422


async def test_scrap_emits_claim_event(api, session):
    await _decide(api, "scrap", reason="Пайка БМС · непропай")
    events = (
        await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "production.scrap")
        )
    ).scalars().all()
    assert len(events) == 1
    payload = events[0].payload
    assert payload["item"] == PRODUCT
    assert payload["reason"] == "Пайка БМС · непропай"
    assert payload["entity_ref"].startswith("production:qc:")


async def test_accept_does_not_emit_event(api, session):
    await _decide(api, "accept")
    events = (
        await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "production.scrap")
        )
    ).scalars().all()
    assert events == []


async def test_journal_newest_first(api):
    await _decide(api, "accept")
    await _decide(api, "rework", reason="доработка")
    journal = (await api.get("/production/qc/decisions")).json()
    assert journal[0]["decision"] == "rework"  # последнее — первым
    assert len(journal) == 2


async def test_qc_stats_pass_rate(api):
    await _decide(api, "accept")
    await _decide(api, "accept")
    await _decide(api, "rework")
    await _decide(api, "scrap")
    stats = (await api.get("/production/qc/stats")).json()
    assert stats["accepted"] == 2
    assert stats["rework"] == 1
    assert stats["scrap"] == 1
    assert stats["total"] == 4
    assert stats["pass_rate"] == 50.0  # 2 из 4


async def test_qc_stats_empty(api):
    stats = (await api.get("/production/qc/stats")).json()
    assert stats["total"] == 0
    assert stats["pass_rate"] == 0.0
