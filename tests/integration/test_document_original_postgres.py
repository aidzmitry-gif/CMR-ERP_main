"""Actual migrated PostgreSQL: immutable SQL guards, row locks and ERP receipts.

Checks the 0115 immutable guards through current ERP issue/cancellation receipts.
"""
import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import Counterparty, OutboxEvent, Sku
from core.services.eventbus import EventContext
from modules.accounting.models import AccessGrant, Organization
from modules.finance.models import Payment
from modules.integrations.models import StockItem
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.client_document_register import DealClientBinding, preview_snapshot
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt, verified_receipt
from modules.sales.models import ContractTemplate, Deal, DealDocument, DealItem, PriceQuote
from modules.wms.models import StockMovement, WarehouseDirectory
from tests.test_invoice_issuance import command, create


async def _sources(pg_app):
    pg_app.headers['X-User'] = 'original-pg'
    core = pg_app._transport.app.state.core
    factory = core.services.db.session_factory
    assert not getattr(core.services.onec, 'outbound_document_source_available', False)
    async with factory() as session:
        has_draft = await session.scalar(text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='sales' AND table_name='deal_document' AND column_name='original_html')"))
        assert has_draft, 'Required document migration 0115 has not been applied'
        key = uuid4().hex
        sku = Sku(code=key, title='Original SKU', unit='шт')
        buyer = Counterparty(name='Original buyer ' + key,
            unp=str(100000000 + uuid4().int % 800000000), requisites={'address': 'Original address'})
        template = ContractTemplate(code=key, name='Original template', body='<p>{{number}} {{items}} {{buyer.name}} {{buyer.address}} {{total}}</p>')
        session.add_all([sku, buyer, template])
        await session.flush()
        session.add(PriceQuote(sku_code=sku.code, counterparty=buyer.name, price=100))
        session.add(StockItem(sku_code=sku.code, qty_available=100, qty_reserved=0))
        await session.commit()
        sku_id, buyer_id, template_id = sku.id, buyer.id, template.id
        buyer_name = buyer.name
    response = await pg_app.post('/sales/deals', json={'number':key, 'title':'Original deal', 'counterparty':buyer_name, 'counterparty_id':buyer_id, 'amount':240})
    assert response.status_code == 201, response.text
    deal = response.json()
    assert (await pg_app.post(f"/sales/deals/{deal['id']}/items", json={'sku_id':sku_id, 'qty':2, 'unit_price':100})).status_code == 201
    async with factory() as session:
        org = Organization(name='Original seller ' + key,
                           unp=str(100000000 + uuid4().int % 800000000))
        session.add(org)
        await session.flush()
        session.add_all([
            AccessGrant(organization_id=org.id, subject='original-pg', role='chief'),
            DealOwnership(deal_id=deal['id'], organization_id=org.id, snapshot={},
                          evidence='Synthetic exact document ownership', actor='original-pg'),
            WarehouseDirectory(organization_id=org.id, name='W', title='Original warehouse',
                               wms_enabled=False, prohibit_negative_stock=True, created_by='original-pg'),
            StockMovement(organization_id=org.id, sku_code=key, warehouse='W',
                          kind='in', qty=100, reason='receipt'),
        ])
        session.add(DealClientBinding(deal_id=deal['id'], organization_id=org.id,
            counterparty_id=buyer_id, snapshot=await preview_snapshot(
                session, org.id, await session.get(Deal, deal['id']), buyer_id),
            evidence='Synthetic exact original buyer', actor='original-pg'))
        item_id = await session.scalar(select(DealItem.id).where(DealItem.deal_id == deal['id']))
        await session.commit()
        org_id = org.id
    # Contracts use the configured legal seller; ERP invoices use its owned
    # seller profile. Bind both to this same synthetic company, without changing
    # process settings or allowing packages for mismatched legal entities.
    core.config = core.config.model_copy(update={
        'seller_name': org.name, 'seller_unp': org.unp, 'seller_address': 'Original seller address',
        'seller_account': 'SYNTHETIC ACCOUNT', 'seller_bank': 'Synthetic bank',
        'seller_bik': 'SYNTHETIC', 'seller_director': 'Synthetic director',
        'seller_phone': '', 'seller_email': '',
    })
    seller = await pg_app.post(f'/accounting/organizations/{org_id}/seller-profiles', json={
        'source_key': key, 'expected_revision': 0, 'effective_from': '2026-01-01',
        'currency': 'BYN', 'address': 'Original seller address', 'account': 'SYNTHETIC ACCOUNT',
        'bank': 'Synthetic bank', 'bik': 'SYNTHETIC', 'director': 'Synthetic director',
        'evidence': 'Synthetic approved seller original', 'confirmed': True})
    assert seller.status_code == 201, seller.text
    ids = {'org': org_id, 'deal': deal['id'], 'item': item_id}
    base = {'organization_id': org_id, 'currency': 'BYN', 'document_date': '2026-09-01',
            'valid_until': '2026-09-06',
            'pricing': [{'item_id': item_id, 'unit_price_net': '100.00', 'vat_rate': '20.00'}],
            'pricing_evidence': 'Synthetic reviewed original price and VAT'}
    return core, factory, key, deal, sku_id, buyer_id, template_id, ids, base


