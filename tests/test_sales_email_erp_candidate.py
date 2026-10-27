
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, update

from core.services.auth import CurrentUser
from modules.accounting.models import AccessGrant
from modules.sales import mail_documents
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
from modules.sales.models import DealDocument
from tests.test_invoice_issuance import command, create, seed


@pytest.mark.parametrize("corruption", [None, "missing_receipt", "changed_receipt", "changed_original", "no_book_access", "cancelled"])
async def test_erp_invoice_email_requires_receipt_original_and_current_book(api, session, monkeypatch, corruption):
    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    reply = await create(api, ids, cmd)
    assert reply.status_code == 201, reply.text
    doc_id = reply.json()["document"]["id"]
    if corruption == "missing_receipt":
        await session.execute(delete(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc_id))
    elif corruption == "changed_receipt":
        await session.execute(update(InvoiceIssuanceReceipt).where(InvoiceIssuanceReceipt.document_id == doc_id).values(snapshot_digest="f" * 64))
    elif corruption == "changed_original":
        await session.execute(update(DealDocument).where(DealDocument.id == doc_id).values(original_html="invalid"))
    elif corruption == "no_book_access":
        await session.execute(delete(AccessGrant).where(AccessGrant.organization_id == ids["org"], AccessGrant.subject == "issuer"))
    elif corruption == "cancelled":
        await session.execute(update(DealDocument).where(DealDocument.id == doc_id).values(status="cancelled"))
    await session.commit()
    session.expire_all()
    async def pdf(_html):
        return b"%PDF-synthetic"
    monkeypatch.setattr(mail_documents, "pdf", pdf)
    core = api._transport.app.state.core
    user = CurrentUser(username="issuer", roles=["director"])
    options = await api.get(f"/sales/deals/{ids['deal']}/emails/options")
    assert options.status_code == 200, options.text
    option = next(item for item in options.json()["documents"] if item["id"] == doc_id)
    assert option["available"] is (corruption is None)
    if corruption is None:
        attached = await mail_documents.attachments_for(session, core, user, ids["deal"], [doc_id])
        assert len(attached) == 1 and attached[0].document_id == doc_id
        assert attached[0].content == b"%PDF-synthetic"
    else:
        with pytest.raises(HTTPException) as exc:
            await mail_documents.attachments_for(session, core, user, ids["deal"], [doc_id])
        assert exc.value.status_code == 409

@pytest.mark.parametrize('operation', ['options', 'attachment'])
async def test_invoice_status_rechecked_after_book_lock(api, session, monkeypatch, operation):
    """Simulate a cancellation committed while the caller waited for book authority."""
    ids, base = await seed(api, session)
    cmd, _ = await command(api, ids, base)
    reply = await create(api, ids, cmd)
    assert reply.status_code == 201, reply.text
    doc_id = reply.json()['document']['id']
    core = api._transport.app.state.core
    real_member = core.services.accounting.source_member

    async def cancel_before_lock_returns(current_session, org, user):
        result = await real_member(current_session, org, user)
        # Deliberately keep the already-loaded ORM object stale. This models the
        # visible state after a concurrent commit while the book lock was awaited.
        await current_session.execute(
            update(DealDocument).where(DealDocument.id == doc_id)
            .values(status='cancelled').execution_options(synchronize_session=False)
        )
        return result

    monkeypatch.setattr(core.services.accounting, 'source_member', cancel_before_lock_returns)
    user = CurrentUser(username='issuer', roles=['director'])
    if operation == 'options':
        options = await api.get(f"/sales/deals/{ids['deal']}/emails/options")
        assert options.status_code == 200, options.text
        selected = next(item for item in options.json()['documents'] if item['id'] == doc_id)
        assert selected['available'] is False
        assert selected['status'] == 'cancelled'
    else:
        async def unexpected_pdf(_source):
            raise AssertionError('Cancelled invoice must not reach PDF rendering')
        monkeypatch.setattr(mail_documents, 'pdf', unexpected_pdf)
        with pytest.raises(HTTPException) as exc:
            await mail_documents.attachments_for(session, core, user, ids['deal'], [doc_id])
        assert exc.value.status_code == 409
