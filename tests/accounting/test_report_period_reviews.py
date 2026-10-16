from datetime import date

import pytest

from modules.accounting.models import Period, Policy
from modules.accounting.reports import report


@pytest.mark.asyncio
async def test_multimonth_report_keeps_earlier_policy_review_visible(db, book):
    for month in ["2026-09", "2026-10"]:
        db.add(Period(organization_id=book[0], month=month, closed=True, generation=0))
    for month, verified in [(9, False), (10, True)]:
        db.add(Policy(organization_id=book[0], effective_from=date(2026, month, 1),
                      reference="Synthetic historical policy", inventory_method="specific", allocation_basis="direct_cost",
                      depreciation_method="straight_line", normative_reference="Synthetic review fixture",
                      normative_verified=verified, approved_by="tester"))
    await db.commit()
    october = await report(db, book[0], date(2026, 10, 1), date(2026, 10, 31))
    assert october["review_items"] == []
    combined = await report(db, book[0], date(2026, 9, 1), date(2026, 10, 31))
    assert combined["status"] == "preliminary"
    item = next(row for row in combined["review_items"] if row["code"] == "policy_normative_basis")
    assert item["count"] == 1
    assert item["months"] == ["2026-09"]


@pytest.mark.asyncio
async def test_report_requires_every_month_not_only_existing_closed_rows(db, book):
    for month in ["2026-09", "2026-11"]:
        db.add(Period(organization_id=book[0], month=month, closed=True, generation=0))
    await db.commit()
    combined = await report(db, book[0], date(2026, 9, 1), date(2026, 11, 30))
    assert combined["status"] == "preliminary"
    item = next(row for row in combined["review_items"] if row["code"] == "reporting_period_open")
    assert item["months"] == ["2026-10"]
    assert item["count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("start,end", [(date(2026, 9, 2), date(2026, 9, 30)), (date(2026, 9, 1), date(2026, 9, 15))])
async def test_partial_month_does_not_claim_completed_month_review(db, book, start, end):
    db.add(Period(organization_id=book[0], month="2026-09", closed=True, generation=0))
    await db.commit()
    result = await report(db, book[0], start, end)
    assert result["status"] == "preliminary"
    assert result["from"] == start.isoformat()
    assert result["to"] == end.isoformat()
    assert any(item["code"] == "partial_period_review" for item in result["review_items"])
