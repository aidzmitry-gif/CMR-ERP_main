"""Тесты спецификаций · BOM: состав изделия, обеспеченность, статусы утверждения."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

PRODUCT = "Аккумулятор LiFePO4 RADIAN LF12200-02 12V 200Ah"


async def _bom(api, product=PRODUCT):
    return (await api.post("/production/boms", json={"product": product})).json()


async def _item(api, bom_id, **kw):
    payload = {"component": "Элемент", "norm_qty": 1.0, "stock": 10.0, "reserved": 0.0}
    payload.update(kw)
    return (await api.post(f"/production/boms/{bom_id}/items", json=payload)).json()


# ===== Спецификация: жизненный цикл =====


async def test_create_bom_draft(api):
    body = await _bom(api)
    assert body["status"] == "draft"
    assert body["version"] == "v1"
    assert body["item_count"] == 0
    assert body["coverage"] == 100  # пустой состав — 100%


async def test_list_boms_aggregates(api):
    bom_id = (await _bom(api))["id"]
    await _item(api, bom_id, component="A", norm_qty=2.0, stock=5.0)
    await _item(api, bom_id, component="B", norm_qty=2.0, stock=1.0)  # short
    rows = (await api.get("/production/boms")).json()
    assert rows[0]["item_count"] == 2
    assert rows[0]["coverage"] == 50  # 1 из 2 обеспечена


async def test_approve_bom(api):
    bom_id = (await _bom(api))["id"]
    await _item(api, bom_id)
    r = await api.post(f"/production/boms/{bom_id}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


async def test_approve_empty_bom_conflict(api):
    bom_id = (await _bom(api))["id"]
    r = await api.post(f"/production/boms/{bom_id}/approve")
    assert r.status_code == 409


async def test_edit_item_reverts_to_draft(api):
    bom_id = (await _bom(api))["id"]
    item_id = (await _item(api, bom_id))["id"]
    await api.post(f"/production/boms/{bom_id}/approve")
    assert (await api.get(f"/production/boms/{bom_id}")).json()["status"] == "approved"
    await api.patch(f"/production/bom-items/{item_id}", json={"norm_qty": 3.0})
    assert (await api.get(f"/production/boms/{bom_id}")).json()["status"] == "draft"


async def test_add_item_reverts_to_draft(api):
    bom_id = (await _bom(api))["id"]
    await _item(api, bom_id)
    await api.post(f"/production/boms/{bom_id}/approve")
    await _item(api, bom_id, component="Ещё")
    assert (await api.get(f"/production/boms/{bom_id}")).json()["status"] == "draft"


async def test_delete_item_reverts_and_removes(api):
    bom_id = (await _bom(api))["id"]
    item_id = (await _item(api, bom_id))["id"]
    await _item(api, bom_id, component="Останется")
    await api.post(f"/production/boms/{bom_id}/approve")
    assert (await api.delete(f"/production/bom-items/{item_id}")).status_code == 204
    detail = (await api.get(f"/production/boms/{bom_id}")).json()
    assert detail["status"] == "draft"
    assert detail["item_count"] == 1


async def test_delete_bom_cascades_items(api):
    bom_id = (await _bom(api))["id"]
    await _item(api, bom_id)
    assert (await api.delete(f"/production/boms/{bom_id}")).status_code == 204
    assert (await api.get(f"/production/boms/{bom_id}")).status_code == 404


# ===== Обеспеченность позиций =====


async def test_item_status_ok_and_short(api):
    bom_id = (await _bom(api))["id"]
    await _item(api, bom_id, component="Хватает", norm_qty=2.0, stock=10.0, reserved=3.0)  # 7≥2 ok
    await _item(api, bom_id, component="Дефицит", norm_qty=5.0, stock=4.0, reserved=0.0)   # 4<5 short
    items = (await api.get(f"/production/boms/{bom_id}")).json()["items"]
    by_name = {i["component"]: i["status"] for i in items}
    assert by_name == {"Хватает": "ok", "Дефицит": "short"}


async def test_coverage_full(api):
    bom_id = (await _bom(api))["id"]
    await _item(api, bom_id, norm_qty=1.0, stock=10.0)
    await _item(api, bom_id, norm_qty=1.0, stock=10.0)
    assert (await api.get(f"/production/boms/{bom_id}")).json()["coverage"] == 100


async def test_meta_edit_keeps_approved(api):
    bom_id = (await _bom(api))["id"]
    await _item(api, bom_id)
    await api.post(f"/production/boms/{bom_id}/approve")
    await api.patch(f"/production/boms/{bom_id}", json={"note": "ревизия чертежа"})
    assert (await api.get(f"/production/boms/{bom_id}")).json()["status"] == "approved"


async def test_bom_404(api):
    assert (await api.get("/production/boms/999")).status_code == 404
    assert (await api.post("/production/boms/999/items", json={"component": "X"})).status_code == 404
    assert (await api.patch("/production/bom-items/999", json={"norm_qty": 1.0})).status_code == 404
    assert (await api.delete("/production/bom-items/999")).status_code == 404