async def _cancel_for_replacement(pg_app, ids, invoice):
    # Exercise public reconciliation/review/cancel, never forge a cancellation
    # receipt. Archive statements here refer only to this synthetic test book.
    prefix = f"/sales/organizations/{ids['org']}/invoices/{invoice['id']}"
    identity = {'expected_version': invoice['version'],
                'expected_content_sha256': invoice['content_sha256']}
    money = await pg_app.get(prefix + '/money-reconciliation')
    assert money.status_code == 200, money.text
    bounds = money.json()
    reconciled = await pg_app.post(prefix + '/money-reconciliation', json={
        'source_key': str(uuid4()), 'expected_basis_digest': bounds['basis_digest'],
        'history_from': bounds['required_history_from'], 'history_through': bounds['required_history_through'],
        'evidence': 'Synthetic empty book money history checked',
        'source_references': ['Synthetic bank archive', 'Synthetic cash archive'],
        'all_money_sources_checked': True})
    assert reconciled.status_code == 201, reconciled.text
    preview = await pg_app.post(prefix + '/cancellation/preview', json=identity)
    assert preview.status_code == 200, preview.text
    facts = preview.json()
    history = facts['sections']['legacy_fulfillment']['facts']
    reviewed = await pg_app.post(prefix + '/fulfillment-review', json={
        **identity, 'request_key': str(uuid4()), 'expected_basis_digest': facts['basis_digest'],
        'money_reconciliation_id': reconciled.json()['id'],
        'evidence': 'Synthetic complete original-document history',
        'external_sources': [{'system': 'Synthetic archive', 'reference': f"Invoice {invoice['id']}",
            'history_from': history['required_history_from'], 'history_through': history['required_history_through'],
            'confirmed_no_fulfillment': True}], 'all_fulfillment_sources_identified': True})
    assert reviewed.status_code == 201, reviewed.text
    cancelled = await pg_app.post(prefix + '/cancel', json={
        **identity, 'request_key': str(uuid4()), 'fulfillment_review_id': reviewed.json()['review_id'],
        'expected_review_digest': reviewed.json()['review_digest'],
        'evidence': 'Synthetic cancellation before exact replacement', 'acknowledge_invoice_invalidation': True})
    assert cancelled.status_code == 201, cancelled.text


async def test_migrated_originals_approval_packages_and_sql_guards(pg_app):
    core, factory, key, deal, sku_id, buyer_id, template_id, ids, base = await _sources(pg_app)
    initial, _ = await command(pg_app, ids, base, key=key)
    response = await create(pg_app, ids, initial)
    assert response.status_code == 201, response.text
    invoice = response.json()['document']
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
        item = await session.scalar(select(DealItem).where(DealItem.deal_id == deal['id']))
        item.unit_price = Decimal('150')
        await session.commit()
    approve = await pg_app.post(f"/sales/documents/{contract['id']}/decide", json={'approved':True})
    assert approve.status_code == 200, approve.text
    assert (await pg_app.get(invoice_url)).content == invoice_original
    assert (await pg_app.get(contract_url)).content == reviewed
    p = await pg_app.post(f"/sales/deals/{deal['id']}/send-package")
    assert p.status_code == 200, p.text
    package = p.json()
    package_original = (await pg_app.get(package['render_url'])).content
    await _cancel_for_replacement(pg_app, ids, invoice)
    new = (await pg_app.post(f"/sales/documents/{invoice['id']}/revision", json={'reason':'New price', 'request_key':key+'r'})).json()
    revised_base = {**base, 'pricing': [{'item_id': ids['item'], 'unit_price_net': '150.00', 'vat_rate': '20.00'}]}
    revision, _ = await command(pg_app, ids, revised_base, doc_id=new['id'], key=key+'issue')
    assert (await pg_app.post(f"/sales/documents/{new['id']}/issue", json=revision)).status_code == 200
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
        assert (await session.get(DealDocument, invoice['id'])).status == 'cancelled'
        for document_id in (invoice['id'], new['id']):
            assert await verified_receipt(session, await session.get(DealDocument, document_id), ids['org']) is not None
        await core.event_bus.relay_once(session, EventContext(session=session, services=core.services),
            event_types=['sales.document.posted', 'sales.document.superseded'])
        payments = (await session.execute(select(Payment).where(Payment.deal_id == deal['id']).order_by(Payment.id))).scalars().all()
        # Current ERP issues emit sales.invoice.issued, not legacy finance
        # document-posted placeholders. The signed issuance receipts carry the
        # exact240/360 originals; an issued invoice is not a money receipt.
        assert payments == []
        receipts = (await session.scalars(select(InvoiceIssuanceReceipt).where(
            InvoiceIssuanceReceipt.deal_id == deal['id']).order_by(InvoiceIssuanceReceipt.document_id))).all()
        assert [(row.document_id, Decimal(str(row.response['document']['amount']))) for row in receipts] == [
            (invoice['id'], Decimal('240')), (new['id'], Decimal('360'))]
    assert (await pg_app.get(invoice_url)).content == invoice_original


async def test_two_pg_issue_requests_wait_on_same_deal_and_issue_only_once(pg_app):
    _, factory, key, deal, _, _, _, ids, base = await _sources(pg_app)
    initial, _ = await command(pg_app, ids, base, key=key+'initial')
    response = await create(pg_app, ids, initial)
    assert response.status_code == 201, response.text
    old = response.json()['document']
    await _cancel_for_replacement(pg_app, ids, old)
    new = (await pg_app.post(f"/sales/documents/{old['id']}/revision", json={'reason':'Concurrent issue', 'request_key':key})).json()
    revision, _ = await command(pg_app, ids, base, doc_id=new['id'], key=key+'issue')
    tasks = []
    try:
        async with factory() as holder:
            await holder.execute(text('UPDATE sales.deal SET id=id WHERE id=:id'), {'id':deal['id']})
            pid = await holder.scalar(text('SELECT pg_backend_pid()'))
            tasks = [asyncio.create_task(pg_app.post(f"/sales/documents/{new['id']}/issue", json=revision)) for _ in range(2)]
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
                OutboxEvent.event_type == 'sales.invoice.issued',
                OutboxEvent.payload['document_id'].as_integer() == new['id'],
            ))
            assert count == 1
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
