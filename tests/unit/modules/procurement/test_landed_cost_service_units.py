from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.procurement.landed_cost import LandedCostService


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class Session:
    def __init__(self, result):
        self.result = result

    async def execute(self, _statement):
        return self.result


def row(code="A", stage="actual"):
    return SimpleNamespace(
        sku_code=code,
        unit_landed_cost_byn=Decimal("12.50"),
        shipment_id="S-1",
        fixed_at=datetime(2026, 9, 17, 10, 0),
        stage=stage,
        fx_rate=Decimal("3.2"),
        fx_date=date(2026, 9, 16),
        fx_rate_basis="NB RB",
        id=1,
    )


@pytest.mark.asyncio
async def test_landed_cost_returns_full_latest_row_and_honest_none():
    service = LandedCostService()
    got = await service.last_landed_cost(Session(Result([row()])), "A")
    assert got == {
        "unit_landed_cost_byn": Decimal("12.50"),
        "shipment_id": "S-1",
        "fixed_at": datetime(2026, 9, 17, 10, 0),
        "stage": "actual",
        "fx_rate": Decimal("3.2"),
        "fx_date": date(2026, 9, 16),
        "fx_rate_basis": "NB RB",
    }
    assert await service.last_landed_cost(Session(Result()), "MISSING") is None


@pytest.mark.asyncio
async def test_landed_cost_batch_preserves_every_requested_code_and_first_row():
    service = LandedCostService()
    assert await service.last_landed_cost_batch(Session(Result()), []) == {}

    actual = row("A", "actual")
    estimate = row("A", "estimated")
    other = row("B", "actual")
    got = await service.last_landed_cost_batch(Session(Result([actual, estimate, other])), ["A", "B", "A", "C"])
    assert got["A"]["stage"] == "actual"
    assert got["B"]["stage"] == "actual"
    assert got["C"] is None
