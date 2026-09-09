from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import undefer

from modules.sales.mail_models import EmailAttempt, OutgoingEmail
from modules.sales.mail_queue import Attachment, claim, deliver, now, prepare, recover
from modules.sales.mail_transport import SMTPResult
from modules.sales.models import Deal
from tests.test_sales_email_transport import parse_message, receiver, settings


async def prepared(session, key="test-request", number="QUEUE-1"):
    deal = await session.scalar(select(Deal).where(Deal.number == number))
    if deal is None:
        deal = Deal(number=number, title="Synthetic email only", counterparty="Synthetic buyer")
        session.add(deal)
        await session.commit()
    return await prepare(
        session,
        deal_id=deal.id,
        actor="manager",
        key=key,
        sender="crm@example.test",
        to=["control@example.test"],
        cc=["copy@example.test"],
        subject="Счёт № 1",
        body="Контрольные документы.",
        attachments=[
            Attachment(
                123, 2, "INV-1", "a" * 64, "invoice-123-v2.pdf", b"%PDF-1.4 synthetic fixture"
            )
        ],
    )


async def test_prepare_is_not_send_and_request_idempotency(session):
    first = await prepared(session)
    again = await prepared(session)
    assert first.id == again.id and first.status == "prepared"
    assert await claim(session) is None
    assert len((await session.scalars(select(OutgoingEmail))).all()) == 1
    with pytest.raises(HTTPException) as exc:
        await prepared(session, number="OTHER-DEAL")
    assert exc.value.status_code == 409


async def test_actual_local_smtp_receives_fixed_attachments_and_headers(session):
    email = await prepared(session)
    email.status = "queued"
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    claimed = await claim(session)
    with receiver() as (config, received):
        await deliver(factory, config, *claimed)
    await session.refresh(email)
    assert email.status == "accepted" and email.accepted_at
    assert await claim(session) is None
    await session.refresh(email)
    parsed = parse_message(received[0])
    assert parsed["Message-ID"] == email.message_id
    assert str(parsed["To"]) == "control@example.test"
    assert str(parsed["Cc"]) == "copy@example.test"
    attachment = list(parsed.iter_attachments())[0]
    assert attachment.get_filename() == "invoice-123-v2.pdf"
    assert attachment.get_payload(decode=True) == b"%PDF-1.4 synthetic fixture"
    attempt = (await session.scalars(select(EmailAttempt))).one()
    assert attempt.smtp_code == 250 and attempt.status == "accepted"


async def test_retries_are_bounded_and_other_messages_continue(session):
    first = await prepared(session)
    second = await prepared(session, key="request-2", number="QUEUE-2")
    first.status = second.status = "queued"
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    submitted = []

    def transient(*args):
        submitted.append(args[-1])
        return SMTPResult("retry_wait", "connection_error")

    await deliver(factory, settings(), *await claim(session), transport=transient)
    claimed_second = await claim(session)
    assert claimed_second[0] == second.id
    await deliver(
        factory,
        settings(),
        *claimed_second,
        transport=lambda *a: SMTPResult("accepted", "smtp_accepted", 250),
    )
    for _ in range(3):
        await session.refresh(first)
        assert first.status == "retry_wait"
        first.next_attempt_at = now() - timedelta(seconds=1)
        await session.commit()
        await deliver(factory, settings(), *await claim(session), transport=transient)
    await session.refresh(first)
    assert first.status == "failed" and first.attempt_count == 4
    assert len(submitted) == 4 and len(set(submitted)) == 1
    assert await claim(session) is None


async def test_restart_after_claim_is_uncertain_and_not_retried(session):
    email = await prepared(session)
    email.status = "queued"
    await session.commit()
    await claim(session)
    await session.refresh(email)
    email.claimed_at = now() - timedelta(hours=1)
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as restarted:
        assert await recover(restarted) == 1
        assert await claim(restarted) is None
    await session.refresh(email)
    assert email.status == "uncertain"


async def test_unknown_smtp_result_does_not_retry(session):
    email = await prepared(session)
    email.status = "queued"
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    with receiver(drop_after_data=True) as (config, messages):
        await deliver(factory, config, *await claim(session))
    await session.refresh(email)
    assert email.status == "uncertain" and len(messages) == 1
    assert await claim(session) is None


async def test_corrupt_mime_never_reaches_transport(session):
    email = await prepared(session)
    email.status = "queued"
    email.mime = b"tampered"
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)

    def forbidden(*a):
        raise AssertionError("Do not send corrupt MIME")

    await deliver(factory, settings(), *await claim(session), transport=forbidden)
    await session.refresh(email)
    assert email.status == "failed" and email.last_reason == "mime_integrity_error"


async def test_claimed_message_cannot_be_claimed_twice(session):
    email = await prepared(session)
    email.status = "queued"
    await session.commit()
    assert await claim(session)
    assert await claim(session) is None


async def test_stored_mime_survives_new_session(session):
    email = await prepared(session)
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as restarted:
        stored = await restarted.scalar(select(OutgoingEmail).options(undefer(OutgoingEmail.mime)))
        assert stored.mime_sha256 == email.mime_sha256 and stored.mime.startswith(b"From:")


async def test_commit_failure_after_actual_smtp_acceptance_never_blindly_resends(session):
    email = await prepared(session)
    email.status = "queued"
    await session.commit()
    claimed = await claim(session)

    class CommitFailure(AsyncSession):
        async def commit(self):
            raise RuntimeError("Synthetic database outage after SMTP acceptance")

    broken = async_sessionmaker(session.bind, class_=CommitFailure, expire_on_commit=False)
    with receiver() as (config, received):
        with pytest.raises(RuntimeError, match="Synthetic database outage"):
            await deliver(broken, config, *claimed)
    assert len(received) == 1
    await session.refresh(email)
    assert email.status == "sending" and email.accepted_at is None
    email.claimed_at = now() - timedelta(hours=1)
    await session.commit()
    assert await recover(session) == 1
    assert await claim(session) is None
    await session.refresh(email)
    assert email.status == "uncertain" and email.attempt_count == 1


async def test_oversize_attachments_rejected_before_mime_creation(session):
    email = await prepared(session)
    with pytest.raises(HTTPException) as exc:
        await prepare(
            session,
            deal_id=email.deal_id,
            actor="manager",
            key="oversize",
            sender=email.sender,
            to=email.to,
            cc=[],
            subject="Synthetic",
            body="",
            attachments=[
                Attachment(
                    1, 1, "INV-1", "a" * 64, "invoice.pdf", b"%PDF-" + b"0" * (14 * 1024 * 1024)
                )
            ],
        )
    assert exc.value.status_code == 413
    assert len((await session.scalars(select(OutgoingEmail))).all()) == 1
