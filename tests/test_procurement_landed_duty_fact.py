"""ORACLE (координатор): worker must make this pass; do not weaken the assertion.

Пошлина ТН ВЭД в ФАКТИЧЕСКОЙ (``actual``) себестоимости при приёмке заказа (``_fixate_landed_cost``)
уже применяется корректно — bug из ``task_fc401241`` в ЭТОМ пути закрыт (см. коммит
``feat(zak): пошлина ТН ВЭД в факт landed на приёмке (круг 4 B2)`` в modules/procurement).

НО: ``GET /procurement/orders/{id}/landed-preview`` — предпросмотр landed cost ДО приёмки
(редактор машины, `routes.py::landed_preview`) — вызывает `_order_allocation()` напрямую и
НЕ применяет пошлину вообще, хотя его docstring утверждает «тот же движок, что и на приёмке».
Это и есть реальный план↔факт разрыв: пользователь видит в превью цифру БЕЗ пошлины, а после
факта приёмки (`_fixate_landed_cost`) себестоимость «прыгает» вверх на величину пошлины —
план и факт расходятся.

Тест конструирует ПЛАН (landed-preview заказа с непустой пошлиной по SKU) и ФАКТ (тот же заказ
после приёмки) и проверяет, что они сходятся (±0.01 BYN). Падает на текущем коде: preview = 100.00
(без пошлины), факт = 125.00 (с пошлиной 25%).
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

import core.services.sku_master as sku_master_mod
from modules.procurement.landed_cost import LandedCostService

pytestmark = pytest.mark.asyncio

SVC = LandedCostService()


async def _owned_order(api, payload):
    api.headers["X-User"] = "procurement-owner-test"
    created = await api.post("/procurement/orders", json=payload)
    assert created.status_code == 201, created.text
    books = (await api.get("/accounting/organizations")).json()
    if not books:
        company = await api.post("/accounting/organizations", json={"name": "Synthetic procurement company", "unp": "999999994"})
        assert company.status_code == 201, company.text
        books = [company.json()]
    org = books[0]["id"]
    assigned = await api.post(f"/procurement/organizations/{org}/purchase-ownership", json={
        "kind": "order", "source_id": created.json()["id"], "evidence": "Explicit synthetic plan/fact fixture"
    })
    assert assigned.status_code == 201, assigned.text
    api.headers["X-Expected-Organization"] = str(org)
    api.headers["X-Expected-Principal"] = "procurement-owner-test"
    return created.json()


def _patch_duty(monkeypatch, pct):
    """Подменить фасад ядра фиксированной пошлиной (как в test_procurement_reference_recompute.py)."""

    async def fake_batch(session, sku_codes, on_date=None):
        return {code: {"duty_pct": pct} for code in sku_codes}

    async def fake_single(session, sku_code, on_date=None):
        return {"duty_pct": pct}

    monkeypatch.setattr(sku_master_mod, "landed_inputs_batch", fake_batch)
    monkeypatch.setattr(sku_master_mod, "landed_inputs", fake_single)


async def test_landed_plan_fact_reconcile(api, session, monkeypatch):
    """landed-preview (план ДО приёмки) должен сходиться с actual LandedCost (факт ПОСЛЕ приёмки)."""
    _patch_duty(monkeypatch, 25.0)

    payload = {
        "supplier": "Поставщик",
        "lines": [{"sku_code": "RECON-1", "qty": 10, "goods_value_byn": 1000}],
    }
    order = await _owned_order(api, payload)

    # ПЛАН: предпросмотр landed cost ДО приёмки (то, что видит закупщик в редакторе машины)
    org = api.headers["X-Expected-Organization"]
    preview_response = await api.get(f"/procurement/organizations/{org}/orders/{order['id']}/landed-preview")
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    plan_unit = Decimal(str(preview["lines"][0]["unit_landed_cost_byn"]))

    # ФАКТ: реальная приёмка заказа — фиксация actual landed cost
    received = await api.post(f"/procurement/organizations/{org}/orders/{order['id']}/edit-commands", json={
        "version": 1, "request_key": str(uuid4()), "order_id": order["id"],
        "action": "status", "payload": {"status": "received"}
    })
    assert received.status_code == 200, received.text

    fact = await SVC.last_landed_cost(session, "RECON-1")
    assert fact is not None
    fact_unit = fact["unit_landed_cost_byn"]

    # 1000/10 = 100 без пошлины; ×1.25 = 125 с пошлиной — план должен УЖЕ нести пошлину,
    # чтобы не расходиться с фактом после приёмки.
    assert abs(plan_unit - fact_unit) <= Decimal("0.01"), (
        f"план↔факт разошлись: preview(план)={plan_unit} != actual(факт)={fact_unit} "
        "— пошлина не учтена в landed-preview"
    )
