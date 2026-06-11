"""Тесты модуля Production: справочник норм и нормо-часы на нарядах."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

PRODUCT = "Аккумулятор LiFePO4 RADIAN 12V 100Ah"


# ===== Нормы: жизненный цикл статусов =====


async def test_norm_create_pending(api):
    r = await api.post("/production/norms", json={"title": PRODUCT, "nh": 5.0})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["nh"] == 5.0
    assert body["kind"] == "product"


async def test_norm_create_without_nh_is_none(api):
    r = await api.post("/production/norms", json={"title": "Без нормы"})
    assert r.status_code == 201
    assert r.json()["status"] == "none"


async def test_norm_approve(api):
    norm_id = (await api.post("/production/norms", json={"title": PRODUCT, "nh": 5.0})).json()["id"]
    r = await api.post(f"/production/norms/{norm_id}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


async def test_norm_approve_without_nh_conflict(api):
    norm_id = (await api.post("/production/norms", json={"title": "Пустая"})).json()["id"]
    r = await api.post(f"/production/norms/{norm_id}/approve")
    assert r.status_code == 409


async def test_norm_edit_nh_returns_to_pending(api):
    norm_id = (await api.post("/production/norms", json={"title": PRODUCT, "nh": 5.0})).json()["id"]
    await api.post(f"/production/norms/{norm_id}/approve")
    r = await api.patch(f"/production/norms/{norm_id}", json={"nh": 6.5})
    assert r.json()["status"] == "pending"
    assert r.json()["nh"] == 6.5


async def test_norm_edit_note_keeps_status(api):
    norm_id = (await api.post("/production/norms", json={"title": PRODUCT, "nh": 5.0})).json()["id"]
    await api.post(f"/production/norms/{norm_id}/approve")
    r = await api.patch(f"/production/norms/{norm_id}", json={"note": "уточнение состава"})
    assert r.json()["status"] == "approved"


async def test_norm_list_filter_by_kind(api):
    await api.post("/production/norms", json={"title": "Изделие", "nh": 1.0})
    await api.post("/production/norms", json={"title": "Сварка", "kind": "operation", "nh": 0.4})
    products = (await api.get("/production/norms", params={"kind": "product"})).json()
    operations = (await api.get("/production/norms", params={"kind": "operation"})).json()
    assert [n["title"] for n in products] == ["Изделие"]
    assert [n["title"] for n in operations] == ["Сварка"]


async def test_norm_delete(api):
    norm_id = (await api.post("/production/norms", json={"title": "Временная", "nh": 1.0})).json()["id"]
    assert (await api.delete(f"/production/norms/{norm_id}")).status_code == 204
    assert (await api.get("/production/norms")).json() == []


async def test_norm_missing_404(api):
    assert (await api.patch("/production/norms/999", json={"nh": 1.0})).status_code == 404
    assert (await api.post("/production/norms/999/approve")).status_code == 404
    assert (await api.delete("/production/norms/999")).status_code == 404


# ===== Наряды: нормо-часы =====


async def test_order_explicit_nh(api):
    r = await api.post(
        "/production/orders", json={"product": PRODUCT, "qty": 2, "nh_per_unit": 5.0}
    )
    assert r.status_code == 201
    assert r.json()["nh_per_unit"] == 5.0


async def test_order_nh_from_approved_norm(api):
    norm_id = (await api.post("/production/norms", json={"title": PRODUCT, "nh": 5.0})).json()["id"]
    await api.post(f"/production/norms/{norm_id}/approve")
    r = await api.post("/production/orders", json={"product": PRODUCT, "qty": 2})
    assert r.json()["nh_per_unit"] == 5.0


async def test_order_pending_norm_not_used(api):
    await api.post("/production/norms", json={"title": PRODUCT, "nh": 5.0})  # не утверждена
    r = await api.post("/production/orders", json={"product": PRODUCT})
    assert r.json()["nh_per_unit"] == 0.0


async def test_board_card_has_nh_tag(api):
    await api.post("/production/orders", json={"product": PRODUCT, "qty": 2, "nh_per_unit": 5.0})
    board = (await api.get("/production/board")).json()
    queue = next(c for c in board["stages"] if c["id"] == "queue")
    assert "10 н.ч" in queue["cards"][0]["tags"]


async def test_board_card_nh_russian_format(api):
    await api.post("/production/orders", json={"product": PRODUCT, "qty": 1, "nh_per_unit": 7.5})
    board = (await api.get("/production/board")).json()
    queue = next(c for c in board["stages"] if c["id"] == "queue")
    assert "7,5 н.ч" in queue["cards"][0]["tags"]


async def test_done_sets_made_qty(api):
    order_id = (
        await api.post("/production/orders", json={"product": PRODUCT, "qty": 3})
    ).json()["id"]
    r = await api.patch(f"/production/orders/{order_id}", json={"stage": "done"})
    body = r.json()
    assert body["progress"] == 100
    assert body["made_qty"] == 3
