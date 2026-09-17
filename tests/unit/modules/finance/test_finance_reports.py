from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.finance import (
    allocation,
    balance_sheet,
    cashflow,
    cashflow_dds,
    cost_center,
    pnl,
    summary,
)


class Result:
    def __init__(self, scalar=None, rows=()):
        self._scalar = scalar
        self._rows = list(rows)

    def scalar_one(self):
        return self._scalar

    def all(self):
        return self._rows

    def scalars(self):
        return self


class Session:
    def __init__(self, *results, account=None):
        self.results = list(results)
        self.account = account
        self.added = []

    async def execute(self, _statement):
        return self.results.pop(0)

    async def get(self, _model, _identity):
        return self.account

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_balance_sheet_aggregates_payables_and_optional_onec_values():
    onec = SimpleNamespace(
        fetch_bank_balance=AsyncMock(return_value={"balance": "12.345"}),
        fetch_balance_sheet=AsyncMock(return_value={"inventory": "7.8"}),
    )
    session = Session(Result("100"), Result("20"), Result("3"), Result("4"))

    result = await balance_sheet.get_balance_sheet(
        session, date(2026, 9, 17), SimpleNamespace(onec=onec)
    )

    assert result == {
        "as_of": "2026-09-17",
        "currency": "BYN",
        "accounts_receivable": "100.00",
        "cash": "12.34",
        "inventory_value": "7.80",
        "total_assets": "120.14",
        "accounts_payable": "20.00",
        "payroll_payable": "3.00",
        "tax_payable": "4.00",
        "total_liabilities": "27.00",
        "equity": "93.14",
    }
    onec.fetch_bank_balance.assert_awaited_once_with()
    onec.fetch_balance_sheet.assert_awaited_once_with(date(2026, 9, 17))


@pytest.mark.asyncio
async def test_balance_sheet_is_fail_soft_for_missing_gateway_and_bad_payloads():
    onec = SimpleNamespace(
        fetch_bank_balance=AsyncMock(side_effect=RuntimeError("offline")),
        fetch_balance_sheet=AsyncMock(side_effect=ValueError("bad payload")),
    )
    session = Session(Result("0"), Result("0"), Result("0"), Result("0"))

    result = await balance_sheet.get_balance_sheet(session, date(2026, 9, 17), SimpleNamespace(onec=onec))

    assert result["cash"] is None
    assert result["inventory_value"] is None
    assert result["total_assets"] == "0.00"
    assert result["equity"] == "0.00"


@pytest.mark.asyncio
async def test_cashflow_report_builds_breakdown_and_handles_bank_balance():
    onec = SimpleNamespace(fetch_bank_balance=AsyncMock(return_value="99.999"))
    session = Session(
        Result("100.1"),
        Result(rows=[("freight", "12.5"), ("landed", "7.25"), ("ignored", "900")]),
    )

    result = await cashflow_dds.cashflow_report(
        session, date(2026, 9, 1), date(2026, 9, 30), onec
    )

    assert result["period_from"] == "2026-09-01"
    assert result["period_to"] == "2026-09-30"
    assert result["inflows"] == "100.10"
    assert result["outflows"] == "19.75"
    assert result["net_cashflow"] == "80.35"
    assert result["bank_balance"] == "100.00"
    assert result["breakdown"]["freight"] == "12.50"
    assert result["breakdown"]["tax"] == "0.00"


@pytest.mark.asyncio
async def test_pnl_report_applies_refunds_and_optional_period():
    session = Session(
        Result(
            rows=[
                ("revenue_recognized", "1000"),
                ("landed", "400"),
                ("claim_refund", "50"),
                ("freight", "100"),
                ("freight_refund", "-20"),
                ("payroll", "100"),
                ("opex", "30"),
                ("tax", "20"),
                ("bank_fee", "5"),
            ]
        )
    )

    result = await pnl.pnl_report(session, date(2026, 9, 1), date(2026, 9, 30))

    assert result["revenue"] == "1000.00"
    assert result["cogs_net"] == "350.00"
    assert result["freight_net"] == "80.00"
    assert result["gross_profit"] == "650.00"
    assert result["operating_profit"] == "415.00"
    assert result["from_date"] == "2026-09-01"
    assert result["to_date"] == "2026-09-30"


