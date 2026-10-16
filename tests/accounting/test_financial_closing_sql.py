"""Independent PostgreSQL closing calculation, installed only by the frozen proposal."""
import json

import pytest
from sqlalchemy import text

from modules.accounting.financial_closing import preview
from tests.accounting.test_financial_closing_preview import post
from tests.accounting.test_financial_closing_preview_postgres import preview_pg  # noqa: F401
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


@pytest.mark.parametrize("income,expense", [("180.00", "100.00"), ("80.00", "180.00"), ("100.00", "100.00")])
async def test_sql_calculation_matches_full_independent_python_basis(preview_pg, posting, income, expense):  # noqa: F811
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "income", "62", "701", income, department='Отдел "А"')
    await post(pg.api, pg.prefix, posting, pg.policy, "expense", "702", "60", expense)
    async with pg.factory() as session:
        calculated = await preview(session, pg.org, "2026-10", include_basis=True)
        basis = calculated["basis"]
        sql = await session.scalar(text("SELECT accounting.financial_close_calculation(:org,:month,ARRAY[]::integer[],:og,:pg)"),
            dict(org=pg.org, month="2026-10", og=basis["organization_generation"], pg=basis["period_generation"]))
        assert sql == basis
        assert await session.scalar(text("SELECT accounting.financial_sha(CAST(:body AS jsonb))"),
            {"body": json.dumps(sql, ensure_ascii=False)}) == calculated["basis_digest"]
