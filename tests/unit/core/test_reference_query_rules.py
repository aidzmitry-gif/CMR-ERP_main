from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services import reference_query


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar = scalar

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        return self.scalar

    def scalars(self):
        return self


class Session:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_query_handles_flat_versioned_hierarchical_and_categories():
    unit = SimpleNamespace(code="шт", title="Штука", is_active=True)
    assert await reference_query.query(Session(Result([unit])), "core.units", key="шт") == {
        "ref": "core.units",
        "key": "шт",
        "result": {"code": "шт", "title": "Штука", "is_active": True},
    }
    assert await reference_query.query(Session(Result([unit])), "core.units") == {
        "ref": "core.units",
        "result": [{"code": "шт", "title": "Штука", "is_active": True}],
    }

    rate = SimpleNamespace(currency_code="USD", rate="3.2", start_date=date(2026, 1, 1), end_date=None)
    monkey_session = Session()
    versioned = AsyncMock(return_value=rate)
    # The service is selected by the public query API; both date and current paths are explicit.
    original_as_of = reference_query.scd2.version_as_of
    original_current = reference_query.scd2.current_version
    reference_query.scd2.version_as_of = versioned
    reference_query.scd2.current_version = AsyncMock(return_value=None)
    try:
        assert (await reference_query.query(
            monkey_session, "core.currency_rates", key="USD", as_of=date(2026, 9, 17)
        ))["result"]["rate"] == "3.2"
        assert (await reference_query.query(
            monkey_session, "core.currency_rates", key="USD"
        ))["result"] is None
    finally:
        reference_query.scd2.version_as_of = original_as_of
        reference_query.scd2.current_version = original_current

    account = SimpleNamespace(
        id=1, code="10", title="Assets", kind="asset", parent_id=None,
        effective_from=None, effective_to=None, is_active=True,
    )
    assert (await reference_query.query(Session(Result([account])), "core.accounts"))["result"][0]["code"] == "10"

    category = SimpleNamespace(id=2, code="BAT", name="Batteries", parent_id=None)
    assert await reference_query.query(Session(Result([category])), "core.nomenclature_groups", key="BAT") == {
        "ref": "core.nomenclature_groups", "key": "BAT",
        "result": {"id": 2, "code": "BAT", "name": "Batteries", "parent_id": None},
    }
    assert (await reference_query.query(Session(Result([category])), "core.nomenclature_groups"))["result"]

    with pytest.raises(reference_query.ReferenceQueryError, match="нужен параметр key"):
        await reference_query.query(Session(), "core.currency_rates")
    with pytest.raises(reference_query.ReferenceQueryError, match="неизвестный справочник"):
        await reference_query.query(Session(), "core.unknown")


@pytest.mark.asyncio
async def test_query_handles_counterparties_skus_and_resolve(monkeypatch):
    cp = SimpleNamespace(id=1, name="Alpha", unp="111")
    result = await reference_query.query(Session(Result([cp])), "core.counterparties", key="111")
    assert result["result"] == [{"id": 1, "name": "Alpha", "unp": "111"}]
    result = await reference_query.query(Session(Result([cp])), "core.counterparties", name="alp")
    assert result["result"][0]["name"] == "Alpha"
    with pytest.raises(reference_query.ReferenceQueryError, match="УНП"):
        await reference_query.query(Session(), "core.counterparties")

    sku = SimpleNamespace(code="S-1", title="Battery", unit="шт", category_id=4, vat_code="20", volume_m3=0.1)
    result = await reference_query.query(Session(Result([sku])), "core.skus", category_id=4)
    assert result["result"] == [{
        "code": "S-1", "title": "Battery", "unit": "шт", "category_id": 4,
        "vat_code": "20", "volume_m3": 0.1,
    }]

    monkeypatch.setattr(
        reference_query.tnved,
        "effective_code_for_sku",
        AsyncMock(return_value={"code": "8507", "source": "own"}),
    )
    monkeypatch.setattr(
        reference_query.tnved, "resolve", AsyncMock(return_value={"duty_rate": "5"})
    )
    monkeypatch.setattr(
        reference_query.tnved,
        "effective_group_field",
        AsyncMock(side_effect=["20", "шт", "BY"]),
    )
    resolved = await reference_query.query(Session(Result([sku])), "core.skus", key="S-1", resolve=True)
    assert resolved["result"]["effective_tnved"]["rates"] == {"duty_rate": "5"}
    assert resolved["result"]["effective_vat"] == "20"

    missing = await reference_query.query(Session(Result([])), "core.skus", key="missing", resolve=True)
    assert missing["result"] is None
    with pytest.raises(reference_query.ReferenceQueryError, match="только для core.skus"):
        await reference_query.query(Session(), "core.units", resolve=True)
    with pytest.raises(reference_query.ReferenceQueryError, match="нужен key"):
        await reference_query.resolve_sku(Session(), None)


@pytest.mark.asyncio
async def test_aggregates_validate_whitelist_and_return_counts():
    assert await reference_query.run_aggregate(Session(Result(scalar=4)), "core.skus", "count", None) == {
        "ref": "core.skus", "aggregate": "count", "result": 4
    }
    grouped = await reference_query.run_aggregate(
        Session(Result(rows=[("шт", 3), ("компл", 1)])), "core.skus", "group_by", "unit"
    )
    assert grouped["result"] == [{"value": "шт", "count": 3}, {"value": "компл", "count": 1}]

    with pytest.raises(reference_query.ReferenceQueryError, match="не поддержана"):
        await reference_query.run_aggregate(Session(), "core.tnved", "count", None)
    with pytest.raises(reference_query.ReferenceQueryError, match="не разрешён"):
        await reference_query.run_aggregate(Session(), "core.skus", "group_by", "title")
    with pytest.raises(reference_query.ReferenceQueryError, match="неизвестная агрегация"):
        await reference_query.run_aggregate(Session(), "core.skus", "sum", None)

    assert await reference_query.query(
        Session(Result(scalar=2)), "core.skus", aggregate="count"
    ) == {"ref": "core.skus", "aggregate": "count", "result": 2}
