from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.finance.reconcile import _erp_key, _onec_key, _safe_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 0.0),
        ("", 0.0),
        (12, 12.0),
        (12.5, 12.5),
        (" 1 234,50 ", 1234.5),
        (Decimal("10.25"), 10.25),
        ("not-money", 0.0),
    ],
)
def test_safe_amount_is_localized_and_fail_soft(raw, expected):
    assert _safe_amount(raw) == expected


def test_reconcile_keys_preserve_counterparty_dimension_and_empty_defaults():
    payment = SimpleNamespace(ref="INV-1", counterparty_ref=None)
    assert _erp_key(payment) == "INV-1|"
    assert _onec_key({"ref": "INV-1", "counterparty_ref": None}) == "INV-1|"
    assert _onec_key({}) == "|"


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows


class Session:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _statement):
        return Result(self.rows)


@pytest.mark.asyncio
async def test_reconcile_keeps_duplicate_buckets_and_reports_unmatched_rows():
    from modules.finance.reconcile import reconcile_with_onec

    payments = [
        SimpleNamespace(ref="INV-1", counterparty_ref="BY1", amount=Decimal("10.00")),
        SimpleNamespace(ref="INV-1", counterparty_ref="BY1", amount=Decimal("20.00")),
        SimpleNamespace(ref="INV-2", counterparty_ref="BY2", amount=Decimal("30.00")),
    ]

    class Gateway:
        async def fetch_payments(self):
            return [
                {"ref": "INV-1", "counterparty_ref": "BY1", "amount": "1 000,50"},
                {"ref": "INV-3", "counterparty_ref": "BY3", "amount": "bad"},
            ]

    result = await reconcile_with_onec(Session(payments), Gateway())
    assert result["source_available"] is True
    assert len(result["matched"]) == 1
    assert {row["ref"] for row in result["only_in_erp"]} == {"INV-1", "INV-2"}
    assert {row["ref"] for row in result["only_in_1c"]} == {"INV-3"}
    assert result["only_in_1c"][0]["amount"] == "0.00"


@pytest.mark.asyncio
async def test_reconcile_fail_soft_for_missing_or_broken_gateway():
    from modules.finance.reconcile import reconcile_with_onec

    payment = SimpleNamespace(ref="INV-1", counterparty_ref=None, amount=Decimal("3"))
    missing = await reconcile_with_onec(Session([payment]), object())
    assert missing["source_available"] is False and len(missing["only_in_erp"]) == 1

    class Broken:
        async def fetch_payments(self):
            raise RuntimeError("1c offline")

    broken = await reconcile_with_onec(Session([payment]), Broken())
    assert broken["source_available"] is False and len(broken["only_in_erp"]) == 1
