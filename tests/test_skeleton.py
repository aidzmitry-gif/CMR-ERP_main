"""Дымовые тесты каркаса: модуль подключается, роуты живые, событие летит."""
from fastapi.testclient import TestClient

from core.runtime.app import create_app

client = TestClient(create_app())


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_sales_module_loaded():
    r = client.get("/system/modules")
    assert r.status_code == 200
    data = r.json()
    assert "sales" in data["loaded_modules"]
    assert any(rt["prefix"] == "/sales" for rt in data["routers"])
    assert any(e["event_type"] == "sales.deal.created" for e in data["events"])
    assert any(w["name"] == "DealApproval" for w in data["workflows"])
    assert "sales.deal.read" in data["permissions"]


def test_sales_ping():
    r = client.get("/sales/ping")
    assert r.status_code == 200
    assert r.json()["module"] == "sales"


def test_create_deal_publishes_event():
    r = client.post(
        "/sales/deals",
        json={"number": "CRM-TEST-1", "title": "Тест", "counterparty": "ООО Тест"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["number"] == "CRM-TEST-1"
    assert body["id"] is not None
