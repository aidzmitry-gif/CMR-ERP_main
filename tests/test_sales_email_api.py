import base64

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.domain.models import User
from modules.sales import mail_routes
from modules.sales.mail_models import OutgoingEmail
from modules.sales.mail_queue import claim, deliver
from modules.sales.mail_transport import SMTPResult
from modules.sales.models import Deal, DealDocument
from tests.test_sales_email_queue import prepared
from tests.test_sales_email_transport import settings

DIRECTOR_HEADERS = {"X-User": "director"}


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
    assert "Отдел продаж microchips.by" in body
    assert "order@microchips.by" in body
    assert first.json()["attachments"][0]["content_type"] == "text/plain"

    director = await session.scalar(select(User).where(User.username == "director"))
    director.full_name = "Позднее изменённое имя"
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
