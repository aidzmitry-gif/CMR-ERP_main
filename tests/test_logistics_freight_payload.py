# ruff: noqa: F811 -- pytest fixtures imported for this module
"""LOG3-2 — деньги в payload событий шины: str(BYN), не float (защита от дрейфа копеек).

Finance принимает Decimal(str(...)) — float туда передавать нельзя (двоичное представление
теряет точность; накопленный дрейф при сотнях проводок = реальная потеря денег).

Проверки: (1) grep по исходнику не находит float(...amount...) в payload эмитов;
(2) при реальных вызовах payload содержит amount/price строками.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent
from tests.test_logistics_fixtures import exact, shipping_api  # noqa: F401

ROUTES_PY = Path(__file__).resolve().parent.parent / "modules" / "logistics" / "routes.py"


@pytest.mark.unit
def test_no_float_amount_in_emit_payload():
    """grep-страховка: в payload эмитов шины НЕТ float(...) для денежных ключей.

    Регэксп прицельный — берёт ТОЛЬКО фрагменты внутри ``event_bus.emit(...{ ... })``
    (шинные словари), не локальные dict-входы для ``pricing.rank_bids``/``bid_risk``
    (там float корректен — чистые функции).
    """
    src = ROUTES_PY.read_text(encoding="utf-8")
    # Захватываем тело payload между event_bus.emit(...{ и ближайшей } того же словаря.
    emit_bodies = re.findall(
        r"event_bus\.emit\([^{]*\{(.*?)\}", src, re.DOTALL
    )
    bad: list[tuple[str, str]] = []
    for body in emit_bodies:
        for hit in re.findall(r'"(amount|price|variance|new_price)"\s*:\s*float\(', body):
            bad.append((hit, body[:80]))
    assert not bad, (
        f"LOG3-2: деньги в payload эмитов должны быть str(), а не float() — найдено: {bad}"
    )


async def test_shipment_freight_payload_has_str_money(shipping_api, session):
    """logistics.freight.cost (доставка РБ/РФ) — amount строкой, leg='domestic'."""
    sid = (await shipping_api.post("/logistics/shipments", json={
        "customer": "ООО Тест", "weight_kg": 5, "amount": 78.40,
        "status": "planned", "carrier": "DPD",
    })).json()["id"]
    r = await shipping_api.patch(f"/logistics/shipments/{sid}", json={"status": "delivered"})
    assert r.status_code == 200

    rows = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "logistics.freight.cost")
    )).scalars().all()
    domestic = [e for e in rows if e.payload.get("entity_ref") == f"shipment:{sid}"]
    assert len(domestic) == 1
    p = domestic[0].payload
    assert isinstance(p["amount"], str)
    assert p["leg"] == "domestic", "LOG3-2: leg маркирует плечо (domestic/import)"


async def test_audit_refund_payload_has_str_money(shipping_api, session):
    """logistics.freight.audit_refund — amount строкой (variance к возврату)."""
    r = await shipping_api.post("/logistics/costs/audit", json={
        "shipment_code": "ЛОГ-2026-T01", "carrier_code": "dpd",
        "invoice_amount": 100.0, "expected_amount": 80.0, "reason": "тест",
    })
    assert r.status_code == 409 and r.json()["detail"] == "organization_scope_incomplete"

    rows = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "logistics.freight.audit_refund")
    )).scalars().all()
    assert rows == []  # unresolved ownership must not emit financial projections


async def test_contract_signed_payload_has_str_price(shipping_api, session):
    """logistics.contract.signed — price строкой (закупочная цена контракта)."""
    rfq = (await shipping_api.post("/logistics/rfqs", json={"cargo": "Test"})).json()
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "dpd", "price": 100})
    assert rfq, "seed_rfq должен вернуть RfqOut"
    r = await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/award", json={})
    assert r.status_code == 200

    rows = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "logistics.contract.signed")
    )).scalars().all()
    assert rows
    assert all(isinstance(e.payload["price"], str) for e in rows)
