"""Membership authority must be current when an operation acquires the org lock."""
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text, update
from starlette.requests import Request

from core.services.auth import CurrentUser
from modules.accounting import service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import AccessGrant
from modules.accounting.routes import member
from tests.accounting.test_postgres import pg_book as pg_book
from tests.accounting.test_postgres import pg_factory as pg_factory

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("operation", ["source", "http_write", "http_chief"])
async def test_waiting_operation_rechecks_membership(pg_factory, pg_book, operation):
    org_id = pg_book[0]
    user = CurrentUser("tester", ["director"])
    ready = asyncio.Event()
    reader_pid = []

    async def waiting_operation():
        async with pg_factory() as session:
            # Retain an ORM object to also catch stale identity-map role checks.
            cached = await session.scalar(select(AccessGrant).where(
                AccessGrant.organization_id == org_id, AccessGrant.subject == "tester"))
            assert cached.role == "chief"
            reader_pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
            ready.set()
            try:
                if operation == "source":
                    await AccountingService().source_member(session, org_id, user)
                else:
                    request = Request({"type": "http", "method": "PUT",
                                       "path_params": {"org_id": org_id}, "headers": []})
                    ctx = await member(request, session, user)
                    if operation == "http_chief":
                        from modules.accounting.routes import chief
                        chief(ctx)
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code
            await session.rollback()
            return 200

    task = None
    try:
        async with pg_factory() as changer:
            await service.lock_organization(changer, org_id)
            changer_pid = await changer.scalar(text("SELECT pg_backend_pid()"))
            condition = (AccessGrant.organization_id == org_id, AccessGrant.subject == "tester")
            if operation == "source":
                await changer.execute(delete(AccessGrant).where(*condition))
            else:
                await changer.execute(update(AccessGrant).where(*condition).values(
                    role="reader" if operation == "http_write" else "accountant"))
            task = asyncio.create_task(waiting_operation())
            await asyncio.wait_for(ready.wait(), 5)

            async def blocked_on_changer():
                while changer_pid not in await changer.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": reader_pid[0]},
                ):
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(blocked_on_changer(), 5)
            await changer.commit()
        assert await asyncio.wait_for(task, 5) == 403
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
