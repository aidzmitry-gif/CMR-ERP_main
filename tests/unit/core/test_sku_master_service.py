from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services import sku_master


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalars(self):
        return self


class Session:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_landed_inputs_resolves_own_vat_and_normalizes_zero_dimensions(monkeypatch):
    sku = SimpleNamespace(
        code="S-1", weight_kg=0, volume_m3=0, vat_code="20", category_id=None
    )
    monkeypatch.setattr(
        sku_master.tnved,
        "effective_code_for_sku",
        AsyncMock(return_value={"code": "8507", "source": "own", "group_code": None}),
    )
    monkeypatch.setattr(
        sku_master.tnved,
        "resolve",
        AsyncMock(return_value={"duty_rate": 5.0, "vat_rate": None}),
    )
    monkeypatch.setattr(
        sku_master.tnved,
        "effective_group_field",
        AsyncMock(side_effect=[
            {"value": "шт", "source": "own", "group_code": None, "group_name": None},
            {"value": "BY", "source": "own", "group_code": None, "group_name": None},
        ]),
    )
    monkeypatch.setattr(
        sku_master.scd2,
        "version_as_of",
        AsyncMock(return_value=SimpleNamespace(rate="20")),
    )

    result = await sku_master.landed_inputs(Session(Result([sku])), "S-1", date(2026, 9, 17))

    assert result["weight_kg"] is None
    assert result["volume_m3"] is None
    assert result["duty_pct"] == 5.0
    assert result["vat_code"] == "20"
    assert result["vat_rate"] == 20.0
    assert result["provenance"] == {
        "weight": "none", "volume": "none", "unit": "own", "country": "own",
        "tnved": "own", "vat": "own",
    }


@pytest.mark.asyncio
async def test_landed_inputs_uses_group_vat_or_tnved_vat_and_unknown_sku(monkeypatch):
    sku = SimpleNamespace(code="S-2", weight_kg=1.5, volume_m3=0.2, vat_code=None, category_id=4)
    monkeypatch.setattr(
        sku_master.tnved,
        "effective_code_for_sku",
        AsyncMock(return_value={"code": None, "source": None, "group_code": None}),
    )
    monkeypatch.setattr(sku_master.tnved, "resolve", AsyncMock())
    monkeypatch.setattr(sku_master.scd2, "version_as_of", AsyncMock(return_value=None))
    monkeypatch.setattr(
        sku_master.tnved,
        "effective_group_field",
        AsyncMock(side_effect=[
            {"value": "шт", "source": "group", "group_code": "G", "group_name": "Group"},
            {"value": "BY", "source": "group", "group_code": "G", "group_name": "Group"},
            {"value": "20", "source": "group", "group_code": "G", "group_name": "Group"},
        ]),
    )
    result = await sku_master.landed_inputs(Session(Result([sku])), "S-2", date(2026, 9, 17))
    assert result["vat_code"] == "20"
    assert result["vat_rate"] is None
    assert result["provenance"]["vat"] == "group"

    unknown = await sku_master.landed_inputs(Session(Result([])), "missing", date(2026, 9, 17))
    assert unknown is None

    sku_master.tnved.effective_code_for_sku = AsyncMock(
        return_value={"code": "8507", "source": "group", "group_code": "G"}
    )
    sku_master.tnved.resolve = AsyncMock(
        return_value={"duty_rate": 5.0, "vat_code": "10", "vat_rate": 10.0}
    )
    sku_master.tnved.effective_group_field = AsyncMock(side_effect=[
        {"value": "шт", "source": "group", "group_code": "G", "group_name": "Group"},
        {"value": "BY", "source": "group", "group_code": "G", "group_name": "Group"},
        {"value": None, "source": None, "group_code": None, "group_name": None},
    ])
    tnved_vat = await sku_master.landed_inputs(Session(Result([sku])), "S-2", date(2026, 9, 17))
    assert tnved_vat["vat_code"] == "10"
    assert tnved_vat["vat_rate"] == 10.0
    assert tnved_vat["provenance"]["vat"] == "tnved"


@pytest.mark.asyncio
async def test_landed_inputs_batch_deduplicates_codes(monkeypatch):
    rows = [SimpleNamespace(code="A"), SimpleNamespace(code="B")]
    monkeypatch.setattr(
        sku_master,
        "_inputs_for",
        AsyncMock(side_effect=lambda _session, sku, _on: {"sku_code": sku.code}),
    )
    result = await sku_master.landed_inputs_batch(
        Session(Result(rows)), ["A", "A", "missing", "B"], date(2026, 9, 17)
    )
    assert list(result) == ["A", "missing", "B"]
    assert result == {"A": {"sku_code": "A"}, "missing": None, "B": {"sku_code": "B"}}
