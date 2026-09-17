from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.finance.routes import _enrich, _safe_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("2026-09-17", date(2026, 9, 17)),
        ("2026-02-30", None),
        ("17.09.2026", None),
    ],
)
def test_safe_date_accepts_only_valid_iso_dates(raw, expected):
    assert _safe_date(raw) == expected


def _payment(**changes):
    values = {
        "id": 3,
        "ref": "СЧ-3",
        "amount": Decimal("100.50"),
        "status": "pending",
        "kind": "receivable",
        "due_date": date(2026, 9, 16),
        "paid_at": None,
        "deal_id": 9,
        "counterparty_ref": "42",
        "account_id": 5,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_enrich_projects_money_links_and_overdue_outstanding_balance():
    result = _enrich(_payment(), Decimal("40.25"), today=date(2026, 9, 17))

    assert result == {
        "id": 3,
        "ref": "СЧ-3",
        "amount": "100.50",
        "status": "pending",
        "kind": "receivable",
        "due_date": date(2026, 9, 16),
        "paid_at": None,
        "deal_id": 9,
        "counterparty_ref": "42",
        "account_id": 5,
        "outstanding": "60.25",
        "is_overdue": True,
    }


@pytest.mark.parametrize(
    ("status", "due_date", "today", "expected"),
    [
        ("partial", date(2026, 9, 17), date(2026, 9, 17), False),
        ("paid", date(2026, 9, 16), date(2026, 9, 17), False),
        ("pending", None, date(2026, 9, 17), False),
    ],
)
def test_enrich_overdue_requires_open_status_and_strictly_past_due_date(
    status, due_date, today, expected
):
    result = _enrich(_payment(status=status, due_date=due_date), Decimal("100.50"), today=today)

    assert result["outstanding"] == "0.00"
    assert result["is_overdue"] is expected
