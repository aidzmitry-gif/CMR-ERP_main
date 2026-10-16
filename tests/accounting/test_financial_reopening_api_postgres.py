"""Public reopening reverses authenticated transfers rather than clearing a flag."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from modules.accounting.models import AccessGrant, Entry, FinancialReopenReceipt, Period
from tests.accounting.test_financial_closing_commands import close
from tests.accounting.test_financial_closing_preview import post
from tests.accounting.test_financial_closing_preview_postgres import preview_pg  # noqa: F401
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_reopen_reverses_package_and_replays_without_duplicates(preview_pg, posting):  # noqa: F811
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    async with pg.factory() as session:
        original_close, _ = await close(session, pg.org)
    prefix = pg.prefix + "/periods/2026-10"
    preview = await pg.api.get(prefix + "/financial-reopening-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["posted"] is False
    assert len(preview.json()["reversals"]) == 2
    assert preview.json()["periods"][0]["closed"] is True
    assert len(preview.json()["basis_digest"]) == 64
    async with pg.factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == 3
        assert await session.scalar(select(func.count()).select_from(FinancialReopenReceipt)) == 0
    body = {"request_key": str(uuid4()), "reason": "Synthetic correction approved",
            "expected_basis_digest": preview.json()["basis_digest"]}
    stale = await pg.api.post(prefix + "/financial-reopening-confirm", json={**body, "expected_basis_digest": "0" * 64})
    assert stale.status_code == 422, stale.text
    assert (await pg.api.post(prefix + "/reopen", json={"reason": body["reason"]})).status_code == 422
    response = await pg.api.post(prefix + "/financial-reopening-confirm", json=body)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["periods"][0]["closed"] is False
    repeated = await pg.api.post(prefix + "/financial-reopening-confirm", json=body)
    assert repeated.status_code == 201 and repeated.json() == response.json()
    old_closing_replay = await pg.api.post(prefix + "/financial-closing-confirm",
        json=original_close.model_dump(mode="json"))
    assert old_closing_replay.status_code == 201, old_closing_replay.text
    assert old_closing_replay.json()["closed"] is False
    async with pg.factory() as session:
        assert await session.scalar(select(func.count()).select_from(FinancialReopenReceipt)) == 1
        assert await session.scalar(select(func.count()).select_from(Entry)) == 5
        assert await session.scalar(select(func.count()).select_from(Entry).where(Entry.correction_of.is_not(None))) == 2
        assert await session.scalar(select(Period.closed).where(Period.organization_id == pg.org)) is False
    async with pg.factory() as session:
        await close(session, pg.org)
        before_replay = await session.scalar(select(func.count()).select_from(Entry))
    historical = await pg.api.post(prefix + "/financial-reopening-confirm", json=body)
    assert historical.status_code == 201, historical.text
    assert historical.json()["periods"][0]["closed"] is False
    assert historical.json()["current_periods"][0]["closed"] is True
    async with pg.factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == before_replay


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_later_closed_month_invalidates_reviewed_cascade(preview_pg, posting):  # noqa: F811
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    async with pg.factory() as session:
        await close(session, pg.org)
    prefix = pg.prefix + "/periods/2026-10"
    old = await pg.api.get(prefix + "/financial-reopening-preview")
    assert old.status_code == 200, old.text
    async with pg.factory() as session:
        await close(session, pg.org, "2026-11")
    body = {"request_key": str(uuid4()), "reason": "Synthetic reviewed cascade",
            "expected_basis_digest": old.json()["basis_digest"]}
    stale = await pg.api.post(prefix + "/financial-reopening-confirm", json=body)
    assert stale.status_code == 422, stale.text
    assert "basis changed" in stale.json()["detail"]
    async with pg.factory() as session:
        assert await session.scalar(select(func.count()).select_from(FinancialReopenReceipt)) == 0
        assert await session.scalar(select(func.count()).select_from(Period).where(Period.closed.is_(True))) == 2
    fresh = await pg.api.get(prefix + "/financial-reopening-preview")
    assert fresh.status_code == 200, fresh.text
    assert [row["month"] for row in fresh.json()["periods"]] == ["2026-10", "2026-11"]
    response = await pg.api.post(prefix + "/financial-reopening-confirm",
        json={**body, "expected_basis_digest": fresh.json()["basis_digest"]})
    assert response.status_code == 201, response.text
    assert len(response.json()["items"]) == 2
    assert all(not row["closed"] for row in response.json()["periods"])


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_failed_reopening_commit_preserves_closed_book(preview_pg, posting, monkeypatch):  # noqa: F811
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.accounting import closing_commands

    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    async with pg.factory() as session:
        await close(session, pg.org)
    prefix = pg.prefix + "/periods/2026-10"
    preview = await pg.api.get(prefix + "/financial-reopening-preview")
    assert preview.status_code == 200, preview.text
    body = {"request_key": str(uuid4()), "reason": "Synthetic correction approved",
            "expected_basis_digest": preview.json()["basis_digest"]}
    original, commit = closing_commands.confirm_reopening, AsyncSession.commit

    async def mark(session, *args, **kwargs):
        receipt = await original(session, *args, **kwargs)
        session.info["reject_reopening_commit"] = True
        return receipt

    async def reject(session):
        if session.info.pop("reject_reopening_commit", False):
            raise ValueError("Synthetic reopening commit rejection")
        return await commit(session)

    monkeypatch.setattr(closing_commands, "confirm_reopening", mark)
    monkeypatch.setattr(AsyncSession, "commit", reject)
    response = await pg.api.post(prefix + "/financial-reopening-confirm", json=body)
    assert response.status_code == 422, response.text
    async with pg.factory() as session:
        assert await session.scalar(select(func.count()).select_from(FinancialReopenReceipt)) == 0
        assert await session.scalar(select(func.count()).select_from(Entry)) == 3
        period = await session.scalar(select(Period).where(Period.organization_id == pg.org))
        assert period.closed is True
        assert period.generation == preview.json()["periods"][0]["generation"]
    monkeypatch.setattr(closing_commands, "confirm_reopening", original)
    monkeypatch.setattr(AsyncSession, "commit", commit)
    retry = await pg.api.post(prefix + "/financial-reopening-confirm", json=body)
    assert retry.status_code == 201, retry.text


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
async def test_reopening_access_and_concurrent_exact_requests(preview_pg, posting):  # noqa: F811
    import asyncio

    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", "180.00")
    async with pg.factory() as session:
        await close(session, pg.org)
    prefix = pg.prefix + "/periods/2026-10"
    preview = await pg.api.get(prefix + "/financial-reopening-preview")
    assert preview.status_code == 200, preview.text
    body = {"request_key": str(uuid4()), "reason": "Synthetic approved correction",
            "expected_basis_digest": preview.json()["basis_digest"]}
    endpoint = prefix + "/financial-reopening-confirm"
    foreign = endpoint.replace(f"/organizations/{pg.org}/", "/organizations/999999/")
    assert (await pg.api.post(foreign, json=body)).status_code == 403
    async with pg.factory() as session:
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == pg.org).values(role="accountant"))
        await session.commit()
    assert (await pg.api.get(prefix + "/financial-reopening-preview")).status_code == 403
    assert (await pg.api.post(endpoint, json=body)).status_code == 403
    async with pg.factory() as session:
        assert await session.scalar(select(func.count()).select_from(FinancialReopenReceipt)) == 0
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == pg.org).values(role="chief"))
        await session.commit()
    first, second = await asyncio.gather(pg.api.post(endpoint, json=body), pg.api.post(endpoint, json=body))
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json() == second.json()
    async with pg.factory() as session:
        assert await session.scalar(select(func.count()).select_from(FinancialReopenReceipt)) == 1
        assert await session.scalar(select(func.count()).select_from(Entry)) == 5
