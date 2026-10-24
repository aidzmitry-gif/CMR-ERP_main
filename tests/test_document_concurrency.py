"""Current ERP invoice races use an independent transaction per request."""
import asyncio
from copy import deepcopy
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.modules import ENABLED_MODULES
from core.db.base import Base
from core.domain.models import OutboxEvent
from core.runtime.app import create_app
from core.runtime.deps import get_session
from modules.sales.invoice_cancellation import InvoiceCancellationReceipt
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
from modules.sales.models import DealDocument
from modules.wms.models import ReservationVersion, StockMovement
from tests.test_invoice_issuance import command, create, seed
from tests.test_invoice_unreserved_cancellation import _atomic_command, _atomic_on_order


@pytest_asyncio.fixture
async def concurrent_app(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrency.db'}", connect_args={'timeout': 20})
    engine = engine.execution_options(schema_translate_map={m: None for m in ENABLED_MODULES})
    try:
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
                               headers={'X-User': 'issuer', 'X-User-Roles': 'director'}) as api:
            yield api, factory
    finally:
        await engine.dispose()


def _original(doc):
    assert doc.original_html and doc.snapshot_json and doc.issued_at
    assert doc.content_sha256 and len(doc.content_sha256) == 64
    return (doc.original_html, deepcopy(doc.snapshot_json), doc.content_sha256,
            doc.version, doc.amount, doc.issued_at)


async def _issued_events(session, doc_id):
    rows = (await session.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == 'sales.invoice.issued'))).all()
    return [row for row in rows if row.payload['document_id'] == doc_id]


async def _cancelled_original(api, factory):
    async with factory() as session:
        ids, doc, base = await _atomic_on_order(api, session)
        old_id, original = doc.id, _original(doc)
        path, payload = await _atomic_command(api, session, ids, doc)
    cancelled = await api.post(path, json=payload)
    assert cancelled.status_code == 201, cancelled.text
    result = cancelled.json()
    assert result['stock_outcome'] == 'no_stock_release' and result['release_id'] is None
    async with factory() as session:
        assert await session.get(InvoiceCancellationReceipt, result['cancellation_id']) is not None
        old = await session.get(DealDocument, old_id)
        assert old.status == 'cancelled' and _original(old) == original
    return ids, base, old_id, original


async def _replacement_command(api, ids, base, child_id):
    preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview",
                             json={**base, 'document_id': child_id})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    return {**base, 'request_key': 'concurrent-replacement-issue',
            'expected_document_version': p['document_version'],
            'expected_basis_digest': p['basis_digest'],
            'allocations': [], 'unreserved_confirmed': True}


async def test_concurrent_retries_issue_one_document(concurrent_app):
    api, factory = concurrent_app
    async with factory() as session:
        ids, base = await seed(api, session)
    payload, _ = await command(api, ids, base, key='concurrent-invoice')
    responses = await asyncio.gather(create(api, ids, payload), create(api, ids, payload))
    assert sorted(r.status_code for r in responses) == [200, 201], [r.text for r in responses]
    assert sorted(r.json()['replayed'] for r in responses) == [False, True]
    doc_id = responses[0].json()['document']['id']
    assert responses[1].json()['document'] == responses[0].json()['document']
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(DealDocument)) == 1
        assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt)) == 1
        assert len(await _issued_events(session, doc_id)) == 1
        doc = await session.get(DealDocument, doc_id)
        assert doc.amount == Decimal('240')
        original = _original(doc)
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 1
        versions = (await session.scalars(select(ReservationVersion))).all()
        assert len(versions) == 1
        reservation = versions[0]
        assert (reservation.organization_id, reservation.sku_code, reservation.warehouse,
                reservation.version, reservation.qty) == (ids['org'], ids['code'], 'W', 1, Decimal('2'))
        reserved = (await session.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == 'sales.stock.reserved'))).all()
        assert len([event for event in reserved if event.payload['document_id'] == doc_id]) == 1
        before = [await session.scalar(select(func.count()).select_from(model))
                  for model in (StockMovement, ReservationVersion, OutboxEvent)]
    repeated = await create(api, ids, payload)
    assert repeated.status_code == 200 and repeated.json()['replayed']
    async with factory() as session:
        assert _original(await session.get(DealDocument, doc_id)) == original
        assert before == [await session.scalar(select(func.count()).select_from(model))
                          for model in (StockMovement, ReservationVersion, OutboxEvent)]


async def test_concurrent_revision_and_issue_cannot_duplicate(concurrent_app):
    api, factory = concurrent_app
    ids, base, old_id, original = await _cancelled_original(api, factory)
    results = await asyncio.gather(*[
        api.post(f'/sales/documents/{old_id}/revision', json={
            'reason': 'Concurrent replacement', 'request_key': f'new-revision-{i}'})
        for i in range(2)
    ])
    assert sorted(r.status_code for r in results) == [201, 409], [r.text for r in results]
    child_id = next(r.json()['id'] for r in results if r.status_code == 201)
    preview = await api.get(f'/sales/documents/{child_id}/preview')
    assert preview.status_code == 409, preview.text
    assert preview.json()['detail'] == 'Invoice preview requires explicit ERP pricing and organization payload'
    async with factory() as session:
        child = await session.get(DealDocument, child_id)
        assert child.original_html is None and child.version == 2
        assert await session.get(InvoiceIssuanceReceipt, child_id) is None
        assert await session.scalar(select(func.count()).select_from(DealDocument)) == 2
    payload = await _replacement_command(api, ids, base, child_id)
    results = await asyncio.gather(*[
        api.post(f'/sales/documents/{child_id}/issue', json=payload) for _ in range(2)
    ])
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    assert sorted(r.json()['replayed'] for r in results) == [False, True]
    assert results[0].json()['document'] == results[1].json()['document']
    async with factory() as session:
        docs = (await session.scalars(select(DealDocument).order_by(DealDocument.id))).all()
        assert len(docs) == 2 and docs[0].superseded_by_id == docs[1].id
        assert docs[1].id == child_id and docs[1].amount == Decimal('240')
        assert _original(docs[0]) == original
        assert await session.get(InvoiceIssuanceReceipt, child_id) is not None
        assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt)) == 2
        assert len(await _issued_events(session, child_id)) == 1


