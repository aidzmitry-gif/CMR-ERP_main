from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.finance.aging import AR_KINDS, _bucket, _payments_outstanding, aging_buckets


class Result:
    def __init__(self, rows=(), pairs=()):
        self.rows = list(rows)
        self.pairs = list(pairs)

    def scalars(self):
        return self

    def all(self):
        return self.pairs if self.pairs else self.rows

    def __iter__(self):
        return iter(self.pairs)


class Session:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        (None, "no_due"),
        (date(2026, 9, 17), "current"),
        (date(2026, 9, 1), "1-30"),
        (date(2026, 7, 20), "31-60"),
        (date(2026, 7, 1), "61-90"),
        (date(2026, 1, 1), "90+"),
    ],
)
def test_bucket_boundaries_are_explicit(due, expected):
    assert _bucket(due, date(2026, 9, 17)) == expected


@pytest.mark.asyncio
async def test_aging_reports_ar_ap_outstanding_and_skips_fully_allocated_rows():
    today = date(2026, 9, 17)
    ar_open = SimpleNamespace(id=1, kind="receivable", status="pending", amount=Decimal("100"), due_date=today - timedelta(days=5))
    ar_paid = SimpleNamespace(id=2, kind="receivable", status="partial", amount=Decimal("50"), due_date=today)
    ap_open = SimpleNamespace(id=3, kind="freight", status="pending", amount=Decimal("40"), due_date=None)
    session = Session(
        Result([ar_open, ar_paid]),
        Result(pairs=[(1, Decimal("25")), (2, Decimal("50"))]),
        Result([ap_open]),
        Result(pairs=[]),
    )

    result = await aging_buckets(session, today)
    assert result["as_of"] == "2026-09-17"
    assert result["ar"]["buckets"]["1-30"] == "75.00"
    assert result["ar"]["buckets"]["current"] == "0.00"
    assert result["ar"]["total"] == "75.00"
    assert result["ap"]["buckets"]["no_due"] == "40.00"
    assert result["ap"]["total"] == "40.00"


@pytest.mark.asyncio
async def test_payments_outstanding_returns_empty_without_running_allocation_query():
    result = await _payments_outstanding(Session(Result([])), AR_KINDS)
    assert result == []
