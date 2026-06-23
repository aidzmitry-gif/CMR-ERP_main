"""Тесты претензий поставщикам: автосоздание из брака производства (production.scrap) + API.

Замыкание цикла ОТК → закупки: брак на сборке публикует ``production.scrap`` в outbox,
relay доставляет событие подписчику закупок, тот открывает претензию поставщику.
Фоновый relay в тестах не крутится — гоняем ``relay_once`` на той же in-memory сессии.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.services.eventbus import EventContext

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def claims_app(session):
    """Клиент + core, привязанные к тестовой сессии (для ручного relay подписчика)."""
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    # Дефолт-роль: после fail-closed (P0-1) запрос без роли — «Гость» (403 на модули).
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-User-Roles": "director"}
    ) as client:
        yield client, app.state.core


async def _scrap(client, **fields):
    payload = {"decision": "scrap", "product": "АКБ 48V 100Ah", "order_code": "№250"}
    payload.update(fields)
    return await client.post("/production/qc/decisions", json=payload)


async def _relay(core, session):
    await core.event_bus.relay_once(session, EventContext(session, core.services))


async def test_scrap_creates_claim(claims_app, session):
    client, core = claims_app
    r = await _scrap(client, reason="Непропай БМС")
    assert r.status_code == 201

    await _relay(core, session)

    claims = (await client.get("/procurement/claims")).json()
    assert len(claims) == 1
    c = claims[0]
    assert c["item"] == "АКБ 48V 100Ah"
    assert c["reason"] == "Непропай БМС"
    assert c["order_code"] == "№250"
    assert c["status"] == "open"
    assert c["source"] == "production"
    assert c["supplier"] == ""  # поставщик неизвестен — проставит закупщик
    assert c["entity_ref"].startswith("production:qc:")


async def test_accept_creates_no_claim(claims_app, session):
    client, core = claims_app
    await _scrap(client, decision="accept")  # приёмка, не брак
    await _relay(core, session)
    assert (await client.get("/procurement/claims")).json() == []


async def test_subscription_registered(claims_app):
    _, core = claims_app
    handlers = core.event_bus._handlers.get("production.scrap", [])
    assert any(h.__name__ == "on_production_scrap" for h in handlers)


async def test_claims_empty(claims_app):
    client, _ = claims_app
    assert (await client.get("/procurement/claims")).json() == []


async def test_patch_claim_assign_supplier(claims_app, session):
    client, core = claims_app
    await _scrap(client, reason="Скол корпуса")
    await _relay(core, session)
    claim_id = (await client.get("/procurement/claims")).json()[0]["id"]

    r = await client.patch(
        f"/procurement/claims/{claim_id}",
        json={"supplier": "ООО Поставщик", "status": "resolved"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["supplier"] == "ООО Поставщик"
    assert body["status"] == "resolved"
    assert body["item"] == "АКБ 48V 100Ah"  # прочие поля не затёрты


async def test_patch_claim_404(claims_app):
    client, _ = claims_app
    r = await client.patch("/procurement/claims/999", json={"status": "resolved"})
    assert r.status_code == 404


async def test_claims_newest_first(claims_app, session):
    client, core = claims_app
    await _scrap(client, order_code="№1", reason="брак 1")
    await _scrap(client, order_code="№2", reason="брак 2")
    await _relay(core, session)
    claims = (await client.get("/procurement/claims")).json()
    assert len(claims) == 2
    assert claims[0]["order_code"] == "№2"  # последний — первым
