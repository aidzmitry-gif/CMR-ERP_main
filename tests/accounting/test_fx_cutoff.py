"""A dated valuation must not consume entries posted after its effective date."""
from datetime import date
from uuid import uuid4

import pytest

from modules.accounting import fx_revaluation, service
from modules.accounting.models import Account, Policy
from modules.accounting.schemas import FxRevaluationInput
from tests.accounting.test_fx_revaluation import _foreign_posting, _policy


@pytest.mark.parametrize("future_configuration", [False, True])
async def test_midmonth_valuation_excludes_later_foreign_entries(db, book, future_configuration):
    policy_id = await _policy(db, book[0])
    earlier = _foreign_posting(policy_id, source="earlier")
    earlier.document_date = earlier.operation_date = earlier.posting_date = date(2026, 9, 1)
    for line in earlier.lines:
        line.rate_date = date(2026, 9, 1)
    await service.post(db, book[0], earlier, "tester")
    await service.post(db, book[0], _foreign_posting(policy_id, source="later"), "tester")
    if future_configuration:
        db.add(Account(organization_id=book[0], code="62", title="Future configuration",
            category="asset", valid_from=date(2026, 9, 20), required_dimensions=[],
            currency_tracking=False, quantity_tracking=False, cash=False, normative_ref="Synthetic"))
        db.add(Policy(organization_id=book[0], effective_from=date(2026, 9, 20),
            reference="Future policy", inventory_method="specific", allocation_basis="direct_cost",
            depreciation_method="straight_line", normative_reference="Synthetic only",
            normative_verified=True, currency_revaluation=None, approved_by="tester"))
    await db.commit()
    plan = await fx_revaluation.preview(db, book[0], "2026-09", FxRevaluationInput(
        request_key=uuid4(), policy_id=policy_id, posting_date=date(2026, 9, 15),
        expected_generation=2, rates=[{
            "currency": "USD", "rate": "3.20", "rate_scale": 1,
            "rate_date": "2026-09-15", "rate_source": "Synthetic dated rate",
        }], evidence="Synthetic as-of balance",
    ))
    assert plan["source_line_count"] == 2
    assert {row["account"]: row["book_balance"] for row in plan["adjustments"]} == {"60": "-300.00", "62": "300.00"}
