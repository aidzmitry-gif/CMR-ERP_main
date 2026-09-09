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


@pytest.fixture
def enabled_email(monkeypatch):
    monkeypatch.setenv("AIOS_SALES_EMAIL_ENABLED", "1")
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")


async def test_confirmation_is_idempotent_and_does_not_mean_sent(api, session, enabled_email):
    email = await prepared(session)
    endpoint = f"/sales/deals/{email.deal_id}/emails/{email.id}/send"
    first = await api.post(endpoint)
    second = await api.post(endpoint)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "queued"
    assert first.json()["accepted_at"] is None
    assert len((await session.scalars(select(OutgoingEmail))).all()) == 1
    assert (
        await api.get(f"/sales/deals/{email.deal_id}/emails/{email.id}/attachments/0")
    ).content.startswith(b"%PDF-")


async def test_history_and_confirmation_respect_own_deal(api, session, enabled_email):
    email = await prepared(session)
    deal = await session.get(Deal, email.deal_id)
    deal.owner_id = 202
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
    assert (await api.post(prefix + "/retry", json={"expected_attempt": 1})).status_code == 409
    payload = {"expected_attempt": 1, "acknowledge_possible_duplicate": True}
    result = await api.post(prefix + "/retry", json=payload)
    assert result.status_code == 200 and result.json()["status"] == "queued"
    assert (await api.post(prefix + "/retry", json=payload)).json()["status"] == "queued"
    await deliver(
        factory,
        settings(),
        *await claim(session),
        transport=lambda *a: SMTPResult("accepted", "smtp_accepted", 250),
    )
    assert (await api.post(prefix + "/retry", json=payload)).status_code == 409
    assert (await api.get(prefix)).json()["status"] == "accepted"


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
    assert (await api.post(url, json=payload)).status_code == 404
    doc.deal_id = email.deal_id
    await session.commit()
    response = await api.post(url, json=payload)
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
    response = await api.post(f"/sales/deals/{email.deal_id}/emails/prepare", json=payload)
    assert response.status_code == 422


async def test_feature_disabled_cannot_confirm(api, session, monkeypatch):
    monkeypatch.delenv("AIOS_SALES_EMAIL_ENABLED", raising=False)
    email = await prepared(session)
    response = await api.post(f"/sales/deals/{email.deal_id}/emails/{email.id}/send")
    assert response.status_code == 503
    await session.refresh(email)
    assert email.status == "prepared"
