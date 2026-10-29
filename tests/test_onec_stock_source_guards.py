"""Unknown 1C stock must not become a warehouse, a balance or a reservation."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Sku
from modules.integrations.client import OneCClient
from modules.integrations.models import StockItem
from modules.integrations.service import sync_1c
from modules.integrations.stock import StockService


def live_catalog(monkeypatch):
    client = OneCClient("https://onec.example/odata")
    rows = [{"Ref_Key": "synthetic-sku", "Code": "STOCK-UNKNOWN", "Description": "Synthetic SKU"}]
    monkeypatch.setattr(client, "_get_all", lambda entity, *a, **k: rows if entity.startswith("Catalog_") else [])
    return client


def test_catalog_without_stock_register_does_not_invent_balances(monkeypatch):
    row, = live_catalog(monkeypatch)._fetch_stock_sync()
    assert row["sku_code"] == "STOCK-UNKNOWN"
    for key in ("warehouse", "qty_available", "qty_reserved", "qty_forecast", "price", "cost"):
        assert row[key] is None, key


async def test_unconfigured_client_does_not_supply_demo_by_default():
    client = OneCClient()
    assert await client.fetch_counterparties() == []
    assert await client.fetch_stock() == []


async def test_live_catalog_import_preserves_existing_stock_and_imports_sku(session, monkeypatch):
    row = StockItem(sku_code="STOCK-UNKNOWN", warehouse="Verified warehouse", qty_available=7,
                    qty_reserved=2, qty_forecast=9, price=Decimal("12.50"), cost=Decimal("8.75"))
    session.add(row)
    await session.commit()
    old = (row.qty_available, row.qty_reserved, row.qty_forecast, row.price, row.cost, row.updated_at)
    client = live_catalog(monkeypatch)
    monkeypatch.setattr(client, "fetch_counterparties", AsyncMock(return_value=[]))
    summary = await sync_1c(session, Mock(), client)
    await session.commit()
    stocks = list(await session.scalars(select(StockItem)))
    assert len(stocks) == 1
    assert (row.qty_available, row.qty_reserved, row.qty_forecast, row.price, row.cost, row.updated_at) == old
    sku = await session.scalar(select(Sku).where(Sku.code == "STOCK-UNKNOWN"))
    assert sku is not None and sku.title == "Synthetic SKU"
    assert summary["stock"] == 0
    assert summary["stock_unknown"] == 1
    assert summary["stock_source_available"] is False


async def test_stock_http_refuses_unverified_old_rows(api, session, monkeypatch):
    session.add(StockItem(sku_code="OLD-DEMO", warehouse="Main", qty_available=120, price=95))
    await session.commit()
    gateway = api._transport.app.state.core.services.onec
    monkeypatch.setattr(gateway, "base_url", "https://onec.example/odata")
    response = await api.get("/integrations/1c/stock")
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "onec_stock_source_unavailable"
    assert "OLD-DEMO" not in response.text


async def test_demo_opt_in_returns_independent_rows_and_still_cannot_write_finance():
    client = OneCClient(allow_demo=True)
    assert client.stock_source_available is True
    first = await client.fetch_stock()
    assert first and first[0]["qty_available"] > 0
    first[0]["qty_available"] = -1
    assert (await client.fetch_stock())[0]["qty_available"] > 0
    first = await client.fetch_counterparties()
    first[0]["name"] = "Changed synthetic copy"
    assert (await client.fetch_counterparties())[0]["name"] != first[0]["name"]
    assert client.financial_source_available is False
    assert client.outbound_document_source_available is False


@pytest.mark.parametrize(("environment", "url", "available"), [
    ("prod", "", False), (None, "", False), ("staging", "", False),
    ("dev", "", True), ("TEST", "", True), ("development", "", True),
    ("dev", "https://onec.example", False), ("prod", "https://onec.example", False),
])
async def test_registration_binds_source_and_scopes_demo(environment, url, available):
    from modules.integrations.module import IntegrationsModule
    from tests.test_integrations_price_cost_register import _FakeCore

    core = _FakeCore(url)
    if environment is not None:
        core.config.environment = environment
    IntegrationsModule().register(core)
    assert core.services.onec.stock_source_available is available
    assert core.services.stock._source is core.services.onec
    if not available:
        session = AsyncMock(spec=AsyncSession)
        assert await core.services.stock.stock_by_sku(session, "OLD-DEMO") is None
        session.execute.assert_not_awaited()


@pytest.mark.parametrize("availability", [False, None, "true", 1])
@pytest.mark.parametrize("operation", ["reserve", "release", "lock_reservation_items"])
async def test_unknown_source_cannot_change_or_lock_stock(availability, operation):
    gateway = StockService(source=SimpleNamespace(stock_source_available=availability))
    session = AsyncMock(spec=AsyncSession)
    with pytest.raises(ValueError, match="источника"):
        await getattr(gateway, operation)(session, [{"sku_code": "OLD-DEMO", "qty": 1}])
    session.scalars.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("operation", ["reserve", "release", "lock_reservation_items"])
async def test_empty_reservation_is_no_effect_even_without_source(operation):
    session = AsyncMock(spec=AsyncSession)
    result = await getattr(StockService(source=SimpleNamespace()), operation)(session, [])
    assert result in (None, [])
    session.execute.assert_not_awaited()
    session.scalars.assert_not_awaited()


@pytest.mark.parametrize("key", ["warehouse", "qty_available", "qty_reserved", "qty_forecast", "price"])
async def test_incomplete_snapshot_does_not_overwrite_mirror(session, key):
    stock = StockItem(sku_code="PARTIAL", warehouse="Explicit warehouse", qty_available=5,
                      qty_reserved=1, qty_forecast=6, price=9)
    session.add(stock)
    await session.commit()
    row = {"sku_code": "PARTIAL", "title": "Synthetic partial", "warehouse": stock.warehouse,
           "qty_available": 0, "qty_reserved": 0, "qty_forecast": 0, "price": 0, key: None}
    client = SimpleNamespace(stock_source_available=True,
                             fetch_counterparties=AsyncMock(return_value=[]),
                             fetch_stock=AsyncMock(return_value=[row]))
    result = await sync_1c(session, Mock(), client)
    await session.commit()
    assert result["stock"] == 0 and result["stock_unknown"] == 1
    assert (stock.qty_available, stock.qty_reserved, stock.qty_forecast, stock.price) == (5, 1, 6, 9)
    assert len(list(await session.scalars(select(StockItem)))) == 1


async def test_explicit_verified_zero_is_distinct_from_unknown(session):
    row = {"sku_code": "REAL-ZERO", "title": "Synthetic verified zero", "warehouse": "Explicit warehouse",
           "qty_available": 0, "qty_reserved": 0, "qty_forecast": 0, "price": 0}
    client = SimpleNamespace(stock_source_available=True,
                             fetch_counterparties=AsyncMock(return_value=[]),
                             fetch_stock=AsyncMock(return_value=[row]))
    summary = await sync_1c(session, Mock(), client)
    await session.commit()
    assert summary["stock"] == 1 and summary["stock_unknown"] == 0
    stock, = list(await session.scalars(select(StockItem)))
    assert stock.warehouse == row["warehouse"]
    assert stock.qty_available == stock.qty_reserved == stock.qty_forecast == stock.price == 0


async def test_numeric_legacy_payload_cannot_override_unavailable_source(session):
    row = {"sku_code": "UNVERIFIED-ZERO", "title": "Synthetic legacy", "warehouse": "Invented warehouse",
           "qty_available": 0, "qty_reserved": 0, "qty_forecast": 0, "price": 0}
    client = SimpleNamespace(stock_source_available=False,
                             fetch_counterparties=AsyncMock(return_value=[]),
                             fetch_stock=AsyncMock(return_value=[row]))
    summary = await sync_1c(session, Mock(), client)
    assert summary["stock"] == 0 and summary["stock_unknown"] == 1
    assert list(await session.scalars(select(StockItem))) == []


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-Infinity", -1, 0, None, {}, "bad"])
def test_invalid_price_does_not_become_a_number_or_zero(monkeypatch, price):
    client = live_catalog(monkeypatch)
    catalog = [{"Ref_Key": "synthetic-sku", "Code": "STOCK-UNKNOWN"}]
    prices = [{"RecordSet": [{"Номенклатура_Key": "synthetic-sku", "Цена": price}]}]
    monkeypatch.setattr(client, "_get_all", lambda entity, *a, **k: catalog if entity.startswith("Catalog_") else prices)
    row, = client._fetch_stock_sync()
    assert row["price"] is None
    assert row["qty_available"] is None


def test_unavailable_price_register_preserves_unknown(monkeypatch):
    client = live_catalog(monkeypatch)

    def get(entity, *args, **kwargs):
        if entity.startswith("Catalog_"):
            return [{"Ref_Key": "synthetic-sku", "Code": "STOCK-UNKNOWN"}]
        raise RuntimeError("Synthetic unavailable price register")

    monkeypatch.setattr(client, "_get_all", get)
    row, = client._fetch_stock_sync()
    assert row["price"] is None and row["warehouse"] is None


@pytest.mark.parametrize("method", ["fetch_counterparties", "fetch_stock"])
async def test_unreachable_read_does_not_fall_back_to_demo(monkeypatch, method):
    client = OneCClient("https://onec.example", allow_demo=True)
    monkeypatch.setattr(client, f"_{method}_sync", Mock(side_effect=RuntimeError("Synthetic unavailable source")))
    assert await getattr(client, method)() == []
    assert client.stock_source_available is False
    assert client.stock_source_reason
