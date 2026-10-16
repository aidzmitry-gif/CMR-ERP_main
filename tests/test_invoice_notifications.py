import hashlib
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from core.domain.models import OutboxEvent
from core.services.eventbus import EventContext
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.invoice_notifications import (
    InvoiceNotification,
    on_invoice_cancelled_notification,
    on_invoice_expiring_notification,
)
from modules.sales.models import Deal, DealDocument


async def setup_invoice(session, *, email="buyer@example.com", status="issued"):
    deal = Deal(number="NOTIFY-DEAL", title="Notification", counterparty="Buyer")
    session.add(deal)
    await session.flush()
    original = "<html><body><h1>Synthetic invoice original</h1></body></html>"
    content = hashlib.sha256(original.encode("utf-8")).hexdigest()
    doc = DealDocument(
        deal_id=deal.id,
        kind="invoice",
        number="ERP-INV-NOTIFY",
        version=1,
        status=status,
        content_sha256=content,
        original_html=original,
        snapshot_json={"buyer": {"requisites": {"email": email}}},
    )
    session.add(doc)
    session.add(
        DealOwnership(
            deal_id=deal.id,
            organization_id=17,
            snapshot={},
            evidence="Notification test ownership",
            actor="tester",
        )
    )
    await session.flush()
    return deal, doc


def payload(deal, doc, **extra):
    return {
        "organization_id": 17,
        "deal_id": deal.id,
        "document_id": doc.id,
        "document_version": doc.version,
        "content_sha256": doc.content_sha256,
        "customer_notification": "requires_authorized_send",
        **extra,
    }


async def test_expiring_notification_is_pending_and_replay_is_idempotent(session):
    deal, doc = await setup_invoice(session, email="Buyer@Example.COM")
    event_payload = payload(deal, doc, expiry_state="expiring")

    first = await on_invoice_expiring_notification(
        event_payload, SimpleNamespace(session=session, event_id=101)
    )
    replay = await on_invoice_expiring_notification(
        event_payload, SimpleNamespace(session=session, event_id=101)
    )
    business_replay = await on_invoice_expiring_notification(
        event_payload, SimpleNamespace(session=session, event_id=102)
    )

    assert first.id == replay.id == business_replay.id
    assert first.state == "pending"
    assert first.recipient == "Buyer@example.com"
    assert first.business_key == f"expiring:{doc.id}:1"
    assert await session.scalar(select(func.count()).select_from(InvoiceNotification)) == 1


async def test_missing_snapshot_email_is_blocked_without_mail(session):
    deal, doc = await setup_invoice(session, email=None)
    row = await on_invoice_expiring_notification(
        payload(deal, doc, expiry_state="review_required"),
        SimpleNamespace(session=session, event_id=103),
    )

    assert row.state == "blocked"
    assert row.recipient is None
    assert row.reason == "recipient_email_missing_or_invalid"


async def test_cancelled_notification_uses_cancellation_identity(session):
    deal, doc = await setup_invoice(session, status="cancelled")
    row = await on_invoice_cancelled_notification(
        payload(deal, doc, cancellation_id="cancel-17", cancellation_digest="b" * 64, release_id="release-17"),
        SimpleNamespace(session=session, event_id=104),
    )

    assert row.event_type == "sales.invoice.cancelled"
    assert row.business_key == "cancelled:cancel-17"
    assert row.state == "pending"
    assert row.payload["release_id"] == "release-17"


async def test_notification_rejects_foreign_organization_and_changed_replay(session):
    deal, doc = await setup_invoice(session)
    event_payload = payload(deal, doc, expiry_state="expiring")
    with pytest.raises(ValueError, match="organization"):
        await on_invoice_expiring_notification(
            {**event_payload, "organization_id": 18},
            SimpleNamespace(session=session, event_id=105),
        )

    await on_invoice_expiring_notification(event_payload, SimpleNamespace(session=session, event_id=106))
    with pytest.raises(ValueError, match="different immutable content"):
        await on_invoice_expiring_notification(
            {**event_payload, "expiry_state": "review_required"},
            SimpleNamespace(session=session, event_id=106),
        )


async def test_notification_receipt_is_immutable(session):
    deal, doc = await setup_invoice(session)
    row = await on_invoice_expiring_notification(
        payload(deal, doc, expiry_state="expiring"),
        SimpleNamespace(session=session, event_id=107),
    )
    row.reason = "changed"
    with pytest.raises(ValueError, match="immutable"):
        await session.flush()
    await session.rollback()


async def test_registered_relay_persists_notification_atomically(session, services):
    deal, doc = await setup_invoice(session)
    session.add(
        OutboxEvent(
            event_type="sales.invoice.expiring",
            payload=payload(deal, doc, expiry_state="expiring"),
        )
    )
    await session.flush()
    count = await services.event_bus.relay_once(
        session, EventContext(session=session, services=services)
    )

    assert count == 1
    row = await session.scalar(select(InvoiceNotification))
    assert row is not None and row.event_id > 0


async def test_notification_register_is_scoped_to_visible_deal(api, session):
    deal, doc = await setup_invoice(session)
    row = await on_invoice_expiring_notification(
        payload(deal, doc, expiry_state="expiring"),
        SimpleNamespace(session=session, event_id=108),
    )
    await session.commit()

    response = await api.get(f"/sales/deals/{deal.id}/invoice-notifications")
    assert response.status_code == 200, response.text
    assert response.json()[0]["id"] == row.id
    assert response.json()[0]["recipient"] == "buyer@example.com"


async def test_notification_prepare_freezes_mail_for_explicit_confirmation(api, session, monkeypatch):
    deal, doc = await setup_invoice(session)
    row = await on_invoice_expiring_notification(
        payload(deal, doc, expiry_state="expiring"),
        SimpleNamespace(session=session, event_id=109),
    )
    await session.commit()
    config = api._transport.app.state.core.services.config
    config.smtp_host = "127.0.0.1"
    config.smtp_from = "crm@example.test"
    config.smtp_tls = False
    async def fake_pdf(source):
        return b"%PDF-1.4 synthetic notification"
    monkeypatch.setattr("modules.sales.mail_pdf.pdf", fake_pdf)

    endpoint = f"/sales/deals/{deal.id}/invoice-notifications/{row.id}/prepare-email"
    first = await api.post(endpoint)
    second = await api.post(endpoint)

    assert first.status_code == second.status_code == 201, (first.status_code, first.text, second.status_code, second.text)
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "prepared"
    assert first.json()["to"] == ["buyer@example.com"]
    assert first.json()["attachments"][0]["document_id"] == doc.id


async def test_blocked_notification_cannot_prepare_mail(api, session):
    deal, doc = await setup_invoice(session, email=None)
    row = await on_invoice_expiring_notification(
        payload(deal, doc, expiry_state="expiring"),
        SimpleNamespace(session=session, event_id=110),
    )
    await session.commit()
    response = await api.post(
        f"/sales/deals/{deal.id}/invoice-notifications/{row.id}/prepare-email"
    )
    assert response.status_code == 409


async def test_expiring_prepare_refuses_a_paid_invoice(api, session):
    deal, doc = await setup_invoice(session)
    row = await on_invoice_expiring_notification(
        payload(deal, doc, expiry_state="expiring"),
        SimpleNamespace(session=session, event_id=111),
    )
    doc.status = "paid"
    await session.commit()
    response = await api.post(
        f"/sales/deals/{deal.id}/invoice-notifications/{row.id}/prepare-email"
    )
    assert response.status_code == 409
