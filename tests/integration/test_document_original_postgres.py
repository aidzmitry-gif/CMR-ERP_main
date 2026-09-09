"""Actual migrated PostgreSQL: immutable SQL guards, row locks and financial relay.

Requires migration 0115 from the normal Alembic chain.
"""
import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import Counterparty, OutboxEvent, Sku
from core.services.eventbus import EventContext
from modules.finance.models import Payment
from modules.sales.models import ContractTemplate, DealDocument, PriceQuote


async def _sources(pg_app):
    core = pg_app._transport.app.state.core
    factory = core.services.db.session_factory
    async with factory() as session:
        has_draft = await session.scalar(text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='sales' AND table_name='deal_document' AND column_name='original_html')"))
        assert has_draft, 'Required document migration 0115 has not been applied'
        key = uuid4().hex
        sku = Sku(code=key, title='Original SKU', unit='шт')
        buyer = Counterparty(name='Original buyer ' + key, unp=None, requisites={'address': 'Original address'})
        template = ContractTemplate(code=key, name='Original template', body='<p>{{number}} {{items}} {{buyer.name}} {{buyer.address}} {{total}}</p>')
        session.add_all([sku, buyer, template])
        await session.flush()
        session.add(PriceQuote(sku_code=sku.code, counterparty=buyer.name, price=100))
        await session.commit()
        sku_id, buyer_id, template_id = sku.id, buyer.id, template.id
        buyer_name = buyer.name
    response = await pg_app.post('/sales/deals', json={'number':key, 'title':'Original deal', 'counterparty':buyer_name, 'amount':240})
    assert response.status_code == 201, response.text
    deal = response.json()
    assert (await pg_app.post(f"/sales/deals/{deal['id']}/items", json={'sku_id':sku_id, 'qty':2})).status_code == 201
    return core, factory, key, deal, sku_id, buyer_id, template_id


async def test_migrated_originals_approval_packages_and_sql_guards(pg_app):
    core, factory, key, deal, sku_id, buyer_id, template_id = await _sources(pg_app)
    response = await pg_app.post(f"/sales/deals/{deal['id']}/documents", json={'kind':'invoice', 'request_key':key})
    assert response.status_code == 201, response.text
    invoice = response.json()
    contract = (await pg_app.post(f"/sales/deals/{deal['id']}/contract", json={'template_code':key})).json()
    invoice_url = f"/sales/documents/{invoice['id']}/render"
    contract_url = f"/sales/documents/{contract['id']}/render"
    invoice_original = (await pg_app.get(invoice_url)).content
    reviewed = (await pg_app.get(contract_url)).content
    async with factory() as session:
        sku = await session.get(Sku, sku_id)
        buyer = await session.get(Counterparty, buyer_id)
        sku.title, buyer.requisites = 'New SKU title', {'address':'Changed buyer address'}
        (await session.get(ContractTemplate, template_id)).body = '<h1>Different template</h1>'
        session.add(PriceQuote(sku_code=sku.code, counterparty=buyer.name, price=150))
        await session.commit()
    approve = await pg_app.post(f"/sales/documents/{contract['id']}/decide", json={'approved':True})
    assert approve.status_code == 200, approve.text
    assert (await pg_app.get(invoice_url)).content == invoice_original
    assert (await pg_app.get(contract_url)).content == reviewed
    p = await pg_app.post(f"/sales/deals/{deal['id']}/send-package")
    assert p.status_code == 200, p.text
    package = p.json()
    package_original = (await pg_app.get(package['render_url'])).content
    new = (await pg_app.post(f"/sales/documents/{invoice['id']}/revision", json={'reason':'New price', 'request_key':key+'r'})).json()
    assert (await pg_app.post(f"/sales/documents/{new['id']}/issue")).status_code == 200
    assert (await pg_app.get(package['render_url'])).content == package_original
    assert (await pg_app.get(invoice_url)).content == invoice_original
    statements = [
        ('UPDATE sales.deal_document SET amount=999 WHERE id=:id', invoice['id']),
        ("UPDATE sales.deal_document SET original_html='tampered' WHERE id=:id", invoice['id']),
        ("UPDATE sales.deal_document SET snapshot_json='{}' WHERE id=:id", invoice['id']),
        ('DELETE FROM sales.deal_document WHERE id=:id', invoice['id']),
        ("UPDATE sales.deal_document SET issued_by='forged' WHERE id=:id", invoice['id']),
        ('UPDATE sales.deal_document SET superseded_by_id=NULL WHERE id=:id', invoice['id']),
        ("UPDATE sales.document_package SET original_html='tampered' WHERE id=:id", package['package_id']),
        ('DELETE FROM sales.document_package WHERE id=:id', package['package_id']),
    ]
    for statement, identifier in statements:
        async with factory() as session:
            with pytest.raises(DBAPIError, match='immutable|cannot be deleted'):
                await session.execute(text(statement), {'id':identifier})
            await session.rollback()
    async with factory() as session:
        # Status is a legitimate lifecycle change; content stays fixed.
        await session.execute(text("UPDATE sales.deal_document SET status='paid' WHERE id=:id"), {'id':invoice['id']})
        await session.commit()
        await core.event_bus.relay_once(session, EventContext(session=session, services=core.services),
            event_types=['sales.document.posted', 'sales.document.superseded'])
        payments = (await session.execute(select(Payment).where(Payment.deal_id == deal['id']).order_by(Payment.id))).scalars().all()
        assert [(p.entity_ref, p.amount, p.status) for p in payments] == [
            (f"document:{invoice['id']}", Decimal('240'), 'superseded'),
            (f"document:{new['id']}", Decimal('360'), 'pending'),
        ]
    assert (await pg_app.get(invoice_url)).content == invoice_original


