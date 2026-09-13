"""Real proposal/API evidence for the read-only financial transfer calculation."""
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update

from modules.accounting import service
from modules.accounting.models import AccessGrant, Audit, Entry, Line, Period
from tests.accounting.test_financial_closing_preview import post, setup_policy
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_procurement_request_creation_postgres import schedule
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


@pytest_asyncio.fixture
async def preview_pg(issuance_pg, request):  # noqa: F811
    api, factory = issuance_pg
    response = await api.post("/accounting/organizations", json={"name": "Synthetic closing", "unp": "999999921"})
    assert response.status_code == 201, response.text
    org = response.json()["id"]
    prefix = f"/accounting/organizations/{org}"
    for code, category in [("62", "asset"), ("60", "liability")]:
        response = await api.post(prefix + "/accounts", json=dict(code=code, title="Synthetic " + code,
            category=category, required_dimensions=[], valid_from="2026-01-01", currency_tracking=False,
            quantity_tracking=False, cash=False, normative_ref="Synthetic only"))
        assert response.status_code == 201, response.text
    _, policy = await setup_policy(api, (org, None), year_end=10,
                                   normative_verified=getattr(request, "param", False))
    return SimpleNamespace(api=api, factory=factory, org=org, prefix=prefix, policy=policy,
        preview=prefix + "/periods/2026-10/financial-closing-preview", evidence={"locks": []})


async def counts(pg):
    async with pg.factory() as session:
        return {model.__name__: await session.scalar(select(func.count()).select_from(model))
                for model in (Entry, Line, Period, Audit)}


@pytest.mark.parametrize("income,expense,side,amount", [
    ("180.00", "100.00", "credit", "80.00"),
    ("80.00", "180.00", "debit", "100.00"),
    ("100.00", "100.00", None, None),
])
async def test_pg_preview_exact_math_is_read_only(preview_pg, posting, income, expense, side, amount):
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "synthetic-income", "62", "701", income)
    await post(pg.api, pg.prefix, posting, pg.policy, "synthetic-expense", "702", "60", expense)
    before = await counts(pg)
    response = await pg.api.get(pg.preview)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["confirmation_available"] is False and result["status"] == "preview_only"
    assert result["normative_verified"] is False
    assert result["source_line_count"] == 2 and len(result["monthly_lines"]) == 4
    if side:
        assert result["annual_lines"][-1] == dict(account="704", dimensions={}, side=side, amount=amount)
    else:
        assert result["annual_lines"] == []
    assert (await pg.api.get(pg.preview)).json() == result
    assert await counts(pg) == before


async def test_pg_preview_observes_committed_post_after_real_org_wait(preview_pg, posting, tmp_path):
    pg = preview_pg
    await post(pg.api, pg.prefix, posting, pg.policy, "base-income", "62", "701", "180.00")
    before = (await pg.api.get(pg.preview)).json()
    body = posting("concurrent-expense", "702", "60", "100.00", policy_id=pg.policy,
        document_date="2026-10-01", operation_date="2026-10-01", posting_date="2026-10-01").model_dump(mode="json")
    async with pg.factory() as session:
        pg.evidence["database"] = await session.scalar(text("SELECT current_database()"))
    try:
        results = await schedule(pg, ("POST", pg.prefix + "/entries", body), ("GET", pg.preview, None))
        assert [r["status"] for r in results] == [201, 200], results
        preview = results[1]["body"]
        assert preview["basis_digest"] != before["basis_digest"]
        assert preview["period_generation"] > before["period_generation"]
        assert preview["source_line_count"] == 2
        assert preview["annual_lines"][-1]["amount"] == "80.00"
        assert (await pg.api.get(pg.preview)).json() == preview
        assert (await counts(pg))["Entry"] == 2
    finally:
        (tmp_path / "financial-preview-lock-evidence.json").write_text(
            json.dumps(pg.evidence, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize("role", ["reader", "accountant", None])
async def test_pg_preview_requires_current_chief_grant(preview_pg, role):
    pg = preview_pg
    async with pg.factory() as session:
        await service.lock_organization(session, pg.org)
        grant = await session.scalar(select(AccessGrant).where(
            AccessGrant.organization_id == pg.org, AccessGrant.subject == "issuer"))
        assert grant is not None
        if role is None:
            await session.delete(grant)
        else:
            await session.execute(update(AccessGrant).where(AccessGrant.id == grant.id).values(role=role))
        await session.commit()
    before = await counts(pg)
    response = await pg.api.get(pg.preview)
    assert response.status_code == 403, response.text
    assert await counts(pg) == before
