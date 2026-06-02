"""Тесты модуля Integrations (чтение из 1С)."""


async def test_1c_sync(session, api):
    from sqlalchemy import select

    from core.domain.models import Counterparty, OutboxEvent

    r = await api.post("/integrations/1c/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["stock"] == 3
    assert body["counterparties"] == 3

    stock = (await api.get("/integrations/1c/stock")).json()
    assert len(stock) == 3
    assert any(s["sku_code"] == "AKB-60" for s in stock)

    counterparties = (await session.execute(select(Counterparty))).scalars().all()
    assert len(counterparties) >= 3

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "integration.1c.synced" in types


async def test_two_modules_loaded(api):
    data = (await api.get("/system/modules")).json()
    assert "sales" in data["loaded_modules"]
    assert "integrations" in data["loaded_modules"]
