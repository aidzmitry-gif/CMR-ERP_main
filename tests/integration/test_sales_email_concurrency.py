"""Real PostgreSQL row locking and durable queue restart; no SMTP traffic."""

import asyncio
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.sales.mail_models import EmailAttempt, OutgoingEmail
from modules.sales.mail_queue import claim
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
