from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modules.finance import routes


class Result:
    def __init__(self, *, rows=(), scalar=None):
        self._rows = list(rows)
        self._scalar = scalar

    def all(self):
        return self._rows

    def scalar_one(self):
        return self._scalar


class Session:
    def __init__(self, *results):
        self._results = list(results)

    async def execute(self, _statement):
        return self._results.pop(0)


@pytest.mark.asyncio
async def test_summary_route_projects_real_finance_aggregation_contract():
    session = Session(
        Result(
            rows=[
                ("receivable", Decimal("100")),
                ("freight", Decimal("20")),
                ("freight_refund", Decimal("-3")),
                ("landed", Decimal("40")),
                ("claim_refund", Decimal("5")),
                ("po_planned", Decimal("99")),
            ]
        ),
        Result(scalar=Decimal("30")),
    )

    result = await routes.get_summary(session)

    assert result["currency"] == "BYN"
    assert result["margin"] == {
        "revenue": "100.00",
        "landed": "35.00",
        "landed_gross": "40.00",
        "claim_refund": "5.00",
        "freight": "17.00",
        "gross": "48.00",
        "pct": 48.0,
    }
    assert result["cash"] == {
        "inflow": "33.00",
        "outflow": "60.00",
        "net": "-27.00",
        "received": "30.00",
        "pending_receivable": "70.00",
        "freight_refund": "3.00",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "kwargs", "field"),
    [
        (routes.get_cashflow, {"period_from": "17.09.2026"}, "period_from"),
        (routes.get_cashflow, {"period_to": "2026-02-30"}, "period_to"),
        (routes.get_pnl, {"period_from": "bad-date"}, "period_from"),
    ],
)
async def test_finance_report_routes_reject_invalid_iso_dates_before_data_access(
    handler, kwargs, field
):
    call_kwargs = {"session": object(), **kwargs}
    if handler is routes.get_cashflow:
        call_kwargs["core"] = SimpleNamespace(services=SimpleNamespace())

    with pytest.raises(HTTPException) as error:
        await handler(**call_kwargs)

    assert error.value.status_code == 400
    assert field in str(error.value.detail)
