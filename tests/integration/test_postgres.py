"""Integration-тесты на реальном PostgreSQL (вершина «integration» пирамиды).

Покрывают то, что SQLite-тесты не трогают: реальный ``get_session``, подключение к
Postgres (``db.connect``), схемы ``sales.*`` из миграций, фоновый relay в lifespan.
"""
import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.settings import get_settings
from core.domain.models import AuditLog, OutboxEvent
from core.services.eventbus import OutboxEventBus
from modules.finance.models import BankTransaction
from modules.integrations.models import StockItem
from modules.integrations.stock import StockService


async def test_health_and_modules_on_postgres(pg_app):
    assert (await pg_app.get("/health")).json()["status"] == "ok"
    mods = (await pg_app.get("/system/modules")).json()
    assert "sales" in mods["loaded_modules"]
    assert "integrations" in mods["loaded_modules"]


async def test_postgres_schema_is_migrated_to_declared_head(postgres_url):
    """The real database must be at Alembic head and retain the partial-unique index."""
    engine = create_async_engine(postgres_url, future=True)
    try:
        async with engine.connect() as conn:
            versions = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
            indexes = (
                await conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' AND indexname = 'uq_ref_vat_rate_open'"
                    )
                )
            ).scalars().all()
        assert versions == ["0110"]
        assert indexes == ["uq_ref_vat_rate_open"]
    finally:
        await engine.dispose()


async def test_sales_route_is_fail_closed_without_role(pg_app):
    """A real Postgres-backed request without a role cannot read the sales board."""
    denied = await pg_app.get("/sales/board", headers={"X-User-Roles": "guest"})
    assert denied.status_code == 403


async def test_outbox_relay_concurrency_delivers_an_event_once(postgres_url):
    """Two real Postgres relays must claim disjoint rows through FOR UPDATE SKIP LOCKED."""
    engine = create_async_engine(postgres_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    marker = uuid4().hex
    try:
        async with factory() as seed:
            seed.add(
                OutboxEvent(
                    event_type="qa.concurrent.relay",
                    payload={"entity_ref": f"qa:{marker}", "marker": marker},
                )
            )
            await seed.commit()

        async def relay_once() -> int:
            async with factory() as session:
                return await OutboxEventBus().relay_once(session)

        delivered = await asyncio.gather(relay_once(), relay_once())
        assert sorted(delivered) == [0, 1]

        async with factory() as check:
            event = (
                await check.execute(
                    select(OutboxEvent).where(OutboxEvent.payload["marker"].as_string() == marker)
                )
            ).scalar_one()
            audit_count = (
                await check.execute(
                    select(AuditLog).where(AuditLog.entity_ref == f"qa:{marker}")
                )
            ).scalars().all()
        assert event.processed_at is not None
        assert len(audit_count) == 1
    finally:
        async with factory() as cleanup:
            await cleanup.execute(
                delete(OutboxEvent).where(OutboxEvent.payload["marker"].as_string() == marker)
            )
            await cleanup.execute(delete(AuditLog).where(AuditLog.entity_ref == f"qa:{marker}"))
            await cleanup.commit()
        await engine.dispose()


async def test_stock_reservation_cannot_overcommit_under_concurrency(postgres_url):
    """Concurrent real reservations must never confirm more than available stock."""
    engine = create_async_engine(postgres_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    marker = f"QA-STOCK-{uuid4().hex}"
    try:
        async with factory() as seed:
            seed.add(
                StockItem(
                    sku_code=marker,
                    warehouse="QA",
                    qty_available=Decimal("5"),
                    qty_reserved=Decimal("0"),
                )
            )
            await seed.commit()

        async def reserve_once() -> list[dict]:
            async with factory() as session:
                result = await StockService().reserve(
                    session, [{"sku_code": marker, "qty": "4"}]
                )
                await session.commit()
                return result

        results = await asyncio.gather(reserve_once(), reserve_once())
        confirmed = sum(
            (Decimal(str(item["qty"])) for result in results for item in result),
            Decimal("0"),
        )
        assert confirmed <= Decimal("5")
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(StockItem).where(StockItem.sku_code == marker))
            await cleanup.commit()
        await engine.dispose()


async def test_bank_transaction_external_id_is_unique(postgres_url):
    """The real finance ledger rejects a duplicate bank operation id."""
    engine = create_async_engine(postgres_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    marker = f"QA-BANK-{uuid4().hex}"
    try:
        async with factory() as session:
            session.add(BankTransaction(ext_id=marker, amount=Decimal("10")))
            await session.commit()
            session.add(BankTransaction(ext_id=marker, amount=Decimal("10")))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(BankTransaction).where(BankTransaction.ext_id == marker))
            await cleanup.commit()
        await engine.dispose()


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


async def test_microchips_and_email_intake_on_postgres(postgres_url, monkeypatch):
    """Публичный intake: token → relay → PostgreSQL, включая dedupe сайта."""
    marker = uuid4().hex[:10]
    phone = f"+37529{str(int(marker, 16)).zfill(10)[-7:]}"
    email = f"mail-{marker}@client.example"
    token = f"intake-{marker}"
    monkeypatch.setenv("AIOS_DATABASE_URL", postgres_url)
    monkeypatch.setenv("AIOS_INTAKE_WEBHOOK_TOKEN", token)
    get_settings.cache_clear()
    from core.runtime.app import create_app

    app = create_app()
    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={"X-User-Roles": "director"},
            ) as client:
                rejected = await client.post(
                    "/integrations/web/lead?token=wrong", json={"phone": phone}
                )
                assert rejected.status_code == 403

                payload = {
                    "company": f"ООО Microchips {marker}",
                    "phone": phone,
                    "product": "Аккумулятор",
                    "message": "Первая заявка",
                    "landing_url": "https://microchips.by/?utm_source=google&utm_campaign=battery",
                }
                first = await client.post(
                    f"/integrations/web/lead?token={token}", json=payload
                )
                repeat = await client.post(
                    f"/integrations/web/lead?token={token}",
                    json={**payload, "message": "Повторная заявка"},
                )
                inbound = await client.post(
                    f"/integrations/email/inbound?token={token}",
                    json={
                        "from": f"Закупщик <{email}>",
                        "subject": "Запрос с почты",
                        "text": "Нужна цена",
                    },
                )
                assert first.status_code == repeat.status_code == inbound.status_code == 200

                matched = []
                for _ in range(15):
                    await asyncio.sleep(1)
                    rows = (await client.get("/leads")).json()
                    matched = [
                        row for row in rows if row.get("phone") == phone or row.get("email") == email
                    ]
                    if len(matched) == 2:
                        break
                assert len(matched) == 2
                site = next(row for row in matched if row["source"] == "site")
                mail = next(row for row in matched if row["source"] == "email")
                assert "Первая заявка" in site["message"]
                assert "Повторная заявка" in site["message"]
                assert site["utm_source"] == "google"
                assert mail["email"] == email
    finally:
        get_settings.cache_clear()
