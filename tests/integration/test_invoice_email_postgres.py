"""Actual book-lock ordering between invoice cancellation and email confirmation."""
import asyncio

import pytest
from sqlalchemy import text

from tests.integration.test_invoice_issuance_postgres import issuance_pg as issuance_pg
from tests.test_email_cancel_guard_candidate import setup_mail
from tests.test_invoice_cancellation import cancel_request


@pytest.mark.integration
@pytest.mark.parametrize("winner", ["send", "cancel"])
async def test_invoice_mail_and_cancellation_serialize_on_book(issuance_pg, monkeypatch, winner):
    api, factory = issuance_pg
    async with factory() as session:
        org, facts, doc, email = await setup_mail(api, session, monkeypatch)
        deal_id, email_id = doc.deal_id, email.id
    cancel_path, cancel_body = await cancel_request(api, org, facts)
    send_path = f"/sales/deals/{deal_id}/emails/{email_id}/send"
    gateway = api._transport.app.state.core.services.accounting
    acquired, release, started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    waiting_pid = None
    member, owner = gateway.source_member, gateway.source_owner_authority

    def intercept(original):
        async def call(session, organization_id, user):
            nonlocal waiting_pid
            task = asyncio.current_task().get_name()
            if task == "invoice-mail-loser":
                waiting_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                started.set()
            result = await original(session, organization_id, user)
            if task == "invoice-mail-winner" and not acquired.is_set():
                acquired.set()
                await release.wait()
            return result
        return call

    monkeypatch.setattr(gateway, "source_member", intercept(member))
    monkeypatch.setattr(gateway, "source_owner_authority", intercept(owner))

    async def command(kind):
        return await api.post(send_path) if kind == "send" else await api.post(cancel_path, json=cancel_body)

    first = asyncio.create_task(command(winner), name="invoice-mail-winner")
    second = None
    try:
        await asyncio.wait_for(acquired.wait(), 10)
        second = asyncio.create_task(command("cancel" if winner == "send" else "send"), name="invoice-mail-loser")
        await asyncio.wait_for(started.wait(), 10)
        async with factory() as observer:
            async def blocked():
                while not await observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": waiting_pid}):
                    assert not second.done(), "Competing operation bypassed the book lock"
                    await asyncio.sleep(0.02)
            await asyncio.wait_for(blocked(), 10)
        release.set()
        accepted, rejected = await asyncio.wait_for(asyncio.gather(first, second), 20)
        assert accepted.status_code == (200 if winner == "send" else 201), accepted.text
        assert rejected.status_code == 409, rejected.text
        if winner == "send":
            assert accepted.json()["status"] == "queued"
        else:
            assert accepted.json()["status"] == "cancelled"
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in (first, second) if t is not None), return_exceptions=True)
