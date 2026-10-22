import base64
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.domain.models import User
from modules.sales import documents, mail_profiles, mail_routes
from modules.sales.invoice_issuance import MODE, InvoiceIssuanceReceipt, verified_receipt
from modules.sales.mail_documents import eligible_original
from modules.sales.mail_models import OutgoingEmail
from modules.sales.mail_queue import claim, deliver
from modules.sales.mail_transport import SMTPResult
from modules.sales.models import Deal, DealDocument
from tests.test_invoice_issuance import command, create, seed
from tests.test_sales_email_queue import prepared
from tests.test_sales_email_transport import settings

DIRECTOR_HEADERS = {"X-User": "director", "X-User-Roles": "sales"}


async def native_mail_document(api, session, *, mode="stock"):
    """Issue through the real preview/create command; never synthesize a receipt."""
    await prepared(session)
    ids, base = await seed(api, session)
    if mode == "stock":
        cmd, _ = await command(api, ids, base)
    else:
        base["reserve_mode"] = mode
        preview = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
        assert preview.status_code == 200, preview.text
        value = preview.json()
        cmd = {**base, "request_key": "on-order-mail", "expected_document_version": value["document_version"],
               "expected_basis_digest": value["basis_digest"], "allocations": [], "unreserved_confirmed": True}
    issued = await create(api, ids, cmd)
    assert issued.status_code == 201, issued.text
    document = await session.get(DealDocument, issued.json()["document"]["id"])
    assert await verified_receipt(session, document, ids["org"]) is not None
    return document


async def issued_mail_document(session, *, mode="stock", damage=None):
    email = await prepared(session)
    document = DealDocument(
        id=70001, deal_id=email.deal_id, kind="invoice", number="MAIL-ISSUED-1", status="issued",
        version=1, amount=Decimal("12.00"),
        issued_at=datetime(2026, 7, 1, 12), issued_by="director",
        original_html="<html><body>Synthetic immutable invoice</body></html>",
    )
    document.content_sha256 = documents.digest(document.original_html)
    document.snapshot_json = {
        "issuance_mode": MODE, "document_id": document.id, "deal_id": document.deal_id,
        "organization_id": 1, "version": document.version, "amount": "12.00", "reserve_mode": mode,
    }
    receipt = InvoiceIssuanceReceipt(
        document_id=document.id, deal_id=document.deal_id, organization_id=1,
        document_version=document.version, content_sha256=document.content_sha256,
        snapshot_digest=documents.digest(document.snapshot_json),
        reservation_digest="a" * 64 if mode == "stock" else None,
        request_key="synthetic-mail-issuance", request_hash="b" * 64,
        response={}, actor="director",
    )
    # Seed final stored facts before the first INSERT; never bypass immutable-row guards.
    if damage == "html":
        document.original_html += "changed"
    elif damage == "version":
        document.version += 1
    elif damage == "snapshot_digest":
        document.snapshot_json = {**document.snapshot_json, "unexpected": "changed"}
    elif damage == "organization":
        document.snapshot_json = {**document.snapshot_json, "organization_id": 2}
    elif damage == "malformed_snapshot":
        document.snapshot_json = ["invalid"]
    elif damage in {"cancelled", "draft"}:
        document.status = damage
    elif damage == "issued_contract":
        document.kind = "contract"
    elif damage == "generic_issued_invoice":
        document.snapshot_json = None
    elif damage == "missing_paid_receipt":
        document.status = "paid"
    session.add(document)
    if damage not in {"missing_issued_receipt", "missing_paid_receipt", "generic_issued_invoice"}:
        session.add(receipt)
    await session.commit()
    return document


@pytest.mark.parametrize("mode", ["stock", "on_order"])
async def test_native_issued_invoice_is_available_for_email(api, session, mode):
    document = await native_mail_document(api, session, mode=mode)
    assert await eligible_original(session, document) == document.original_html
    result = await api.get(
        f"/sales/deals/{document.deal_id}/emails/options", headers=DIRECTOR_HEADERS,
    )
    assert result.status_code == 200
    assert result.json()["documents"] == [{
        "id": document.id, "number": document.number, "kind": "invoice", "status": "issued",
        "version": 1, "superseded_by_id": None, "available": True,
    }]
    assert (await session.get(InvoiceIssuanceReceipt, document.id)).snapshot_digest == (
        documents.digest(document.snapshot_json)
    )


