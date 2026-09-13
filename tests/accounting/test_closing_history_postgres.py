"""Historical receipt lookup through actual app with PostgreSQL guards."""
# ruff: noqa: F811
from uuid import uuid4

import pytest
from sqlalchemy import update

from modules.accounting import closing_commands
from modules.accounting.models import AccessGrant
from modules.accounting.schemas import FinancialReopenInput
from tests.accounting.test_financial_closing_commands import close
from tests.accounting.test_financial_closing_preview import post
from tests.accounting.test_financial_closing_preview_postgres import (  # noqa: F401
    counts,
    preview_pg,
)
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


@pytest.mark.parametrize("preview_pg", [True], indirect=True)
@pytest.mark.parametrize("with_movements", [False, True])
async def test_reader_sees_verified_close_and_reopening(preview_pg, posting, with_movements):
    pg = preview_pg
    url = pg.prefix + "/periods/2026-10/financial-closing-history"
    assert (await pg.api.get(url)).json()["receipts"] == []
    if with_movements:
        await post(pg.api, pg.prefix, posting, pg.policy, "history-income", "62", "701", "180.00")
        await post(pg.api, pg.prefix, posting, pg.policy, "history-expense", "702", "60", "100.00")
    async with pg.factory() as session:
        _, receipt = await close(session, pg.org)
        receipt_id = receipt.id
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == pg.org).values(role="reader"))
        await session.commit()
    pg.api.headers["X-User-Roles"] = "finance"
    before = await counts(pg)
    response = await pg.api.get(url)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    result = response.json()
    assert result["period_closed"] is True
    assert len(result["receipts"]) == 1
    assert result["receipts"][0]["id"] == receipt_id
    assert (result["receipts"][0]["monthly_entry_id"] is not None) is with_movements
    assert (result["receipts"][0]["annual_entry_id"] is not None) is with_movements
    assert result["receipts"][0]["reopening"] is None
    assert await counts(pg) == before
    async with pg.factory() as session:
        await closing_commands.reopen(session, pg.org, "2026-10", FinancialReopenInput(
            request_key=uuid4(), reason="Synthetic reopening for history verification"), "tester")
        await session.commit()
    result = (await pg.api.get(url)).json()
    assert result["period_closed"] is False
    assert result["receipts"][0]["reopening"]["reason"] == "Synthetic reopening for history verification"
    if with_movements:
        for phase in ("monthly", "annual"):
            original_id = result["receipts"][0][phase + "_entry_id"]
            reversal_id = result["receipts"][0]["reopening"][phase + "_entry_id"]
            assert reversal_id != original_id
            original = await pg.api.get(pg.prefix + f"/entries/{original_id}")
            reversal = await pg.api.get(pg.prefix + f"/entries/{reversal_id}")
            assert original.status_code == reversal.status_code == 200
            assert reversal.json()["correction_of"] == original_id
    assert (await pg.api.get(url.replace(f"/organizations/{pg.org}/", "/organizations/999999/"))).status_code == 403
