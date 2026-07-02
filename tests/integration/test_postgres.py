"""Integration-тесты на реальном PostgreSQL (вершина «integration» пирамиды).

Покрывают то, что SQLite-тесты не трогают: реальный ``get_session``, подключение к
Postgres (``db.connect``), схемы ``sales.*`` из миграций, фоновый relay в lifespan.
"""
import asyncio

from httpx import ASGITransport, AsyncClient

from config.settings import get_settings


async def test_health_and_modules_on_postgres(pg_app):
    assert (await pg_app.get("/health")).json()["status"] == "ok"
    mods = (await pg_app.get("/system/modules")).json()
    assert "sales" in mods["loaded_modules"]
    assert "integrations" in mods["loaded_modules"]


async def test_deal_crud_on_postgres(pg_app):
    r = await pg_app.post(
        "/sales/deals",
        json={"number": "PG-DEAL-1", "title": "Интеграция", "counterparty": "ООО ПГ", "amount": 1000},
    )
    assert r.status_code == 201
    deal_id = r.json()["id"]

    got = await pg_app.get(f"/sales/deals/{deal_id}")
    assert got.status_code == 200 and got.json()["counterparty"] == "ООО ПГ"

    board = await pg_app.get("/sales/board")
    assert board.status_code == 200
    assert any(s["id"] == "new" for s in board.json()["stages"])

    # доменное событие действительно записано в outbox реальной БД
    events = (await pg_app.get("/system/events")).json()
    assert any(e["event_type"] == "sales.deal.created" for e in events)


async def test_lead_lifecycle_on_postgres(pg_app):
    lead = (
        await pg_app.post(
            "/leads",
            json={"source": "site", "company": "ООО ПГ-Лид", "region": "Минск", "product": "лист"},
        )
    ).json()
    await pg_app.post(f"/leads/{lead['id']}/qualify")
    routed = (await pg_app.post(f"/leads/{lead['id']}/route")).json()
    assert routed["assigned_to"]

    conv = await pg_app.post(f"/leads/{lead['id']}/convert")
    assert conv.status_code == 201
    assert conv.json()["status"] == "converted"

    # convert лишь публикует leads.lead.converted; сделку sales создаёт по подписке через
    # фоновый relay, а pg_app (ASGITransport) lifespan не крутит. Полный поток лид→сделка
    # проверяет SQLite-тест test_lead_convert_creates_deal (ручной relay). Здесь — что
    # событие реально записано в outbox реальной БД.
    events = (await pg_app.get("/system/events")).json()
    assert any(e["event_type"] == "leads.lead.converted" for e in events)


async def test_lifespan_background_relay_on_postgres(postgres_url, monkeypatch):
    """Полный жизненный цикл с фоновым relay: событие из outbox проецируется в audit."""
    monkeypatch.setenv("AIOS_DATABASE_URL", postgres_url)
    get_settings.cache_clear()
    from core.runtime.app import create_app

    app = create_app()
    try:
        async with app.router.lifespan_context(app):
            # fail-closed RBAC: POST /sales/deals без роли → 403; шлём супер-роль (как pg_app/api).
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={"X-User-Roles": "director"},
            ) as client:
                await client.post(
                    "/sales/deals",
                    json={"number": "PG-RELAY-1", "title": "Relay", "counterparty": "c"},
                )
                # фоновый цикл (тик раз в ~2с) доставляет событие и пишет проекцию в audit
                projected = False
                for _ in range(15):
                    await asyncio.sleep(1)
                    audit = (await client.get("/system/audit")).json()
                    if any(a["action"] == "sales.deal.created" for a in audit):
                        projected = True
                        break
                assert projected, "фоновый relay не спроецировал событие в audit"
    finally:
        get_settings.cache_clear()
