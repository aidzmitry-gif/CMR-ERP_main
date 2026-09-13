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
