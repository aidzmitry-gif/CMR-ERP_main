from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from modules.integrations.price_cost import StockPriceCostSource
from modules.integrations.stock import StockService


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
async def test_stock_price_source_prefers_nonzero_price_and_exposes_onec_provenance():
    source = StockPriceCostSource()
    assert await source.get_item_price_cost(Session(), []) == {}
    older = type("Row", (), {
        "sku_code": "SKU-1", "price": Decimal("0"), "cost": Decimal("40"),
        "updated_at": datetime(2026, 9, 1),
    })()
    newer = type("Row", (), {
        "sku_code": "SKU-1", "price": Decimal("100"), "cost": Decimal("60"),
        "updated_at": datetime(2026, 9, 2),
    })()
    empty = type("Row", (), {
        "sku_code": "SKU-2", "price": None, "cost": None, "updated_at": None,
    })()
    result = await source.get_item_price_cost(Session(Result([older, newer, empty])), ["SKU-1", "SKU-2"])
    assert set(result) == {"SKU-1"}
    assert (result["SKU-1"].price_byn, result["SKU-1"].cost_byn, result["SKU-1"].source) == (100.0, 60.0, "onec")
    assert result["SKU-1"].as_of == date(2026, 9, 2)


@pytest.mark.asyncio
async def test_stock_service_reserve_release_and_stock_mirror_handle_empty_and_boundaries():
    service = StockService()
    row = type("Row", (), {
        "warehouse": "Главный", "qty_reserved": Decimal("2"), "qty_available": Decimal("10"),
        "qty_forecast": Decimal("4"), "price": Decimal("100"), "cost": Decimal("70"),
        "updated_at": datetime(2026, 9, 17),
    })()
    reserved = await service.reserve(
        Session(Result([row]), Result([])),
        [{"sku_code": "SKU-1", "qty": "3"}, {"sku_code": "", "qty": 2}],
    )
    assert reserved == [{"sku_code": "SKU-1", "qty": 3.0, "warehouse": "Главный"}]
    assert row.qty_reserved == Decimal("5")

    row.qty_reserved = Decimal("2")
    released = await service.release(
        Session(Result([row]), Result([])),
        [{"sku_code": "SKU-1", "qty": "5"}, {"sku_code": "SKU-2", "qty": 1}],
    )
    assert released == [{"sku_code": "SKU-1", "qty": 5.0, "warehouse": "Главный"}]
    assert row.qty_reserved == Decimal("0")

    mirror = await service.stock_by_sku(Session(Result([row])), "SKU-1")
    assert (mirror["total_available"], mirror["total_reserved"], mirror["price"], mirror["cost"]) == (10.0, 0.0, 100.0, 70.0)
    assert await service.stock_by_sku(Session(Result([])), "MISSING") is None


@pytest.mark.asyncio
async def test_batches_are_sorted_fefo_and_nearest_expiry_ignores_expired_lots(monkeypatch):
    today = date(2026, 9, 17)
    monkeypatch.setattr("modules.integrations.stock.date", type("Date", (), {"today": staticmethod(lambda: today)}))
    rows = [
        type("BatchRow", (), {"lot_no": "expired", "supplier": "A", "warehouse": "W", "qty": Decimal("1"), "mfg_date": None, "expiry_date": today - timedelta(days=1), "unit_landed_cost": Decimal("5"), "external_ref": "E1"})(),
        type("BatchRow", (), {"lot_no": "warn", "supplier": "A", "warehouse": "W", "qty": Decimal("2"), "mfg_date": None, "expiry_date": today + timedelta(days=100), "unit_landed_cost": None, "external_ref": "E2"})(),
        type("BatchRow", (), {"lot_no": "ok", "supplier": "B", "warehouse": "W", "qty": Decimal("3"), "mfg_date": None, "expiry_date": today + timedelta(days=400), "unit_landed_cost": Decimal("7"), "external_ref": "E3"})(),
        type("BatchRow", (), {"lot_no": "none", "supplier": "B", "warehouse": "W", "qty": Decimal("4"), "mfg_date": None, "expiry_date": None, "unit_landed_cost": None, "external_ref": "E4"})(),
    ]
    result = await StockService().batches_by_sku(Session(Result(rows)), "SKU-1")
    assert [item["lot_no"] for item in result["rows"]] == ["expired", "warn", "ok", "none"]
    assert [item["fefo"] for item in result["rows"]] == ["expired", "warn", "ok", "none"]
    assert (result["total_qty"], result["nearest_expiry"]) == (10.0, (today + timedelta(days=100)).isoformat())
    assert await StockService().batches_by_sku(Session(Result([])), "MISSING") is None