@pytest.mark.parametrize("kind", ["invoice", "contract"])
@pytest.mark.parametrize("status", ["posted", "paid"])
async def test_legacy_issued_document_remains_available_for_email(api, session, kind, status):
    email = await prepared(session)
    document = DealDocument(
        deal_id=email.deal_id, kind=kind, number="LEGACY-MAIL", status=status,
        issued_at=datetime(2026, 7, 1, 12), original_html="<p>Legacy original</p>",
    )
    document.content_sha256 = documents.digest(document.original_html)
    session.add(document)
    await session.commit()
    assert await eligible_original(session, document) == document.original_html
    result = await api.get(
        f"/sales/deals/{document.deal_id}/emails/options", headers=DIRECTOR_HEADERS,
    )
    assert result.status_code == 200
    assert result.json()["documents"][0]["available"] is True


@pytest.mark.parametrize("damage", [
    "missing_issued_receipt", "missing_paid_receipt", "html", "version", "snapshot_digest",
    "organization", "malformed_snapshot", "cancelled", "draft", "issued_contract", "generic_issued_invoice",
])
async def test_invalid_original_is_unavailable_and_cannot_prepare_email(
    api, session, monkeypatch, damage,
):
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")
    document = await issued_mail_document(session, damage=damage)
    prefix = f"/sales/deals/{document.deal_id}/emails"
    options = await api.get(prefix + "/options", headers=DIRECTOR_HEADERS)
    assert options.status_code == 200
    assert options.json()["documents"][0]["available"] is False
    previous = set((await session.scalars(select(OutgoingEmail.id))).all())
    result = await api.post(prefix + "/prepare", headers=DIRECTOR_HEADERS, json={
        "request_key": "invalid-original-" + damage,
        "document_ids": [document.id], "to": ["control@example.test"], "subject": "Synthetic",
    })
    assert result.status_code == 409
    assert set((await session.scalars(select(OutgoingEmail.id))).all()) == previous


async def test_native_invoice_email_options_and_prepare_keep_own_deal_scope(
    api, session, monkeypatch,
):
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")
    document = await native_mail_document(api, session)
    session.add(User(
        username="mail-owner", full_name="Synthetic owner", employee_id=101,
        department="Продажи", role="sales", status="active", deal_visibility="own",
    ))
    deal = await session.get(Deal, document.deal_id)
    deal.owner_id = 202
    await session.commit()
    headers = {"X-User": "mail-owner", "X-User-Roles": "sales"}
    prefix = f"/sales/deals/{document.deal_id}/emails"
    assert (await api.get(prefix + "/options", headers=headers)).status_code == 404
    assert (await api.post(prefix + "/prepare", headers=headers, json={
        "request_key": "foreign-native-mail", "document_ids": [document.id],
        "to": ["control@example.test"], "subject": "Synthetic",
    })).status_code == 404
    deal.owner_id = 101
    await session.commit()
    result = await api.get(prefix + "/options", headers=headers)
    assert result.status_code == 200 and result.json()["documents"][0]["available"] is True


@pytest.fixture
def enabled_email(monkeypatch):
    monkeypatch.setenv("AIOS_SALES_EMAIL_ENABLED", "1")
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")


async def test_confirmation_is_idempotent_and_does_not_mean_sent(api, session, enabled_email):
    email = await prepared(session)
    endpoint = f"/sales/deals/{email.deal_id}/emails/{email.id}/send"
    first = await api.post(endpoint, headers=DIRECTOR_HEADERS)
    second = await api.post(endpoint, headers=DIRECTOR_HEADERS)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "queued"
    assert first.json()["accepted_at"] is None
    assert len((await session.scalars(select(OutgoingEmail))).all()) == 1
    assert (
        await api.get(f"/sales/deals/{email.deal_id}/emails/{email.id}/attachments/0")
    ).content.startswith(b"%PDF-")


