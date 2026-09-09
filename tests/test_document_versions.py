"""Acceptance scenarios for immutable invoices, approval copies and replacements."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from core.domain.models import Counterparty, OutboxEvent, Sku, User
from modules.sales.events import on_payment_paid
from modules.sales.models import (
    CompanyBranding,
    ContractTemplate,
    Deal,
    DealDocument,
    DealItem,
    DocumentPackage,
    PriceQuote,
)


async def make_invoice(api, session):
    sku = Sku(code='ORIGINAL', title='Battery original', unit='шт')
    cp = Counterparty(name='Buyer original', unp='111111111', requisites={'address': 'Original address'})
    session.add_all([sku, cp])
    await session.flush()
    session.add(PriceQuote(sku_code=sku.code, counterparty=cp.name, price=Decimal('100')))
    await session.commit()
    deal = (await api.post('/sales/deals', json={
        'number': 'ORIG', 'title': 'Original deal', 'counterparty': cp.name, 'amount': 200,
    })).json()
    item = (await api.post(f"/sales/deals/{deal['id']}/items", json={'sku_id': sku.id, 'qty': 2})).json()
    result = await api.post(f"/sales/deals/{deal['id']}/documents", json={
        'kind': 'invoice', 'request_key': 'invoice-original',
    })
    assert result.status_code == 201, result.text
    return deal, result.json(), sku, cp, item


async def make_contract(api, session, deal):
    template = ContractTemplate(code='STATIC', name='Contract original', body='<h1>{{number}}</h1><p>{{items}} {{buyer.name}} {{buyer.unp}} {{seller.name}} {{payment_terms}} {{total}} {{deal}}</p>')
    session.add(template)
    await session.commit()
    result = await api.post(f"/sales/deals/{deal['id']}/contract", json={
        'template_code': template.code, 'payment_terms': 'Original payment terms',
    })
    assert result.status_code == 201, result.text
    return result.json(), template


async def test_every_mutable_invoice_source_is_frozen(api, session, monkeypatch):
    deal, doc, sku, cp, item = await make_invoice(api, session)
    url = f"/sales/documents/{doc['id']}/render"
    before = await api.get(url)
    snapshot = (await api.get(f"/sales/documents/{doc['id']}/snapshot")).json()
    assert snapshot['amount'] == '240.00'
    assert sum(Decimal(i['total']) for i in snapshot['items']) == Decimal('240')
    assert snapshot['buyer']['address'] == 'Original address'
    assert doc['original_state'] == 'issued'
    sku.code, sku.title, sku.unit = 'CHANGED', 'Changed product', 'кг'
    cp.name, cp.unp, cp.requisites = 'Changed buyer', '222222222', {'address': 'Changed address'}
    row = await session.get(Deal, deal['id'])
    row.title, row.number, row.counterparty, row.amount = 'Changed deal', 'NEW-NUMBER', 'Changed buyer', Decimal('999')
    (await session.get(DealItem, item['id'])).qty = 99
    session.add(CompanyBranding(id=1, logo_data_url='data:image/png;base64,YWJj'))
    session.add(PriceQuote(sku_code='CHANGED', counterparty='Changed buyer', price=Decimal('150')))
    await session.commit()
    from config.settings import get_settings
    monkeypatch.setattr(get_settings(), 'seller_name', 'New seller')
    monkeypatch.setattr(get_settings(), 'seller_account', 'New account')
    monkeypatch.setenv('AIOS_INVOICE_VALID_DAYS', '91')
    for _ in range(2):
        reopened = await api.get(url)
        assert reopened.content == before.content
        assert reopened.headers['etag'] == before.headers['etag']
    assert '240.00' in reopened.text and 'Original address' in reopened.text
    assert (await session.get(DealDocument, doc['id'])).amount == Decimal('240')


async def test_contract_approval_issues_the_reviewed_copy(api, session):
    deal, invoice, sku, cp, item = await make_invoice(api, session)
    doc, template = await make_contract(api, session, deal)
    url = f"/sales/documents/{doc['id']}/render"
    candidate = await api.get(url)
    assert candidate.headers['x-document-state'] == 'approval_copy'
    template.body = '<p>Entirely different contract</p>'
    sku.title = 'Changed after submission'
    (await session.get(Deal, deal['id'])).amount = Decimal('999')
    await session.commit()
    approved = await api.post(f"/sales/documents/{doc['id']}/decide", json={'approved': True, 'by': 'spoofed'})
    assert approved.status_code == 200, approved.text
    assert approved.json()['amount'] == 200
    assert (await api.get(url)).content == candidate.content
    template.body = '<p>Third template</p>'
    await session.commit()
    assert (await api.get(url)).content == candidate.content
    events = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == 'sales.document.posted'))).scalars().all()
    assert events[-1].payload['amount'] == '200.00'


async def test_revision_draft_issue_history_and_payment_identity(api, session):
    deal, old, sku, cp, item = await make_invoice(api, session)
    before = (await api.get(f"/sales/documents/{old['id']}/render")).content
    payload = {'reason': 'New agreed price', 'request_key': 'revision-key-1'}
    revision = await api.post(f"/sales/documents/{old['id']}/revision", json=payload)
    assert revision.status_code == 201, revision.text
    new = revision.json()
    assert new['status'] == 'draft' and new['supersedes_id'] == old['id']
    assert new['id'] != old['id'] and new['number'] != old['number']
    assert new['version'] == 2 and new['content_sha256'] is None
    duplicate = await api.post(f"/sales/documents/{old['id']}/revision", json=payload)
    assert duplicate.json()['id'] == new['id']
    changed_key = await api.post(f"/sales/documents/{old['id']}/revision", json={**payload, 'reason': 'Different reason'})
    assert changed_key.status_code == 409
    session.add(PriceQuote(sku_code=sku.code, counterparty=cp.name, price=Decimal('150')))
    await session.commit()
    issued = await api.post(f"/sales/documents/{new['id']}/issue")
    assert issued.status_code == 200, issued.text
    assert issued.json()['amount'] == 360
    assert (await api.get(f"/sales/documents/{old['id']}/render")).content == before
    assert (await api.post(f"/sales/documents/{new['id']}/issue")).json()['id'] == new['id']
    assert (await session.get(DealDocument, old['id'])).superseded_by_id == new['id']
    await on_payment_paid({'ref': old['number'], 'deal_id': deal['id']}, SimpleNamespace(session=session))
    await session.commit()
    assert (await session.get(DealDocument, old['id'])).status == 'paid'
    assert (await session.get(DealDocument, new['id'])).status == 'posted'
    await on_payment_paid({'ref': 'Unknown', 'deal_id': deal['id']}, SimpleNamespace(session=session))
    await session.commit()
    assert (await session.get(DealDocument, new['id'])).status == 'posted'
    assert (await api.patch(f"/sales/documents/{old['id']}/draft", json={'payment_terms': 'tamper'})).status_code == 409


async def test_package_pins_versions_and_is_idempotent(api, session):
    deal, invoice, *_ = await make_invoice(api, session)
    contract, _ = await make_contract(api, session, deal)
    assert (await api.post(f"/sales/deals/{deal['id']}/send-package")).status_code == 409
    approved = await api.post(f"/sales/documents/{contract['id']}/decide", json={'approved': True})
    assert approved.status_code == 200, approved.text
    package = await api.post(f"/sales/deals/{deal['id']}/send-package", json={'invoice_id': invoice['id'], 'contract_id': contract['id']})
    assert package.status_code == 200, package.text
    p = package.json()
    assert p['sent'] is False and p['status'] == 'prepared'
    assert p['invoice_id'] == invoice['id'] and p['contract_id'] == contract['id']
    original = (await api.get(p['render_url'])).content
    repeated = (await api.post(f"/sales/deals/{deal['id']}/send-package")).json()
    assert repeated['package_id'] == p['package_id']
    revision = (await api.post(f"/sales/documents/{invoice['id']}/revision", json={
        'reason': 'New conditions', 'request_key': 'package-revision',
    })).json()
    assert (await api.post(f"/sales/documents/{revision['id']}/issue")).status_code == 200
    assert (await api.get(p['render_url'])).content == original
    newer = (await api.post(f"/sales/deals/{deal['id']}/send-package")).json()
    assert newer['package_id'] != p['package_id']
    assert (await api.get(p['render_url'])).content == original
    assert len((await session.execute(select(DocumentPackage))).scalars().all()) == 2


async def test_legacy_original_is_never_reconstructed(api, session):
    deal = Deal(number='LEGACY', title='Legacy', counterparty='Buyer', amount=240)
    session.add(deal)
    await session.flush()
    doc = DealDocument(deal_id=deal.id, kind='invoice', number='LEGACY-INV', amount=240, status='posted')
    session.add(doc)
    await session.commit()
    result = await api.get(f'/sales/documents/{doc.id}/render')
    assert result.status_code == 409 and 'оригинал не сохранён' in result.text
    listed = (await api.get(f'/sales/deals/{deal.id}/documents')).json()
    assert listed[0]['original_state'] == 'legacy_unavailable'
    assert doc.original_html is None


async def test_creation_retries_do_not_duplicate_document_or_events(api, session):
    deal, doc, *_ = await make_invoice(api, session)
    r = await api.post(f"/sales/deals/{deal['id']}/documents", json={'kind': 'invoice', 'request_key': 'invoice-original'})
    assert r.status_code == 201 and r.json()['id'] == doc['id']
    assert (await api.post(f"/sales/deals/{deal['id']}/documents", json={'kind': 'invoice'})).status_code == 409
    events = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == 'sales.document.posted'))).scalars().all()
    assert len(events) == 1
    assert events[0].payload['amount'] == '240.00'
    assert events[0].payload['payer_unp'] == '111111111'
    assert events[0].payload['content_sha256'] == doc['content_sha256']


@pytest.mark.parametrize('path,method,payload', [
    ('render', 'get', None), ('snapshot', 'get', None),
    ('revision', 'post', {'reason': 'Forbidden', 'request_key': 'forbidden-key'}),
    ('issue', 'post', None), ('decide', 'post', {'approved': True}),
])
async def test_foreign_documents_are_not_accessible(api, session, path, method, payload):
    deal, doc, *_ = await make_invoice(api, session)
    session.add(User(username='own-user', full_name='Own user', department='Продажи', role='sales',
                     employee_id=101, status='active', deal_visibility='own'))
    await session.commit()
    args = {'headers': {'X-User': 'own-user', 'X-User-Roles': 'sales'}}
    if payload is not None:
        args['json'] = payload
    result = await getattr(api, method)(f"/sales/documents/{doc['id']}/{path}", **args)
    assert result.status_code in {403, 404}


async def test_orm_cannot_overwrite_a_saved_original(api, session):
    _, body, *_ = await make_invoice(api, session)
    doc = await session.get(DealDocument, body['id'])
    doc.amount = Decimal('360')
    with pytest.raises(ValueError, match='неизменяем'):
        await session.flush()
    await session.rollback()


async def test_missing_price_cannot_issue_a_misleading_zero_invoice(api, session):
    deal = Deal(number='NO-PRICE', title='Missing price', counterparty='Buyer')
    sku = Sku(code='NO-PRICE', title='Unpriced', unit='шт')
    session.add_all([deal, sku])
    await session.flush()
    session.add(DealItem(deal_id=deal.id, sku_id=sku.id, qty=1))
    await session.commit()
    result = await api.post(f'/sales/deals/{deal.id}/documents', json={'kind': 'invoice'})
    assert result.status_code == 422


async def test_external_template_resources_cannot_change_an_original(api, session):
    deal = Deal(number='REMOTE', title='Remote asset', counterparty='Buyer')
    template = ContractTemplate(code='REMOTE', name='Remote', body='<img src="https://example.com/changing.png">')
    session.add_all([deal, template])
    await session.commit()
    result = await api.post(f'/sales/deals/{deal.id}/contract', json={'template_code': 'REMOTE'})
    assert result.status_code == 422

async def test_rejected_replacement_does_not_leave_two_active_contracts(api, session):
    deal, _, *_ = await make_invoice(api, session)
    old, _ = await make_contract(api, session, deal)
    assert (await api.post(f"/sales/documents/{old['id']}/decide", json={'approved': True})).status_code == 200
    second = (await api.post(f"/sales/documents/{old['id']}/revision", json={'reason': 'Second', 'request_key': 'second-contract'})).json()
    assert (await api.post(f"/sales/documents/{second['id']}/issue")).status_code == 200
    assert (await api.post(f"/sales/documents/{second['id']}/decide", json={'approved': False})).status_code == 200
    third = (await api.post(f"/sales/documents/{second['id']}/revision", json={'reason': 'Third', 'request_key': 'third-contract'})).json()
    assert third['supersedes_id'] == old['id']
    assert (await api.post(f"/sales/documents/{third['id']}/issue")).status_code == 200
    assert (await api.post(f"/sales/documents/{third['id']}/decide", json={'approved': True})).status_code == 200
    assert (await session.get(DealDocument, old['id'])).superseded_by_id == third['id']
    assert (await session.get(DealDocument, second['id'])).status == 'rejected'


async def test_draft_preview_does_not_freeze_live_data(api, session):
    deal, old, sku, cp, _ = await make_invoice(api, session)
    new = (await api.post(f"/sales/documents/{old['id']}/revision", json={'reason': 'Preview', 'request_key': 'preview-revision'})).json()
    before = await api.get(f"/sales/documents/{new['id']}/preview")
    assert before.status_code == 200, before.text
    assert 'ЧЕРНОВИК' in before.text
    assert (await session.get(DealDocument, new['id'])).original_html is None
    session.add(PriceQuote(sku_code=sku.code, counterparty=cp.name, price=Decimal('175')))
    await session.commit()
    after = await api.get(f"/sales/documents/{new['id']}/preview")
    assert after.content != before.content
    assert '420.00' in after.text
    issued = await api.post(f"/sales/documents/{new['id']}/issue")
    assert issued.json()['amount'] == 420
