"""Independent transactions exercise actual DB locks, not a shared test session."""
import asyncio
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.modules import ENABLED_MODULES
from core.db.base import Base
from core.domain.models import OutboxEvent, Sku
from core.runtime.app import create_app
from core.runtime.deps import get_session
from modules.sales.models import Deal, DealDocument, DealItem, PriceQuote


@pytest_asyncio.fixture
async def concurrent_app(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrency.db'}", connect_args={'timeout': 20})
    engine = engine.execution_options(schema_translate_map={m: None for m in ENABLED_MODULES})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()
    async def own_session():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = own_session
    async with factory() as session:
        deal = Deal(number='CONCURRENT', title='Original', counterparty='Buyer', amount=200)
        sku = Sku(code='CONCURRENT', title='Original SKU', unit='шт')
        session.add_all([deal, sku])
        await session.flush()
        session.add_all([DealItem(deal_id=deal.id, sku_id=sku.id, qty=2),
                         PriceQuote(sku_code=sku.code, counterparty='Buyer', price=100)])
        await session.commit()
        deal_id, sku_id = deal.id, sku.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test',
                           headers={'X-User-Roles': 'director'}) as api:
        yield api, factory, deal_id, sku_id
    await engine.dispose()


async def test_concurrent_retries_issue_one_document(concurrent_app):
    api, factory, deal_id, _ = concurrent_app
    responses = await asyncio.gather(*[
        api.post(f'/sales/deals/{deal_id}/documents', json={'kind': 'invoice', 'request_key': 'concurrent-invoice'})
        for _ in range(2)
    ])
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json()['id'] == responses[1].json()['id']
    async with factory() as session:
        assert len((await session.execute(select(DealDocument))).scalars().all()) == 1
        assert len((await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == 'sales.document.posted'))).scalars().all()) == 1


async def test_concurrent_revision_and_issue_cannot_duplicate(concurrent_app):
    api, factory, deal_id, _ = concurrent_app
    old = (await api.post(f'/sales/deals/{deal_id}/documents', json={'kind': 'invoice'})).json()
    results = await asyncio.gather(*[
        api.post(f"/sales/documents/{old['id']}/revision", json={'reason': 'Concurrent replacement', 'request_key': f'new-revision-{i}'})
        for i in range(2)
    ])
    assert sorted(r.status_code for r in results) == [201, 409]
    new = next(r.json() for r in results if r.status_code == 201)
    previews = await api.get(f"/sales/documents/{new['id']}/preview")
    assert previews.status_code == 200, previews.text
    async with factory() as session:
        assert (await session.get(DealDocument, new['id'])).original_html is None
    results = await asyncio.gather(*[api.post(f"/sales/documents/{new['id']}/issue") for _ in range(2)])
    assert [r.status_code for r in results] == [200, 200]
    async with factory() as session:
        docs = (await session.execute(select(DealDocument).order_by(DealDocument.id))).scalars().all()
        assert len(docs) == 2 and docs[0].superseded_by_id == docs[1].id
        assert docs[1].amount == Decimal('240')


async def test_edit_against_issuing_draft_is_serialized(concurrent_app):
    api, factory, deal_id, _ = concurrent_app
    old = (await api.post(f'/sales/deals/{deal_id}/documents', json={'kind': 'invoice'})).json()
    new = (await api.post(f"/sales/documents/{old['id']}/revision", json={'reason': 'Draft editing', 'request_key': 'draft-edit-key'})).json()
    edited, issued = await asyncio.gather(
        api.patch(f"/sales/documents/{new['id']}/draft", json={'payment_terms': 'Concurrent terms'}),
        api.post(f"/sales/documents/{new['id']}/issue"),
    )
    assert issued.status_code == 200, issued.text
    assert edited.status_code in {200, 409}
    async with factory() as session:
        doc = await session.get(DealDocument, new['id'])
        assert doc.snapshot_json['payment_terms'] == ('Concurrent terms' if edited.status_code == 200 else None)
        assert doc.original_html and doc.issued_at
