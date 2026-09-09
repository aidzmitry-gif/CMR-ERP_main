"""PostgreSQL receipts, racing assignments and snapshot triggers; synthetic mail only."""

import asyncio
import importlib
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from core.domain.models import AuditLog
from modules.sales import mail_queue, mail_routes
from modules.sales.mail_models import IncomingEmail, OutgoingEmail
from modules.sales.mail_queue import claim, deliver, now
from modules.sales.mail_transport import SMTPResult
from modules.sales.models import Deal
from tests.test_sales_email_queue import prepared
from tests.test_sales_email_transport import settings
from tests.test_sales_mail_routing import (
    DIRECTOR,
    ENDPOINT,
    payload_for,
    raw_message,
)
from tests.test_sales_mail_routing import (
    token_headers as token_headers,
)

pytestmark = pytest.mark.integration


def identity():
    return {"uid": int(uuid4().hex[:8], 16) or 1, "uidvalidity": int(uuid4().hex[:8], 16) or 1}


def session_factory(pg_app):
    return pg_app._transport.app.state.core.services.db.session_factory


@pytest.fixture(autouse=True)
def forbid_smtp(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("PostgreSQL routing tests cannot submit SMTP")
    monkeypatch.setattr(mail_queue, "submit", forbidden)


async def test_concurrent_receipts_have_one_raw_and_one_audit(pg_app, token_headers):
    payload = payload_for(raw_message(), **identity())
    results = await asyncio.gather(*(
        pg_app.post(ENDPOINT, json=payload, headers=token_headers) for _ in range(8)
    ))
    assert sorted(r.status_code for r in results) == [200] * 7 + [201]
    receipts = {r.json()["receipt_id"] for r in results}
    assert len(receipts) == 1
    rid = receipts.pop()
    conflict = await pg_app.post(
        ENDPOINT,
        json=payload_for(raw_message(sender="different@example.test"), uid=payload["uid"], uidvalidity=payload["uidvalidity"]),
        headers=token_headers,
    )
    assert conflict.status_code == 409
    async with session_factory(pg_app)() as session:
        assert await session.scalar(select(func.count()).select_from(IncomingEmail).where(IncomingEmail.id == rid)) == 1
        stored = await session.scalar(select(IncomingEmail.raw_sha256).where(IncomingEmail.id == rid))
        assert stored == payload["raw_sha256"]
        audits = (await session.scalars(select(AuditLog).where(
            AuditLog.entity_ref == rid, AuditLog.action == "sales.email.incoming_received"
        ))).all()
        assert len(audits) == 1


async def test_competing_assignment_has_one_winner_and_audit(pg_app, token_headers):
    payload = payload_for(raw_message(), **identity())
    response = await pg_app.post(ENDPOINT, json=payload, headers=token_headers)
    assert response.status_code == 201
    rid = response.json()["receipt_id"]
    async with session_factory(pg_app)() as session:
        deals = [Deal(number=f"PG-SEND-{uuid4().hex}", title="Synthetic", counterparty="Synthetic") for _ in range(2)]
        session.add_all(deals)
        await session.commit()
        ids = [deal.id for deal in deals]
    results = await asyncio.gather(*(
        pg_app.post(f"/sales/mail/inbox/{rid}/assign", json={"deal_id": deal_id}, headers=DIRECTOR)
        for deal_id in ids
    ))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json()["deal_id"] for r in results if r.status_code == 200)
    async with session_factory(pg_app)() as session:
        assert await session.scalar(select(IncomingEmail.deal_id).where(IncomingEmail.id == rid)) == winner
        audits = (await session.scalars(select(AuditLog).where(
            AuditLog.action == "sales.email.incoming_assigned", AuditLog.entity_ref == f"deal:{winner}"
        ))).all()
        assert len([a for a in audits if a.detail["receipt_id"] == rid]) == 1


async def test_snapshot_triggers_reject_payload_edits_and_allow_queue_transitions(pg_app, token_headers, monkeypatch):
    monkeypatch.setenv("AIOS_SALES_EMAIL_ENABLED", "1")
    monkeypatch.setattr(mail_routes, "sender_or_503", lambda core: "crm@example.test")
    factory = session_factory(pg_app)
    async with factory() as session:
        original = await prepared(session, key=f"pg-original-{uuid4().hex}", number=f"PG-{uuid4().hex}")
        original.status, original.accepted_at = "accepted", now()
        await session.commit()
        deal_id, original_id = original.deal_id, original.message_id
    receipt = await pg_app.post(
        ENDPOINT, json=payload_for(raw_message(references=[original_id]), **identity()), headers=token_headers,
    )
    assert receipt.status_code == 201
    rid = receipt.json()["receipt_id"]
    result = await pg_app.post(f"/sales/deals/{deal_id}/emails/prepare", headers=DIRECTOR, json={
        "request_key": f"pg-reply-{uuid4().hex}", "to": ["control@example.test"],
        "subject": "Synthetic reply", "body": "Frozen reply", "reply_to_receipt_id": rid,
    })
    assert result.status_code == 201, result.text
    email_id = result.json()["id"]
    async with factory() as session:
        for model, row_id, change in (
            (IncomingEmail, rid, {"raw": b"changed"}),
            (IncomingEmail, rid, {"raw_sha256": "0" * 64}),
            (IncomingEmail, rid, {"headers": {"from": ["forged@example.test"]}}),
            (OutgoingEmail, email_id, {"mime": b"changed"}),
            (OutgoingEmail, email_id, {"body": "changed"}),
            (OutgoingEmail, email_id, {"reply_to_receipt_id": None}),
        ):
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(update(model).where(model.id == row_id).values(**change))
    confirmation = await pg_app.post(f"/sales/deals/{deal_id}/emails/{email_id}/send", headers=DIRECTOR)
    assert confirmation.status_code == 200 and confirmation.json()["status"] == "queued"
    async with factory() as session:
        claimed = await claim(session)
    assert claimed and claimed[0] == email_id
    await deliver(factory, settings(), *claimed, transport=lambda *args: SMTPResult("accepted", "synthetic_accepted", 250))
    detail = await pg_app.get(f"/sales/deals/{deal_id}/emails/{email_id}", headers=DIRECTOR)
    assert detail.status_code == 200
    assert detail.json()["status"] == "accepted" and detail.json()["attempt_count"] == 1
    assert detail.json()["reply_to_receipt_id"] == rid


async def test_downgrade_with_originals_refuses_before_any_drop(pg_app, token_headers):
    response = await pg_app.post(ENDPOINT, json=payload_for(raw_message(), **identity()), headers=token_headers)
    assert response.status_code == 201
    migration = importlib.import_module("migrations.versions.0120_sales_incoming_email")
    def downgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    async with session_factory(pg_app)() as session:
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                connection = await session.connection()
                await connection.run_sync(downgrade)
        assert await session.scalar(text("SELECT count(*) FROM sales.incoming_email")) > 0
        assert await session.scalar(text("""
            SELECT count(*) FROM pg_trigger
            WHERE tgname IN ('incoming_email_snapshot_immutable', 'outgoing_email_snapshot_immutable')
        """)) == 2