@pytest.mark.asyncio
async def test_cashflow_forecast_supports_day_mode_account_filter_and_not_dated(monkeypatch):
    today = date(2026, 9, 17)
    wanted = SimpleNamespace(account_id=7, due_date=today)
    other = SimpleNamespace(account_id=8, due_date=today)
    undated = SimpleNamespace(account_id=7, due_date=None)

    async def outstanding(_session, kinds):
        if kinds == ("receivable",):
            return [(wanted, Decimal("10")), (other, Decimal("99")), (undated, Decimal("4"))]
        return [(wanted, Decimal("3")), (SimpleNamespace(account_id=7, due_date=today + timedelta(days=2)), Decimal("2"))]

    monkeypatch.setattr(cashflow, "_payments_outstanding", outstanding)
    account = SimpleNamespace(opening_balance="5.25")
    session = Session(Result("20"), Result("4"), account=account)

    result = await cashflow.cashflow_forecast(
        session, today=today, mode="day", days=3, account_id=7
    )

    assert result["mode"] == "day"
    assert result["bucket_size_days"] == 1
    assert result["opening_balance"] == "21.25"
    assert result["buckets"][0]["inflow"] == "10.00"
    assert result["buckets"][0]["outflow"] == "3.00"
    assert result["buckets"][2]["outflow"] == "2.00"
    assert result["not_dated"] == {"inflow": "4.00", "outflow": "0.00"}
    assert result["weeks"] == []


@pytest.mark.asyncio
async def test_cashflow_forecast_week_mode_has_alias_and_clamped_bucket_count(monkeypatch):
    today = date(2026, 9, 17)

    async def outstanding(_session, _kinds):
        return []

    monkeypatch.setattr(cashflow, "_payments_outstanding", outstanding)
    session = Session(Result("0"), Result("0"))

    result = await cashflow.cashflow_forecast(session, weeks=0, today=today, mode="week")

    assert result["bucket_size_days"] == 7
    assert len(result["buckets"]) == 1
    assert result["weeks"][0]["week_start"] == result["buckets"][0]["bucket_start"]


@pytest.mark.asyncio
async def test_finance_summary_calculates_margin_cash_and_zero_revenue():
    session = Session(
        Result(
            rows=[
                ("receivable", "100"),
                ("freight", "20"),
                ("freight_refund", "-5"),
                ("landed", "40"),
                ("claim_refund", "10"),
                ("po_planned", "999"),
            ]
        ),
        Result("80"),
    )
    result = await summary.finance_summary(session)

    assert result["margin"] == {
        "revenue": "100.00",
        "landed": "30.00",
        "landed_gross": "40.00",
        "claim_refund": "10.00",
        "freight": "15.00",
        "gross": "55.00",
        "pct": 55.0,
    }
    assert result["cash"]["inflow"] == "85.00"
    assert result["cash"]["outflow"] == "60.00"
    assert result["cash"]["net"] == "25.00"

    zero_session = Session(Result(rows=[]), Result("0"))
    zero = await summary.finance_summary(zero_session)
    assert zero["margin"]["pct"] is None


@pytest.mark.asyncio
async def test_cost_centers_skip_plans_and_sort_by_expense():
    rows = [
        SimpleNamespace(kind="receivable", amount="100", cost_center=None),
        SimpleNamespace(kind="claim_refund", amount="5", cost_center="Закупки"),
        SimpleNamespace(kind="landed", amount="40", cost_center=None),
        SimpleNamespace(kind="freight_refund", amount="-3", cost_center=None),
        SimpleNamespace(kind="other", amount="2", cost_center="Прочее"),
        SimpleNamespace(kind="po_planned", amount="999", cost_center=None),
    ]
    session = Session(Result(rows=rows))

    result = await cost_center.group_by_cost_center(session, date(2026, 9, 1), date(2026, 10, 1))

    assert result["from"] == "2026-09-01"
    assert result["to"] == "2026-10-01"
    assert result["centers"] == [
        {"name": "Закупки", "income": "5.00", "expense": "40.00"},
        {"name": "Прочее", "income": "0.00", "expense": "2.00"},
        {"name": "Продажи", "income": "100.00", "expense": "0.00"},
        {"name": "Логистика", "income": "0.00", "expense": "-3.00"},
    ]


class EventBus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


@pytest.mark.asyncio
async def test_apply_allocation_marks_partial_and_emits_received():
    payment = SimpleNamespace(id=10, amount="10", status="pending", ref="P-10", deal_id=3, counterparty_ref="C-1")
    session = Session(Result("3"))
    bus = EventBus()

    allocation_row = await allocation.apply_allocation(session, bus, payment, Decimal("3"))

    assert allocation_row.payment_id == 10
    assert allocation_row.amount == Decimal("3")
    assert payment.status == "partial"
    assert len(bus.calls) == 1
    assert bus.calls[0][1] == "finance.payment.received"
    assert bus.calls[0][2]["outstanding"] == "7"


@pytest.mark.asyncio
async def test_apply_allocation_marks_paid_and_emits_paid_event():
    payment = SimpleNamespace(id=11, amount="10", status="partial", ref="P-11", deal_id=None, counterparty_ref=None)
    session = Session(Result("10"))
    bus = EventBus()

    await allocation.apply_allocation(session, bus, payment, Decimal("10"))

    assert payment.status == "paid"
    assert payment.paid_at is not None
    assert [call[1] for call in bus.calls] == [
        "finance.payment.received",
        "finance.payment.paid",
    ]
