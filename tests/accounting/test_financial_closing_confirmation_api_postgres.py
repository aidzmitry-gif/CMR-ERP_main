"""Committed public financial closing, independent of the browser preview."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.accounting import service
from modules.accounting.models import AccessGrant, Entry, FinancialCloseReceipt, Period
from tests.accounting.test_financial_closing_preview import post
from tests.accounting.test_financial_closing_preview_postgres import preview_pg  # noqa: F401
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_public_close_is_committed_replayable_and_chief_only(preview_pg, posting):  # noqa: F811
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    await post(pg.api, pg.prefix, posting, pg.policy, "expense", "702", "60", "100.00")
    preview = await pg.api.get(pg.preview)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    body = dict(request_key=str(uuid4()), expected_basis_digest=plan["basis_digest"],
                expected_generation=plan["period_generation"],
                evidence={step: "Synthetic review" for step in service.CLOSE_STEPS})
    endpoint = pg.preview.replace("-preview", "-confirm")
    result = await pg.api.post(endpoint, json=body)
    assert result.status_code == 201, result.text
    assert result.headers["cache-control"] == "private, no-store"
    repeated = await pg.api.post(endpoint, json=body)
    assert repeated.status_code == 201 and repeated.json() == result.json()
    assert (await pg.api.post(endpoint, json={**body, "expected_basis_digest": "0" * 64})).status_code == 422
    async with pg.factory() as session:
        assert await session.scalar(select(func.count()).select_from(FinancialCloseReceipt)) == 1
        assert await session.scalar(select(func.count()).select_from(Entry)) == 4
        assert await session.scalar(select(Period.closed).where(Period.organization_id == pg.org)) is True
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == pg.org).values(role="accountant"))
        await session.commit()
    assert (await pg.api.post(endpoint, json=body)).status_code == 403


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_public_close_commit_failure_rolls_back_all_changes(preview_pg, posting, monkeypatch):  # noqa: F811
    from modules.accounting import closing_commands

    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    result = await pg.api.get(pg.preview)
    assert result.status_code == 200, result.text
    plan = result.json()
    body = dict(request_key=str(uuid4()), expected_basis_digest=plan["basis_digest"],
                expected_generation=plan["period_generation"],
                evidence={step: "Synthetic review" for step in service.CLOSE_STEPS})
    original_confirm, original_commit = closing_commands.confirm, AsyncSession.commit

    async def mark(session, *args, **kwargs):
        receipt = await original_confirm(session, *args, **kwargs)
        session.info["reject_close_commit"] = True
        return receipt

    async def reject(session):
        if session.info.pop("reject_close_commit", False):
            raise ValueError("Synthetic closing commit failure")
        return await original_commit(session)

    monkeypatch.setattr(closing_commands, "confirm", mark)
    monkeypatch.setattr(AsyncSession, "commit", reject)
    response = await pg.api.post(pg.preview.replace("-preview", "-confirm"), json=body)
    assert response.status_code == 422, response.text
    async with pg.factory() as session:
        assert await session.scalar(select(func.count()).select_from(FinancialCloseReceipt)) == 0
        assert await session.scalar(select(func.count()).select_from(Entry)) == 1
        period = await session.scalar(select(Period).where(Period.organization_id == pg.org))
        assert period.closed is False
        assert period.closed_generation is None
        assert period.generation == plan["period_generation"]
    monkeypatch.setattr(closing_commands, "confirm", original_confirm)
    monkeypatch.setattr(AsyncSession, "commit", original_commit)
    retry = await pg.api.post(pg.preview.replace("-preview", "-confirm"), json=body)
    assert retry.status_code == 201, retry.text


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_public_close_rejects_late_data_and_foreign_book(preview_pg, posting):  # noqa: F811
    pg = preview_pg
    plan = (await pg.api.get(pg.preview)).json()
    body = dict(request_key=str(uuid4()), expected_basis_digest=plan["basis_digest"],
                expected_generation=plan["period_generation"],
                evidence={step: "Synthetic review" for step in service.CLOSE_STEPS})
    await post(pg.api, pg.prefix, posting, pg.policy, "late-income", "62", "701", "1.00")
    endpoint = pg.preview.replace("-preview", "-confirm")
    rejected = await pg.api.post(endpoint, json=body)
    assert rejected.status_code == 422, rejected.text
    assert "basis changed" in rejected.json()["detail"]
    foreign = endpoint.replace(f"/organizations/{pg.org}/", "/organizations/999999/")
    assert (await pg.api.post(foreign, json=body)).status_code == 403
    async with pg.factory() as session:
        assert await session.scalar(select(func.count()).select_from(FinancialCloseReceipt)) == 0
        assert await session.scalar(select(func.count()).select_from(Entry)) == 1
        assert await session.scalar(select(Period.closed).where(Period.organization_id == pg.org)) is False


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_concurrent_public_closing_returns_one_receipt(preview_pg, posting):  # noqa: F811
    import asyncio

    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    response = await pg.api.get(pg.preview)
    assert response.status_code == 200, response.text
    plan = response.json()
    body = dict(request_key=str(uuid4()), expected_basis_digest=plan["basis_digest"],
                expected_generation=plan["period_generation"],
                evidence={step: "Synthetic review" for step in service.CLOSE_STEPS})
    endpoint = pg.preview.replace("-preview", "-confirm")
    first, second = await asyncio.gather(pg.api.post(endpoint, json=body), pg.api.post(endpoint, json=body))
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json() == second.json()
    async with pg.factory() as session:
        assert await session.scalar(select(func.count()).select_from(FinancialCloseReceipt)) == 1
        assert await session.scalar(select(func.count()).select_from(Entry)) == 3
        assert await session.scalar(select(Period.closed).where(Period.organization_id == pg.org)) is True