async def test_history_and_confirmation_respect_own_deal(api, session, enabled_email):
    alice = User(
        username="alice",
        full_name="Alice",
        employee_id=101,
        department="Продажи",
        role="sales",
        status="active",
        deal_visibility="own",
    )
    session.add(alice)
    await session.flush()
    email = await prepared(session, actor="alice")
    deal = await session.get(Deal, email.deal_id)
    deal.owner_id = 202
    await session.commit()
    headers = {"X-User": "alice", "X-User-Roles": "sales"}
    prefix = f"/sales/deals/{email.deal_id}/emails"
    for suffix in ("", "/options", f"/{email.id}", f"/{email.id}/attachments/0"):
        assert (await api.get(prefix + suffix, headers=headers)).status_code == 404
    assert (await api.post(prefix + f"/{email.id}/send", headers=headers)).status_code == 404
    assert (
        await api.post(prefix + f"/{email.id}/retry", json={"expected_attempt": 1}, headers=headers)
    ).status_code == 404
    deal.owner_id = 101
    await session.commit()
    assert (await api.get(prefix, headers=headers)).status_code == 200
    assert (await api.post(prefix + f"/{email.id}/send", headers=headers)).status_code == 200


async def test_non_sales_cannot_send(api, session, enabled_email):
    email = await prepared(session)
    response = await api.post(
        f"/sales/deals/{email.deal_id}/emails/{email.id}/send", headers={"X-User-Roles": "guest"}
    )
    assert response.status_code == 403


async def test_manual_retry_unknown_requires_explicit_duplicate_ack(api, session, enabled_email):
    email = await prepared(session)
    email.status = "queued"
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    await deliver(
        factory,
        settings(),
        *await claim(session),
        transport=lambda *a: SMTPResult("uncertain", "response_unknown"),
    )
    await session.refresh(email)
    prefix = f"/sales/deals/{email.deal_id}/emails/{email.id}"
    assert (
        await api.post(prefix + "/retry", json={"expected_attempt": 1}, headers=DIRECTOR_HEADERS)
    ).status_code == 409
    payload = {"expected_attempt": 1, "acknowledge_possible_duplicate": True}
    result = await api.post(prefix + "/retry", json=payload, headers=DIRECTOR_HEADERS)
    assert result.status_code == 200 and result.json()["status"] == "queued"
    assert (
        await api.post(prefix + "/retry", json=payload, headers=DIRECTOR_HEADERS)
    ).json()["status"] == "queued"
    await deliver(
        factory,
        settings(),
        *await claim(session),
        transport=lambda *a: SMTPResult("accepted", "smtp_accepted", 250),
    )
    assert (await api.post(prefix + "/retry", json=payload, headers=DIRECTOR_HEADERS)).status_code == 409
    assert (await api.get(prefix, headers=DIRECTOR_HEADERS)).json()["status"] == "accepted"


async def test_prepare_rejects_foreign_document_and_unfrozen_legacy(api, session, monkeypatch):
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")
    email = await prepared(session)
    foreign = Deal(number="FOREIGN", title="Foreign", counterparty="Foreign")
    session.add(foreign)
    await session.flush()
    doc = DealDocument(deal_id=foreign.id, kind="invoice", number="X", status="posted")
    session.add(doc)
    await session.commit()
    payload = {
        "request_key": "prepare-test",
        "document_ids": [doc.id],
        "to": ["test@example.test"],
        "subject": "Test",
    }
    url = f"/sales/deals/{email.deal_id}/emails/prepare"
    assert (await api.post(url, json=payload, headers=DIRECTOR_HEADERS)).status_code == 404
    doc.deal_id = email.deal_id
    await session.commit()
    response = await api.post(url, json=payload, headers=DIRECTOR_HEADERS)
    assert response.status_code == 409 and "оригинала" in response.json()["detail"]


@pytest.mark.parametrize(
    "extra",
    [
        {"to": ["a@example.test\r\nBcc: x@evil.test"]},
        {"subject": "Test\nBcc:"},
        {"paths": ["/etc/passwd"]},
        {"attachments": ["https://evil.test/x.pdf"]},
    ],
)
async def test_prepare_input_validation_precedes_attachment_render(
    api, session, monkeypatch, extra
):
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")
    email = await prepared(session)
    payload = {
        "request_key": "prepare-test",
        "document_ids": [1],
        "to": ["test@example.test"],
        "subject": "Test",
        **extra,
    }
    response = await api.post(
        f"/sales/deals/{email.deal_id}/emails/prepare", json=payload, headers=DIRECTOR_HEADERS
    )
    assert response.status_code == 422


