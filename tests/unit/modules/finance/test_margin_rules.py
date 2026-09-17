from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.finance import margin


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar = scalar

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar

    def scalars(self):
        return self


class Session:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


def payment(kind, amount, deal_id=None, counterparty_ref=None):
    return SimpleNamespace(
        kind=kind, amount=amount, deal_id=deal_id, counterparty_ref=counterparty_ref
    )


def test_parse_items_and_row_handle_invalid_and_zero_values():
    assert margin._parse_items(None) == {}
    assert margin._parse_items("S-1:2,S-2:bad,no-colon,:3,S-1:4") == {
        "S-1": Decimal("4"),
    }
    row = margin._row("deal-1", {
        "receivable": Decimal("100"), "landed": Decimal("40"),
        "freight": Decimal("10"), "freight_refund": Decimal("-2"),
        "claim_refund": Decimal("5"),
    })
    assert row == {
        "key": "deal-1", "revenue": "100.00", "landed": "35.00",
        "freight": "8.00", "gross": "57.00", "pct": 57.0,
    }
    zero = margin._row(None, {kind: Decimal("0") for kind in margin._MARGIN_KINDS})
    assert zero["pct"] is None


@pytest.mark.asyncio
async def test_margin_groups_real_kinds_and_keeps_unattributed_last():
    rows = [
        payment("receivable", "100", deal_id=1),
        payment("landed", "40", deal_id=1),
        payment("freight", "10", deal_id=1),
        payment("freight_refund", "-2", deal_id=1),
        payment("claim_refund", "5", deal_id=1),
        payment("po_planned", "999", deal_id=1),
        payment("receivable", "10", deal_id=None),
    ]
    result = await margin.margin_by_deal(Session(Result(rows)))
    assert result["currency"] == "BYN"
    assert result["items"][0]["key"] == 1
    assert result["items"][0]["gross"] == "57.00"
    assert result["items"][-1]["key"] is None

    cp_result = await margin.margin_by_counterparty(
        Session(Result([payment("receivable", "20", counterparty_ref="CP-1")]))
    )
    assert cp_result["items"][0]["key"] == "CP-1"


@pytest.mark.asyncio
async def test_reconcile_margin_reports_facade_delta_and_fail_soft():
    facade = SimpleNamespace(
        last_landed_cost_batch=__import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            return_value={"S-1": {"unit_landed_cost_byn": "30"}, "S-2": None}
        )
    )
    session = Session(Result(scalar="100"), Result(scalar="70"), Result(scalar="5"), Result(scalar="4"))
    result = await margin.reconcile_deal_margin(
        session, facade, 7, {"S-1": Decimal("2"), "S-2": Decimal("1")}
    )
    assert result == {
        "deal_id": 7, "finance_landed": "70.00", "facade_landed": "60.00", "delta": "10.00",
        "revenue": "100.00", "gross_finance": "29.00", "level": "sku_aggregate",
        "source_facade_available": True, "currency": "BYN",
    }

    no_facade = await margin.reconcile_deal_margin(
        Session(Result(scalar="100"), Result(scalar="70"), Result(scalar="5"), Result(scalar="4")),
        None, 7, None,
    )
    assert no_facade["facade_landed"] is None
    assert no_facade["delta"] is None

    broken = SimpleNamespace(last_landed_cost_batch=__import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(side_effect=RuntimeError("offline")))
    failed = await margin.reconcile_deal_margin(
        Session(Result(scalar="0"), Result(scalar="0"), Result(scalar="0"), Result(scalar="0")),
        broken, 7, {"S-1": Decimal("1")},
    )
    assert failed["source_facade_available"] is False
