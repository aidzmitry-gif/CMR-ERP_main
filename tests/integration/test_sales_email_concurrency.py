"""Real PostgreSQL row locking and durable queue restart; no SMTP traffic."""

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import undefer

from core.domain.models import OutboxEvent
from modules.sales.mail_models import EmailAttempt, OutgoingEmail
from modules.sales.mail_queue import Attachment, claim, prepare
from modules.sales.models import Deal
from tests.test_sales_email_queue import prepared


async def test_concurrent_workers_claim_each_message_once_after_engine_restart(postgres_url):
    engine = create_async_engine(postgres_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    batch = uuid4().hex
    ids = set()
    async with factory() as session:
        for index in range(8):
            email = await prepared(session, key=f"pg-{batch}-{index}", number=f"PG-{batch}-{index}")
            ids.add(email.id)
            email.status = "queued"
        await session.commit()
    await engine.dispose()

    restarted = create_async_engine(postgres_url, pool_size=8)
    restarted_factory = async_sessionmaker(restarted, expire_on_commit=False)

    async def worker():
        async with restarted_factory() as session:
            return await claim(session)

    try:
        results = await asyncio.gather(*(worker() for _ in range(16)))
        claimed = [result[0] for result in results if result]
        assert len(claimed) == len(set(claimed)) == 8
        assert set(claimed) == ids
        async with restarted_factory() as session:
            rows = (
                await session.scalars(select(OutgoingEmail).where(OutgoingEmail.id.in_(ids)))
            ).all()
            assert all(row.status == "sending" and row.attempt_count == 1 for row in rows)
            attempts = (
                await session.scalars(select(EmailAttempt).where(EmailAttempt.email_id.in_(ids)))
            ).all()
            assert len(attempts) == 8
    finally:
        await restarted.dispose()


async def test_concurrent_prepare_same_key_is_idempotent_and_conflicts_are_409(postgres_url):
    """The unique request key remains one durable MIME row under a real race."""
    engine = create_async_engine(postgres_url, pool_size=4)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    batch = uuid4().hex
    actor = f"g04-{batch}"
    key = f"pg-race-{batch}"
    number = f"PG-RACE-{batch}"
    attachment = Attachment(
        123,
        2,
        "INV-1",
        "a" * 64,
        "invoice-123-v2.pdf",
        b"%PDF-1.4 concurrent fixture",
    )

    async with factory() as session:
        deal = Deal(
            number=number, title="Concurrent email race", counterparty="Synthetic buyer"
        )
        session.add(deal)
        await session.commit()
        deal_id = deal.id
        outbox_before = await session.scalar(
            select(OutboxEvent.id).order_by(OutboxEvent.id.desc())
        )

    read_barrier = asyncio.Barrier(2)

    class BarrierSession(AsyncSession):
        """Synchronize both completed idempotency reads; no sleeps-only race."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._first_scalar = True

        async def scalar(self, statement, *args, **kwargs):
            if self._first_scalar:
                self._first_scalar = False
                result = await super().scalar(statement, *args, **kwargs)
                await read_barrier.wait()
                return result
            return await super().scalar(statement, *args, **kwargs)

    raced_factory = async_sessionmaker(engine, class_=BarrierSession, expire_on_commit=False)

    async def prepare_once():
        async with raced_factory() as session:
            return await prepare(
                session,
                deal_id=deal_id,
                actor=actor,
                key=key,
                sender="crm@example.test",
                to=["control@example.test"],
                cc=[],
                subject="Счёт № 1",
                body="Контрольный документ.",
                attachments=[attachment],
            )

    try:
        results = await asyncio.wait_for(
            asyncio.gather(prepare_once(), prepare_once()), timeout=30
        )
        assert results[0].id == results[1].id
        assert results[0].request_hash == results[1].request_hash
        assert results[0].status == results[1].status == "prepared"

        async with factory() as session:
            rows = (
                await session.scalars(
                    select(OutgoingEmail)
                    .options(undefer(OutgoingEmail.mime))
                    .where(
                        OutgoingEmail.created_by == actor,
                        OutgoingEmail.request_key == key,
                    )
                )
            ).all()
            assert len(rows) == 1
            assert rows[0].mime_sha256 == results[0].mime_sha256
            outbox_after = await session.scalar(
                select(OutboxEvent.id).order_by(OutboxEvent.id.desc())
            )
            assert outbox_after == outbox_before

        async with factory() as session:
            with pytest.raises(HTTPException) as exc:
                await prepare(
                    session,
                    deal_id=deal_id,
                    actor=actor,
                    key=key,
                    sender="crm@example.test",
                    to=["control@example.test"],
                    cc=[],
                    subject="Другая тема",
                    body="Контрольный документ.",
                    attachments=[attachment],
                )
            assert exc.value.status_code == 409
    finally:
        await engine.dispose()