async def test_feature_disabled_cannot_confirm(api, session, monkeypatch):
    monkeypatch.delenv("AIOS_SALES_EMAIL_ENABLED", raising=False)
    email = await prepared(session)
    response = await api.post(
        f"/sales/deals/{email.deal_id}/emails/{email.id}/send", headers=DIRECTOR_HEADERS
    )
    assert response.status_code == 503
    await session.refresh(email)
    assert email.status == "prepared"


async def test_prepare_upload_freezes_signature_and_is_idempotent(api, session, monkeypatch):
    monkeypatch.setattr(mail_profiles, "SIGNATURE_DEPARTMENT", "Synthetic sales department")
    monkeypatch.setattr(mail_profiles, "SIGNATURE_EMAIL", "signature@example.test")
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")
    email = await prepared(session)
    payload = {
        "request_key": "upload-request",
        "to": ["test@example.test"],
        "subject": "Plain message",
        "body": "Добрый день",
        "uploads": [
            {
                "filename": "note.txt",
                "content_type": "text/plain",
                "content_base64": base64.b64encode("Привет".encode()).decode(),
            }
        ],
    }
    url = f"/sales/deals/{email.deal_id}/emails/prepare"
    first = await api.post(url, json=payload, headers=DIRECTOR_HEADERS)
    assert first.status_code == 201
    body = first.json()["body"]
    assert "Synthetic sales director" in body
    assert "Synthetic sales director\nSynthetic sales department\nsignature@example.test" in body
    assert first.json()["attachments"][0]["content_type"] == "text/plain"

    director = await session.scalar(select(User).where(User.username == "director"))
    director.full_name = "Позднее изменённое имя"
    monkeypatch.setattr(mail_profiles, "SIGNATURE_EMAIL", "changed@example.test")
    await session.commit()
    again = await api.post(url, json=payload, headers=DIRECTOR_HEADERS)
    assert again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert again.json()["body"] == body
    changed = {**payload, "body": "Другой текст"}
    assert (await api.post(url, json=changed, headers=DIRECTOR_HEADERS)).status_code == 409

    attachment = await api.get(
        f"/sales/deals/{email.deal_id}/emails/{first.json()['id']}/attachments/0",
        headers=DIRECTOR_HEADERS,
    )
    assert attachment.status_code == 200
    assert attachment.headers["content-type"].startswith("text/plain")
    assert attachment.headers["content-disposition"].startswith("attachment;")
    assert attachment.headers["x-content-type-options"] == "nosniff"




async def test_prepare_rejects_empty_body_without_attachments_before_signature(api, session, monkeypatch):
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")
    email = await prepared(session)
    response = await api.post(
        f"/sales/deals/{email.deal_id}/emails/prepare",
        json={
            "request_key": "empty-body",
            "to": ["test@example.test"],
            "subject": "Empty",
            "body": "   ",
        },
        headers=DIRECTOR_HEADERS,
    )
    assert response.status_code == 422
    assert "текст" in response.json()["detail"]


async def test_missing_profile_is_explicit_in_options_and_prepare(api, session, monkeypatch):
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")
    email = await prepared(session)
    headers = {"X-User": "unlinked", "X-User-Roles": "director"}
    options = await api.get(f"/sales/deals/{email.deal_id}/emails/options", headers=headers)
    assert options.status_code == 200
    assert options.json()["signature_preview"] is None
    assert options.json()["signature_configuration_error"] == "Профиль отправителя не настроен"
    response = await api.post(
        f"/sales/deals/{email.deal_id}/emails/prepare",
        json={
            "request_key": "missing-profile",
            "to": ["test@example.test"],
            "subject": "Test",
            "body": "Body",
        },
        headers=headers,
    )
    assert response.status_code == 503


async def test_only_creator_can_confirm_visible_email(api, session, enabled_email):
    email = await prepared(session)
    session.add(
        User(
            username="alice",
            full_name="Alice",
            department="Продажи",
            role="sales",
            status="active",
        )
    )
    await session.commit()
    other = {"X-User": "alice", "X-User-Roles": "sales"}
    response = await api.post(
        f"/sales/deals/{email.deal_id}/emails/{email.id}/send", headers=other
    )
    assert response.status_code == 403
    assert (
        await api.post(
            f"/sales/deals/{email.deal_id}/emails/{email.id}/send", headers=DIRECTOR_HEADERS
        )
    ).status_code == 200
