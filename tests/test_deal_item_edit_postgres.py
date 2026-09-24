"""Actual PostgreSQL row lock and stale-token race for a deal's product line."""

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base
from core.domain.models import AuditLog, Sku
from core.runtime.app import create_app
from core.runtime.deps import get_session
from modules.sales.models import Deal, DealItem

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def postgres_item_app():
    raw_url = os.getenv("CRM_DOCUMENT_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set CRM_DOCUMENT_TEST_POSTGRES_URL for an isolated PostgreSQL race")
    url = make_url(raw_url)
    assert url.get_backend_name() == "postgresql"
    name = "crm_acc_item_" + uuid4().hex[:12]
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    engine = None
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_async_engine(url.set(database=name))
        app = create_app()
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            for schema in sorted({table.schema for table in Base.metadata.tables.values() if table.schema}):
                await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def own_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = own_session
        async with factory() as session:
            deal = Deal(number="PG-ITEM-1", title="Sale", counterparty="Buyer")
            sku = Sku(code="PG-ITEM-SKU-1", title="Product", unit="pcs")
            session.add_all([deal, sku])
            await session.flush()
            item = DealItem(deal_id=deal.id, sku_id=sku.id, qty=2, unit_price=10)
            session.add(item)
            await session.commit()
            item_id, deal_id = item.id, deal.id

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                               headers={"X-User-Roles": "director"}) as api:
            yield api, factory, item_id, deal_id
    finally:
        if engine is not None:
            await engine.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


async def test_simultaneous_item_edits_only_one_wins(postgres_item_app):
    api, factory, item_id, deal_id = postgres_item_app
    listed = (await api.get(f"/sales/deals/{deal_id}/items")).json()
    token = listed[0]["edit_token"]
    responses = await asyncio.gather(*(
        api.patch(f"/sales/deal-items/{item_id}", json={
            "qty": quantity, "expected_edit_token": token,
        }) for quantity in (3, 4)
    ))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json()["qty"] for response in responses if response.status_code == 200)
    async with factory() as session:
        item = await session.get(DealItem, item_id)
        assert float(item.qty) == winner
        assert await session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "sales.deal.item_changed",
            AuditLog.entity_ref == f"deal:{deal_id}")) == 1
