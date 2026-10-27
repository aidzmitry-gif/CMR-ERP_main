"""Invoice-email cancellation and immutable-original regression tests."""
import pytest
from sqlalchemy import select

from core.services.auth import CurrentUser
from modules.sales import mail_documents, mail_routes
from modules.sales.mail_models import EmailAttempt
from modules.sales.mail_queue import prepare
from modules.sales.models import DealDocument
from tests.test_invoice_cancellation import cancel_request
from tests.test_invoice_cancellation import prepared as prepared_invoice


async def setup_mail(api, session, monkeypatch):
    org, facts = await prepared_invoice(api, session)
    doc = await session.get(DealDocument, 1)
    core = api._transport.app.state.core
    user = CurrentUser(username='issuer', roles=['director'])

    async def pdf(_source):
        return b'%PDF-synthetic'

    monkeypatch.setattr(mail_documents, 'pdf', pdf)
    attachments = await mail_documents.attachments_for(session, core, user, doc.deal_id, [doc.id])
    email = await prepare(session, deal_id=doc.deal_id, actor='issuer', key='synthetic-guard',
        sender='crm@example.test', to=['control@example.invalid'], cc=[], subject='Synthetic invoice',
        body='Synthetic only', attachments=attachments)
    monkeypatch.setenv('AIOS_SALES_EMAIL_ENABLED', '1')
    monkeypatch.setattr(mail_routes, 'sender_or_503', lambda _core: 'crm@example.test')
    return org, facts, doc, email


async def test_cancelled_before_confirm_blocks_queue(api, session, monkeypatch):
    org, facts, doc, email = await setup_mail(api, session, monkeypatch)
    path, payload = await cancel_request(api, org, facts)
    cancelled = await api.post(path, json=payload)
    assert cancelled.status_code == 201, cancelled.text
    response = await api.post(f"/sales/deals/{doc.deal_id}/emails/{email.id}/send")
    assert response.status_code == 409, response.text
    await session.refresh(email)
    assert email.status == 'prepared'
    assert (await session.scalars(select(EmailAttempt))).all() == []


@pytest.mark.parametrize('status', ['queued', 'retry_wait', 'sending', 'uncertain'])
async def test_cancellation_rejects_active_or_unknown_invoice_mail(api, session, monkeypatch, status):
    org, facts, doc, email = await setup_mail(api, session, monkeypatch)
    queued = await api.post(f"/sales/deals/{doc.deal_id}/emails/{email.id}/send")
    assert queued.status_code == 200 and queued.json()['status'] == 'queued'
    email.status = status
    await session.commit()
    path, payload = await cancel_request(api, org, facts)
    cancelled = await api.post(path, json=payload)
    assert cancelled.status_code == 409, cancelled.text
    await session.refresh(doc)
    assert doc.status == 'issued'
    await session.refresh(email)
    assert email.status == status


async def test_delivered_history_does_not_block_cancellation(api, session, monkeypatch):
    org, facts, doc, email = await setup_mail(api, session, monkeypatch)
    email.status = 'accepted'
    await session.commit()
    path, payload = await cancel_request(api, org, facts)
    cancelled = await api.post(path, json=payload)
    assert cancelled.status_code == 201, cancelled.text
    assert cancelled.json()['customer_notification'] == 'not_sent'
    await session.refresh(email)
    assert email.status == 'accepted'

async def test_failed_email_cannot_retry_after_invoice_cancellation(api, session, monkeypatch):
    org, facts, doc, email = await setup_mail(api, session, monkeypatch)
    email.status, email.attempt_count = 'failed', 1
    await session.commit()
    path, payload = await cancel_request(api, org, facts)
    cancelled = await api.post(path, json=payload)
    assert cancelled.status_code == 201, cancelled.text
    response = await api.post(f"/sales/deals/{doc.deal_id}/emails/{email.id}/retry",
                              json={'expected_attempt': 1})
    assert response.status_code == 409, response.text
    await session.refresh(email)
    assert email.status == 'failed'

@pytest.mark.parametrize('attachments', [None, {}, ['invalid'], [{}], [{'document_id': -1}],
                                         [{'document_id': None, 'version': 1, 'number': 'INV'}]])
async def test_cancellation_fails_closed_for_malformed_queued_email(api, session, monkeypatch, attachments):
    org, facts, doc, email = await setup_mail(api, session, monkeypatch)
    email.status, email.attachments = 'queued', attachments
    await session.commit()
    path, payload = await cancel_request(api, org, facts)
    response = await api.post(path, json=payload)
    assert response.status_code == 409, response.text
    await session.refresh(doc)
    assert doc.status == 'issued'