async def test_edit_against_issuing_draft_is_serialized(concurrent_app):
    api, factory = concurrent_app
    ids, base, old_id, original = await _cancelled_original(api, factory)
    revision = await api.post(f'/sales/documents/{old_id}/revision', json={
        'reason': 'Draft editing', 'request_key': 'draft-edit-key'})
    assert revision.status_code == 201, revision.text
    child = revision.json()
    child_id = child['id']
    payload = await _replacement_command(api, ids, base, child_id)
    edited, issued = await asyncio.gather(
        api.patch(f'/sales/documents/{child_id}/draft', json={
            'expected_edit_token': child['draft_edit_token'], 'payment_terms': 'Concurrent terms'}),
        api.post(f'/sales/documents/{child_id}/issue', json=payload),
    )
    assert (edited.status_code, issued.status_code) in {(409, 200), (200, 409)}, (edited.text, issued.text)
    if edited.status_code == 200:
        assert issued.json()['detail'] == 'Invoice sources changed; obtain and confirm a new preview'
        async with factory() as session:
            draft = await session.get(DealDocument, child_id)
            assert draft.status == 'draft' and draft.original_html is None and draft.issued_at is None
            assert await session.get(InvoiceIssuanceReceipt, child_id) is None
            assert not await _issued_events(session, child_id)
        refreshed = await _replacement_command(api, ids, base, child_id)
        assert refreshed['expected_basis_digest'] != payload['expected_basis_digest']
        issued = await api.post(f'/sales/documents/{child_id}/issue', json=refreshed)
        assert issued.status_code == 200, issued.text
    assert not issued.json()['replayed']
    async with factory() as session:
        doc = await session.get(DealDocument, child_id)
        assert doc.snapshot_json['payment_terms'] == (
            'Concurrent terms' if edited.status_code == 200 else child['payment_terms'])
        assert doc.original_html and doc.issued_at
        captured = _original(doc)
        assert doc.amount == Decimal('240')
        assert await session.get(InvoiceIssuanceReceipt, child_id) is not None
        assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt)) == 2
        assert len(await _issued_events(session, child_id)) == 1
        assert _original(await session.get(DealDocument, old_id)) == original
    rejected = await api.patch(f'/sales/documents/{child_id}/draft', json={
        'expected_edit_token': child['draft_edit_token'], 'payment_terms': 'After issuance'})
    assert rejected.status_code == 409
    async with factory() as session:
        assert _original(await session.get(DealDocument, child_id)) == captured


async def test_existing_draft_replay_refreshes_cached_original(concurrent_app):
    api, factory = concurrent_app
    ids, base, old_id, _ = await _cancelled_original(api, factory)
    revision = await api.post(f'/sales/documents/{old_id}/revision', json={
        'reason': 'Cached draft replay', 'request_key': 'cached-draft-revision'})
    assert revision.status_code == 201, revision.text
    child_id = revision.json()['id']
    payload = await _replacement_command(api, ids, base, child_id)
    async with factory() as cached_session:
        cached = await cached_session.get(DealDocument, child_id)
        await cached_session.commit()
        first = await api.post(f'/sales/documents/{child_id}/issue', json=payload)
        assert first.status_code == 200 and not first.json()['replayed'], first.text
        assert cached.status == 'draft' and cached.original_html is None
        async with factory() as session:
            frozen = _original(await session.get(DealDocument, child_id))
            before = [await session.scalar(select(func.count()).select_from(model))
                      for model in (InvoiceIssuanceReceipt, StockMovement, ReservationVersion, OutboxEvent)]
        app = api._transport.app
        previous = app.dependency_overrides[get_session]

        async def cached_request_session():
            yield cached_session

        app.dependency_overrides[get_session] = cached_request_session
        try:
            repeated = await api.post(f'/sales/documents/{child_id}/issue', json=payload)
        finally:
            app.dependency_overrides[get_session] = previous
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()['replayed']
        assert repeated.json()['document'] == first.json()['document']
    async with factory() as session:
        assert _original(await session.get(DealDocument, child_id)) == frozen
        assert await session.get(InvoiceIssuanceReceipt, child_id) is not None
        assert await session.scalar(select(func.count()).select_from(InvoiceIssuanceReceipt)) == 2
        assert len(await _issued_events(session, child_id)) == 1
        assert before == [await session.scalar(select(func.count()).select_from(model))
                          for model in (InvoiceIssuanceReceipt, StockMovement, ReservationVersion, OutboxEvent)]
