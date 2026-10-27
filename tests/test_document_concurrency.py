"""Independent transactions exercise actual DB locks, not a shared test session."""
import asyncio
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.modules import ENABLED_MODULES
from core.db.base import Base
from core.domain.models import OutboxEvent
from core.runtime.app import create_app
from core.runtime.deps import get_session
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
from modules.sales.models import DealDocument
from modules.sales.reservation_source import SalesReservationSource
from tests.test_invoice_cancellation import cancel_request
from tests.test_invoice_issuance import command, create, seed


@pytest_asyncio.fixture
async def concurrent_app(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrency.db'}", connect_args={'timeout': 20})
    engine = engine.execution_options(schema_translate_map={m: None for m in ENABLED_MODULES})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()
    app.state.core.services.db.session_factory = factory
    async def own_session():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = own_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test',
                           headers={'X-User-Roles': 'director'}) as api:
        async with factory() as session:
            ids, base = await seed(api, session)
        yield api, factory, ids, base
    await engine.dispose()


async def test_concurrent_retries_issue_one_document(concurrent_app):
    api, factory, ids, base = concurrent_app
    payload, _ = await command(api, ids, base, key='concurrent-invoice')
    responses = await asyncio.gather(*[
        create(api, ids, payload)
        for _ in range(2)
    ])
    assert sorted(r.status_code for r in responses) == [200, 201], [r.text for r in responses]
    assert responses[0].json()['document']['id'] == responses[1].json()['document']['id']
    assert sorted(r.json()['replayed'] for r in responses) == [False, True]
    async with factory() as session:
        assert len((await session.execute(select(DealDocument))).scalars().all()) == 1
        assert len((await session.scalars(select(InvoiceIssuanceReceipt))).all()) == 1
        assert len((await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == 'sales.invoice.issued'))).scalars().all()) == 1


async def cancel_original(api, factory, ids, document_id):
    assert document_id == 1  # The existing cancellation fixture has one fresh invoice.
    async with factory() as session:
        facts = await SalesReservationSource().invoice_reservation(session, document_id)
        await session.commit()
    path, payload = await cancel_request(api, ids['org'], facts)
    cancelled = await api.post(path, json=payload)
    assert cancelled.status_code == 201, cancelled.text


async def test_concurrent_revision_and_issue_cannot_duplicate(concurrent_app, monkeypatch):
    api, factory, ids, base = concurrent_app
    payload, _ = await command(api, ids, base)
    first = await create(api, ids, payload)
    assert first.status_code == 201, first.text
    old = first.json()['document']
    results = await asyncio.gather(*[
        api.post(f"/sales/documents/{old['id']}/revision", json={'reason': 'Concurrent replacement', 'request_key': f'new-revision-{i}'})
        for i in range(2)
    ])
    assert sorted(r.status_code for r in results) == [201, 409]
    new = next(r.json() for r in results if r.status_code == 201)
    blocked = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview",
                            json={**base, 'document_id': new['id']})
    assert blocked.status_code == 409, blocked.text
    await cancel_original(api, factory, ids, old['id'])
    payload, preview = await command(api, ids, base, doc_id=new['id'], key='concurrent-replacement')
    assert preview['document_version'] == 2
    async with factory() as session:
        assert (await session.get(DealDocument, new['id'])).original_html is None
    # Both routes must have discovered the draft before either issuer takes the
    # organization/deal locks. This deterministically exercises a stale identity map.
    from modules.sales import invoice_issuance

    lock_context = invoice_issuance.lock_context
    both_discovered = asyncio.Event()
    arrivals = 0

    async def wait_for_both(*args, **kwargs):
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            both_discovered.set()
        await asyncio.wait_for(both_discovered.wait(), 5)
        return await lock_context(*args, **kwargs)

    monkeypatch.setattr(invoice_issuance, 'lock_context', wait_for_both)
    results = await asyncio.gather(*[api.post(f"/sales/documents/{new['id']}/issue", json=payload) for _ in range(2)])
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    assert sorted(r.json()['replayed'] for r in results) == [False, True]
    async with factory() as session:
        docs = (await session.execute(select(DealDocument).order_by(DealDocument.id))).scalars().all()
        assert len(docs) == 2 and docs[0].superseded_by_id == docs[1].id
        assert docs[1].amount == Decimal('240')
        assert len((await session.scalars(select(InvoiceIssuanceReceipt))).all()) == 2


async def test_edit_against_issuing_draft_is_serialized(concurrent_app):
    api, factory, ids, base = concurrent_app
    payload, _ = await command(api, ids, base)
    first = await create(api, ids, payload)
    assert first.status_code == 201, first.text
    old = first.json()['document']
    new = (await api.post(f"/sales/documents/{old['id']}/revision", json={'reason': 'Draft editing', 'request_key': 'draft-edit-key'})).json()
    await cancel_original(api, factory, ids, old['id'])
    payload, _ = await command(api, ids, base, doc_id=new['id'], key='concurrent-edit-issue')
    edited, issued = await asyncio.gather(
        api.patch(f"/sales/documents/{new['id']}/draft", json={
            'expected_edit_token': new['draft_edit_token'], 'payment_terms': 'Concurrent terms'}),
        api.post(f"/sales/documents/{new['id']}/issue", json=payload),
    )
    assert edited.status_code in {200, 409}
    if issued.status_code == 409:
        assert edited.status_code == 200
        assert 'Invoice sources changed' in issued.text
        async with factory() as session:
            assert (await session.get(DealDocument, new['id'])).original_html is None
            assert await session.get(InvoiceIssuanceReceipt, new['id']) is None
            assert (await session.get(DealDocument, old['id'])).superseded_by_id is None
        payload, _ = await command(api, ids, base, doc_id=new['id'], key='refreshed-edit-issue')
        issued = await api.post(f"/sales/documents/{new['id']}/issue", json=payload)
    assert issued.status_code == 200, issued.text
    async with factory() as session:
        doc = await session.get(DealDocument, new['id'])
        assert doc.snapshot_json['payment_terms'] == ('Concurrent terms' if edited.status_code == 200 else None)
        assert doc.original_html and doc.issued_at
        assert (await session.get(DealDocument, old['id'])).superseded_by_id == doc.id
        assert len((await session.scalars(select(InvoiceIssuanceReceipt))).all()) == 2
