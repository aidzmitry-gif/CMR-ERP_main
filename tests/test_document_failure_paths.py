"""Failure-path acceptance: originals survive invalid edits and integration retries."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from core.domain.models import OutboxEvent
from core.services.eventbus import OutboxEventBus
from modules.finance.document_versions import on_original_issued, on_original_superseded
from modules.finance.models import Payment
from modules.sales.documents import original, validate_static
from modules.sales.models import Deal, DealDocument, DocumentPackage
from tests.test_document_versions import make_contract, make_invoice


@pytest.mark.parametrize('html', [
    '<script>document.write(Date.now())</script>', '<p onclick="change()">x</p>',
    '<meta http-equiv="refresh" content="1">', '<style>@import "https://example.com/a.css";</style>',
    '<p style="background:u\\72l(https://example.com/x)">x</p>',
    '<p style="background:url(https://example.com/x)">x</p>',
    '<svg><animate attributeName="fill"/></svg>', '<a href="https://example.com">x</a>',
])
def test_non_static_forms_cannot_become_an_original(html):
    with pytest.raises(HTTPException) as exc:
        validate_static(html)
    assert exc.value.status_code == 422


def test_static_form_keeps_embedded_images_and_arbitrary_customer_text():
    validate_static('<meta charset="utf-8"><style>p {color: black}</style><p style="color:blue">Product url(123)</p><img src="data:image/png;base64,YWJj"><a href="#terms">Terms</a>')


async def test_original_integrity_and_history_deletion_are_enforced(api, session):
    _, body, *_ = await make_invoice(api, session)
    doc = await session.get(DealDocument, body['id'])
    # Deliberate SQL corruption simulates a damaged SQLite backup, bypassing ORM.
    await session.execute(update(DealDocument).where(DealDocument.id == doc.id).values(original_html='corrupted'))
    await session.commit()
    assert (await api.get(f"/sales/documents/{doc.id}/render")).status_code == 409
    assert (await api.get(f"/sales/documents/{doc.id}/snapshot")).status_code == 409
    await session.delete(doc)
    with pytest.raises(ValueError, match='нельзя удалить'):
        await session.flush()
    await session.rollback()


async def test_issue_identity_cannot_be_rewritten(api, session):
    _, body, *_ = await make_invoice(api, session)
    doc = await session.get(DealDocument, body['id'])
    doc.issued_by = 'someone else'
    with pytest.raises(ValueError, match='Историю выпуска'):
        await session.flush()
    await session.rollback()


async def test_package_integrity_and_exact_selected_versions(api, session):
    deal, invoice, *_ = await make_invoice(api, session)
    contract, _ = await make_contract(api, session, deal)
    assert (await api.get(f"/sales/deals/{deal['id']}/package/render")).status_code == 409
    assert (await api.post(f"/sales/documents/{contract['id']}/decide", json={'approved': True})).status_code == 200
    wrong = await api.post(f"/sales/deals/{deal['id']}/send-package", json={'invoice_id': contract['id']})
    assert wrong.status_code == 409
    saved = (await api.post(f"/sales/deals/{deal['id']}/send-package")).json()
    latest = await api.get(f"/sales/deals/{deal['id']}/package/render")
    assert latest.content == (await api.get(saved['render_url'])).content
    row = await session.get(DocumentPackage, saved['package_id'])
    row.original_html = 'changed'
    with pytest.raises(ValueError, match='пакет неизменяем'):
        await session.flush()
    await session.rollback()
    await session.execute(update(DocumentPackage).values(original_html='damaged'))
    await session.commit()
    assert (await api.get(saved['render_url'])).status_code == 409
    assert (await api.get(f"/sales/deals/{deal['id']}/package/render")).status_code == 409


async def test_failed_issue_does_not_retire_the_old_document(api, api_no_gateways, session):
    _, old, *_ = await make_invoice(api, session)
    new = (await api.post(f"/sales/documents/{old['id']}/revision", json={'reason': 'Retry gateway', 'request_key': 'gateway-retry'})).json()
    assert (await api_no_gateways.post(f"/sales/documents/{new['id']}/issue")).status_code == 503
    await session.rollback()
    assert (await session.get(DealDocument, old['id'])).superseded_by_id is None
    assert (await session.get(DealDocument, new['id'])).original_html is None
    assert (await api.post(f"/sales/documents/{new['id']}/issue")).status_code == 200


async def test_no_item_invoice_keeps_exact_agreed_gross_amount(api, session):
    deal = Deal(number='ROUND', title='Agreed service', counterparty='Buyer', amount=Decimal('0.03'))
    session.add(deal)
    await session.commit()
    result = await api.post(f'/sales/deals/{deal.id}/documents', json={'kind': 'invoice'})
    assert result.status_code == 201
    snap = (await api.get(f"/sales/documents/{result.json()['id']}/snapshot")).json()
    assert Decimal(snap['amount']) == Decimal('0.03')
    line = snap['items'][0]
    assert Decimal(line['net']) + Decimal(line['tax']) == Decimal('0.03')
    assert line['basis'] == 'agreed_gross_amount'


async def test_only_drafts_can_preview_and_rejected_candidates_cannot_issue(api, session):
    deal, inv, *_ = await make_invoice(api, session)
    assert (await api.get(f"/sales/documents/{inv['id']}/preview")).status_code == 409
    contract, _ = await make_contract(api, session, deal)
    row = await session.get(DealDocument, contract['id'])
    with pytest.raises(HTTPException) as exc:
        original(row, issued_only=True)
    assert exc.value.status_code == 409
    assert (await api.post(f"/sales/documents/{contract['id']}/revision", json={'reason':'Too early', 'request_key':'too-early'})).status_code == 409
    assert (await api.post(f"/sales/documents/{contract['id']}/decide", json={'approved': False})).status_code == 200
    assert (await api.post(f"/sales/documents/{contract['id']}/issue")).status_code == 409


async def test_missing_document_and_package_ids_cannot_expose_other_records(api):
    for path in ('render', 'snapshot', 'preview'):
        assert (await api.get(f'/sales/documents/999999/{path}')).status_code == 404
    assert (await api.post('/sales/documents/999999/issue')).status_code == 404
    assert (await api.get('/sales/packages/999999/render')).status_code == 404


async def test_finance_retries_out_of_order_replacement_and_keeps_paid_identity(api, session):
    _, doc, *_ = await make_invoice(api, session)
    payload = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == 'sales.document.posted'))).scalars().one().payload
    ctx = SimpleNamespace(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    replacement = dict(payload, replacement_document_id=987)
    with pytest.raises(ValueError, match='retry replacement'):
        await on_original_superseded(replacement, ctx)
    await on_original_issued(payload, ctx)
    await session.flush()
    payment = (await session.execute(select(Payment))).scalars().one()
    payment.status = 'paid'
    await on_original_superseded(replacement, ctx)
    await session.commit()
    assert payment.status == 'paid' and payment.entity_ref == f"document:{doc['id']}"
    conflicting = deepcopy(payload)
    conflicting['amount'] = '999.00'
    with pytest.raises(ValueError, match='conflicts'):
        await on_original_issued(conflicting, ctx)
    bad = deepcopy(payload)
    bad['amount'] = 240.0
    with pytest.raises(ValueError, match='exact money'):
        await on_original_issued(bad, ctx)


async def test_legacy_finance_records_require_unambiguous_identity(session):
    ctx = SimpleNamespace(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))
    legacy = {'document_id': 14, 'kind': 'invoice', 'number': 'OLD', 'amount': '20.00', 'deal_id': 44, 'replacement_document_id': 15}
    await on_original_superseded(legacy, ctx)  # No invented payment for an unknown legacy original.
    await on_original_issued(legacy, ctx)
    await session.flush()
    assert (await session.execute(select(Payment))).scalars().one().entity_ref is None
    await on_original_superseded(legacy, ctx)
    assert (await session.execute(select(Payment))).scalars().one().status == 'superseded'
    session.add(Payment(ref='OLD', amount=20, status='pending', deal_id=44))
    await session.flush()
    with pytest.raises(ValueError, match='ambiguous'):
        await on_original_superseded(legacy, ctx)
    await on_original_issued({'content_sha256': 'h', 'kind': 'contract'}, ctx)
    await on_original_superseded({'kind': 'contract'}, ctx)
    await on_original_issued({'content_sha256': 'h', 'kind': 'invoice'}, None)
    await on_original_superseded({'kind': 'invoice'}, None)
