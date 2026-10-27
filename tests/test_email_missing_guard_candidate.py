"""Missing or invalid frozen document references must not be queued."""
import pytest
from sqlalchemy import delete

from modules.sales import mail_routes
from modules.sales.models import DealDocument
from tests.test_sales_email_queue import prepared


@pytest.mark.parametrize('case', ['missing', 'missing_key', 'bad_id', 'other_deal', 'malformed'])
async def test_invalid_document_reference_cannot_be_confirmed(api, session, monkeypatch, case):
    email = await prepared(session)
    metadata = [dict(item) for item in email.attachments]
    if case == 'missing':
        await session.execute(delete(DealDocument).where(DealDocument.id == 123))
    elif case == 'missing_key':
        del metadata[0]['document_id']
    elif case == 'bad_id':
        metadata[0]['document_id'] = -1
    elif case == 'other_deal':
        doc = await session.get(DealDocument, 123)
        doc.deal_id = email.deal_id + 100
    else:
        metadata = ['invalid']
    email.attachments = metadata
    await session.commit()
    monkeypatch.setenv('AIOS_SALES_EMAIL_ENABLED', '1')
    monkeypatch.setattr(mail_routes, 'sender_or_503', lambda _core: 'crm@example.test')
    response = await api.post(f"/sales/deals/{email.deal_id}/emails/{email.id}/send",
                              headers={'X-User': 'director'})
    assert response.status_code == 409, response.text
    await session.refresh(email)
    assert email.status == 'prepared'

async def test_uploaded_file_remains_confirmable(api, session, monkeypatch):
    import base64

    existing = await prepared(session)
    monkeypatch.setenv('AIOS_SALES_EMAIL_ENABLED', '1')
    monkeypatch.setattr(mail_routes, 'sender_or_503', lambda _core: 'crm@example.test')
    payload = {
        'request_key': 'synthetic-upload-confirm', 'to': ['control@example.invalid'],
        'subject': 'Synthetic uploaded file', 'body': 'Synthetic only',
        'uploads': [{'filename': 'note.txt', 'content_type': 'text/plain',
                     'content_base64': base64.b64encode(b'synthetic').decode()}],
    }
    reply = await api.post(f"/sales/deals/{existing.deal_id}/emails/prepare", json=payload,
                           headers={'X-User': 'director'})
    assert reply.status_code == 201, reply.text
    assert reply.json()['attachments'][0]['document_id'] is None
    confirmed = await api.post(f"/sales/deals/{existing.deal_id}/emails/{reply.json()['id']}/send",
                               headers={'X-User': 'director'})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['status'] == 'queued'
    assert confirmed.json()['accepted_at'] is None


def test_empty_and_uploaded_attachment_metadata_is_valid():
    from modules.sales.mail_invoice_guard import document_references

    assert document_references([]) == []
    assert document_references([{'document_id': None, 'version': None, 'number': ''}]) == []