async def test_two_pg_issue_requests_wait_on_same_deal_and_issue_only_once(pg_app):
    _, factory, key, deal, *_ = await _sources(pg_app)
    response = await pg_app.post(f"/sales/deals/{deal['id']}/documents", json={'kind':'invoice'})
    assert response.status_code == 201, response.text
    old = response.json()
    new = (await pg_app.post(f"/sales/documents/{old['id']}/revision", json={'reason':'Concurrent issue', 'request_key':key})).json()
    tasks = []
    try:
        async with factory() as holder:
            await holder.execute(text('UPDATE sales.deal SET id=id WHERE id=:id'), {'id':deal['id']})
            pid = await holder.scalar(text('SELECT pg_backend_pid()'))
            tasks = [asyncio.create_task(pg_app.post(f"/sales/documents/{new['id']}/issue")) for _ in range(2)]
            async with factory() as observer:
                for _ in range(100):
                    # Include request connections opened after the first activity snapshot.
                    await observer.execute(text('SELECT pg_stat_clear_snapshot()'))
                    blocked = await observer.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE :pid=ANY(pg_blocking_pids(pid))'), {'pid':pid})
                    if blocked >= 1:
                        break
                    await asyncio.sleep(0.02)
                assert blocked >= 1, 'No real PostgreSQL lock wait was observed'
                assert not any(task.done() for task in tasks)
            await holder.commit()
        responses = await asyncio.gather(*tasks)
        assert [r.status_code for r in responses] == [200,200], [r.text for r in responses]
        assert responses[0].json()['content_sha256'] == responses[1].json()['content_sha256']
        async with factory() as session:
            docs = (await session.execute(select(DealDocument).where(DealDocument.deal_id == deal['id']))).scalars().all()
            assert len(docs) == 2
            assert (await session.get(DealDocument, old['id'])).superseded_by_id == new['id']
            count = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.event_type == 'sales.document.posted',
                OutboxEvent.payload['document_id'].as_integer() == new['id'],
            ))
            assert count == 1
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
