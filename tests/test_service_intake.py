"""Тесты модуля ServiceRequest: CRUD + фильтр + подписка sales.deal.won."""
from __future__ import annotations

import importlib
import os


async def test_list_requests_empty(api):
    """GET /service/requests → 200, пустой список."""
    r = await api.get("/service/requests")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_request(api):
    """POST /service/requests → 201, поля в ответе."""
    payload = {"title": "Тестовая заявка", "description": "Описание", "priority": "high"}
    r = await api.post("/service/requests", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Тестовая заявка"
    assert body["description"] == "Описание"
    assert body["priority"] == "high"
    assert body["status"] == "new"
    assert body["id"] > 0


async def test_get_request_by_id(api):
    """GET /service/requests/{id} → 200 с данными."""
    r = await api.post("/service/requests", json={"title": "Заявка А"})
    assert r.status_code == 201
    created = r.json()

    r2 = await api.get(f"/service/requests/{created['id']}")
    assert r2.status_code == 200
    assert r2.json()["id"] == created["id"]
    assert r2.json()["title"] == "Заявка А"


async def test_get_request_not_found(api):
    """GET /service/requests/999999 → 404."""
    r = await api.get("/service/requests/999999")
    assert r.status_code == 404


async def test_patch_request_status(api):
    """PATCH /service/requests/{id} → 200, status обновлён."""
    r = await api.post("/service/requests", json={"title": "Патч"})
    assert r.status_code == 201
    req_id = r.json()["id"]

    r2 = await api.patch(f"/service/requests/{req_id}", json={"status": "in_progress"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "in_progress"


async def test_filter_by_status(api):
    """GET /service/requests?status=new → только new."""
    await api.post("/service/requests", json={"title": "New 1"})
    r_done = await api.post("/service/requests", json={"title": "Done 1"})
    assert r_done.status_code == 201
    done_id = r_done.json()["id"]
    await api.patch(f"/service/requests/{done_id}", json={"status": "done"})

    r = await api.get("/service/requests?status=new")
    assert r.status_code == 200
    items = r.json()
    assert all(item["status"] == "new" for item in items)
    assert any(item["title"] == "New 1" for item in items)
    assert all(item["title"] != "Done 1" for item in items)


async def test_create_with_deal_id(api):
    """POST /service/requests с deal_id → поле сохраняется."""
    r = await api.post("/service/requests", json={"title": "По сделке", "deal_id": 42})
    assert r.status_code == 201
    assert r.json()["deal_id"] == 42


async def test_import_main():
    """import main не падает (smoke-тест зависимостей)."""
    os.environ.setdefault("AIOS_AUTH_MODE", "dev")
    os.environ.setdefault("AIOS_ENVIRONMENT", "dev")
    importlib.import_module("main")
