from datetime import date
from uuid import uuid4

import pytest

from modules.accounting import fx_revaluation, reports, service
from modules.accounting.schemas import FxRevaluationConfirmInput, FxRevaluationInput
from tests.accounting.test_fx_revaluation import _foreign_posting, _policy


@pytest.mark.parametrize("start,end,movement_group", [
    (date(2026, 9, 15), date(2026, 9, 30), "movements"),
    (date(2026, 10, 1), date(2026, 10, 15), "opening_movements"),
])
async def test_report_keeps_verified_valuation_with_its_currency_position(db, book, start, end, movement_group):
    policy_id = await _policy(db, book[0])
    await service.post(db, book[0], _foreign_posting(policy_id), "tester")
    await db.commit()
    command = FxRevaluationInput(request_key=uuid4(), policy_id=policy_id,
        posting_date=date(2026, 9, 30), expected_generation=1, rates=[{
            "currency": "USD", "rate": "3.20", "rate_scale": 1,
            "rate_date": "2026-09-30", "rate_source": "Synthetic rate",
        }], evidence="Synthetic report attribution")
    plan = await fx_revaluation.preview(db, book[0], "2026-09", command)
    await fx_revaluation.confirm(db, book[0], "2026-09", FxRevaluationConfirmInput(
        **command.model_dump(), basis_digest=plan["basis_digest"], digest=plan["digest"]), "tester")
    await db.commit()
    result = await reports.report(db, book[0], start, end)
    positions = {row["account"]: row for row in result["trial_balance"] if row["account"] in {"60", "62"}}
    assert len([row for row in result["trial_balance"] if row["account"] in {"60", "62"}]) == 2
    assert positions["62"]["currency"] == "USD"
    assert positions["62"]["closing"] == "320.00"
    assert positions["62"]["original_closing"] == "100.00"
    assert positions["60"]["closing"] == "-320.00"
    assert positions["60"]["original_closing"] == "-100.00"
    valuation_lines = [row for row in result[movement_group] if row.get("valuation_only")]
    assert len(valuation_lines) == 2
    assert all(row["currency"] == "USD" and row["ledger_currency"] == "BYN" for row in valuation_lines)
    assert result["balance"]["difference"] == "0.00"
