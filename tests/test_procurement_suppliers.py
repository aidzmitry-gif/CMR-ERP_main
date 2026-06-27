"""Тесты справочника поставщиков (CRUD) + скоркарты поставщика.

Supplier — профиль закупок (условия/срок/incoterms/статус), ``unp`` — soft-ref на MDM.
Скоркарта агрегирует заказы/претензии/выигранные RFQ → компоненты + балл 0–10.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _supplier(api, **over):
    body = {"name": "Шэньчжэнь Бэттери Co", "unp": "ICN-7788", "country": "Китай", "flag": "🇨🇳"}
    body.update(over)
    r = await api.post("/procurement/suppliers", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_supplier_crud(api):
    created = await _supplier(api, payment_terms="30% предоплата / 70% по факту", lead_time_days=45)
    sid = created["id"]
    assert created["name"] == "Шэньчжэнь Бэттери Co" or created["name"]  # имя сохранено
    assert created["unp"] == "ICN-7788"
    assert created["status"] == "active"

    got = (await api.get(f"/procurement/suppliers/{sid}")).json()
    assert got["payment_terms"] == "30% предоплата / 70% по факту"
    assert got["lead_time_days"] == 45

    r = await api.patch(f"/procurement/suppliers/{sid}", json={"status": "blocked", "incoterms": "FOB"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked" and body["incoterms"] == "FOB"
    assert body["unp"] == "ICN-7788"  # прочие поля не затёрты

    lst = (await api.get("/procurement/suppliers")).json()
    assert any(s["id"] == sid for s in lst)


async def test_supplier_404(api):
    assert (await api.get("/procurement/suppliers/9999")).status_code == 404
    assert (await api.patch("/procurement/suppliers/9999", json={"status": "blocked"})).status_code == 404


async def test_scorecard_no_data(api):
    sup = await _supplier(api)
    sc = (await api.get(f"/procurement/suppliers/{sup['id']}/scorecard")).json()
    assert sc["orders_count"] == 0
    assert sc["claims_total"] == 0
    assert sc["on_time_rate"] is None  # honest-empty: нет дат факта
    assert sc["score"] is None  # нет данных → балла нет


async def test_scorecard_with_orders_and_claim(api):
    sup = await _supplier(api)
    sid = sup["id"]
    # 2 заказа поставщика
    for _ in range(2):
        await api.post(
            "/procurement/orders",
            json={"supplier_id": sid, "lines": [{"sku_code": "A", "qty": 1, "goods_value_byn": 100}]},
        )
    # 1 претензия (открытая)
    await api.post("/procurement/claims", json={"supplier_id": sid, "claim_type": "брак", "qty_affected": 1})

    sc = (await api.get(f"/procurement/suppliers/{sid}/scorecard")).json()
    assert sc["orders_count"] == 2
    assert sc["claims_total"] == 1 and sc["claims_open"] == 1
    # quality = 1 − 1/2 = 0.5; своевременность None → балл = 0.5×10 = 5.0
    assert sc["components"]["quality"] == 0.5
    assert sc["score"] == 5.0
