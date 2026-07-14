"""StockPriceCostSource — цена/себес из StockItem с source=onec."""
from __future__ import annotations

from decimal import Decimal

import pytest

from core.services.price_cost import ItemPriceCost
from modules.integrations.models import StockItem
from modules.integrations.price_cost import StockPriceCostSource


@pytest.mark.asyncio
async def test_stock_price_cost_source_onec_provenance(session):
    session.add(StockItem(
        sku_code="LIVE-1", warehouse="Главный",
        price=Decimal("12.50"), cost=Decimal("8.00"),
    ))
    await session.flush()

    out = await StockPriceCostSource().get_item_price_cost(session, ["LIVE-1", "NOPE"])
    assert "NOPE" not in out
    item = out["LIVE-1"]
    assert isinstance(item, ItemPriceCost)
    assert item.price_byn == 12.5
    assert item.cost_byn == 8.0
    assert item.source == "onec"
    assert item.currency == "BYN"


@pytest.mark.asyncio
async def test_stock_price_cost_skips_zero_price_without_cost(session):
    session.add(StockItem(sku_code="EMPTY-1", warehouse="Главный", price=Decimal("0")))
    await session.flush()
    assert await StockPriceCostSource().get_item_price_cost(session, ["EMPTY-1"]) == {}


@pytest.mark.asyncio
async def test_stock_price_cost_empty_input(session):
    assert await StockPriceCostSource().get_item_price_cost(session, []) == {}
