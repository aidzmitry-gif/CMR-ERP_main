"""Isolated PostgreSQL race for conflicting edits of one CRM document draft."""

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base
from core.runtime.app import create_app
from core.runtime.deps import get_session
from modules.sales.models import Deal, DealDocument

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def postgres_draft_app():
    raw_url = os.getenv("CRM_DOCUMENT_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set CRM_DOCUMENT_TEST_POSTGRES_URL for an isolated PostgreSQL race")
    url = make_url(raw_url)
    assert url.get_backend_name() == "postgresql"
    name = "crm_acc_g03d_" + uuid4().hex[:12]
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
            deal = Deal(number="PG-DRAFT-1", title="Sale", counterparty="Buyer")
            session.add(deal)
            await session.flush()
            doc = DealDocument(deal_id=deal.id, kind="contract", number="DOG-PG-DRAFT-1", status="draft")
            session.add(doc)
            await session.commit()
            doc_id, deal_id = doc.id, deal.id
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                               headers={"X-User-Roles": "director"}) as api:
            yield api, factory, doc_id, deal_id
    finally:
        if engine is not None:
            await engine.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


async def test_simultaneous_draft_edits_only_one_wins(postgres_draft_app):
    api, factory, doc_id, deal_id = postgres_draft_app
    listed = (await api.get(f"/sales/deals/{deal_id}/documents")).json()
    token = listed[0]["draft_edit_token"]
    path = f"/sales/documents/{doc_id}"
    edits = await asyncio.gather(*(
        api.patch(f"{path}/draft", json={"payment_terms": value,
                                          "expected_edit_token": token})
        for value in ("До отгрузки", "После отгрузки")
    ))
    assert sorted(response.status_code for response in edits) == [200, 409]
    winner = next(response.json()["payment_terms"] for response in edits if response.status_code == 200)
    async with factory() as session:
        doc = await session.get(DealDocument, doc_id)
        assert doc.payment_terms == winner
    history = (await api.get(f"{path}/field-history")).json()["items"]
    assert len(history) == 1
    assert history[0]["changes"]["payment_terms"] == {"before": None, "after": winner}
