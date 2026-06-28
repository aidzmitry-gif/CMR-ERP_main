"""Тесты расширения рекламаций: ручное заведение закупщиком + событие урегулирования.

POST /procurement/claims — ручная претензия (тип/кол-во/сумма). На переходе в resolved/rejected
эмитится ``procurement.claim.resolved`` (finance/качество подпишутся).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent

pytestmark = pytest.mark.asyncio


async def _claim_events(session):
    return [
        e for e in (await session.execute(select(OutboxEvent))).scalars().all()
        if e.event_type == "procurement.claim.resolved"
    ]


async def test_manual_claim_create(api):
    r = await api.post(
        "/procurement/claims",
        json={
            "supplier_id": 5,
            "item": "АКБ 48V",
            "claim_type": "недопоставка",
            "qty_affected": 12,
            "amount_byn": 3400,
            "reason": "Пришло 88 из 100",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "open" and body["source"] == "manual"
    assert body["claim_type"] == "недопоставка" and body["qty_affected"] == 12
    assert body["amount_byn"] == 3400.0
    assert body["supplier_id"] == 5


async def test_resolve_emits_event(api, session):
    claim = (
        await api.post(
            "/procurement/claims",
            json={"supplier_id": 5, "claim_type": "брак", "amount_byn": 500},
        )
    ).json()
    r = await api.patch(
        f"/procurement/claims/{claim['id']}",
        json={"status": "resolved", "resolution": "Поставщик компенсировал 500 BYN"},
    )
    assert r.status_code == 200
    assert r.json()["resolution"] == "Поставщик компенсировал 500 BYN"

    events = await _claim_events(session)
    assert len(events) == 1
    p = events[0].payload
    assert p["claim_id"] == claim["id"] and p["supplier_id"] == 5
    assert p["claim_type"] == "брак" and p["amount_byn"] == "500.00"
    assert p["status"] == "resolved"


async def test_resolve_enriches_order_id(api, session):
    """P6: претензия с order_code → resolved → payload claim.resolved содержит order_id (резолв номера)."""
    order = (await api.post(
        "/procurement/orders",
        json={"supplier_id": 5, "lines": [{"sku_code": "A", "qty": 1, "goods_value_byn": 100}]},
    )).json()
    claim = (await api.post(
        "/procurement/claims",
        json={"supplier_id": 5, "claim_type": "брак", "amount_byn": 500, "order_code": order["number"]},
    )).json()
    await api.patch(f"/procurement/claims/{claim['id']}", json={"status": "resolved"})

    events = await _claim_events(session)
    assert len(events) == 1
    assert events[0].payload["order_id"] == order["id"]


async def test_resolve_order_id_none_without_order_code(api, session):
    """Без order_code → order_id=None, событие не падает (существующие поля не меняются)."""
    claim = (await api.post(
        "/procurement/claims", json={"supplier_id": 5, "claim_type": "брак", "amount_byn": 100}
    )).json()
    await api.patch(f"/procurement/claims/{claim['id']}", json={"status": "resolved"})
    events = await _claim_events(session)
    assert len(events) == 1
    assert events[0].payload["order_id"] is None


async def test_invalid_claim_status_rejected(api):
    """Неизвестный статус претензии → 422 (закрытый набор, не свободная строка)."""
    claim = (await api.post("/procurement/claims", json={"supplier_id": 1, "claim_type": "брак"})).json()
    r = await api.patch(f"/procurement/claims/{claim['id']}", json={"status": "closed"})
    assert r.status_code == 422


async def test_resolve_event_not_double_emitted(api, session):
    """Повторный PATCH уже закрытой претензии не эмитит событие второй раз."""
    claim = (await api.post("/procurement/claims", json={"supplier_id": 1, "claim_type": "срок"})).json()
    await api.patch(f"/procurement/claims/{claim['id']}", json={"status": "rejected"})
    await api.patch(f"/procurement/claims/{claim['id']}", json={"resolution": "уточнение"})
    assert len(await _claim_events(session)) == 1
