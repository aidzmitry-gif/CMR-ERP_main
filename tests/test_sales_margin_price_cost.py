"""Confirmed deal-line prices, NULL rejection of quote/catalog fallback, and cost provenance."""
from datetime import datetime
from decimal import Decimal as D

import pytest

from core.domain.models import Sku
from core.services.price_cost import ItemPriceCost
from modules.sales.models import DealItem, PriceQuote


async def _new_deal(api, number, **extra):
    payload = {"number": number, "title": "t", "counterparty": "c", **extra}
    r = await api.post("/sales/deals", json=payload)
    assert r.status_code == 201
    return r.json()


async def _seed_sku(session, code, title="t"):
    sku = Sku(code=code, title=title)
    session.add(sku)
    await session.flush()
    return sku


class _FakePriceCost:
    """Стенд фасада price_cost: словарь code → ItemPriceCost, отдаёт только известные коды."""

    def __init__(self, table):
        self.table = table

    async def get_item_price_cost(self, session, sku_codes):
        return {c: self.table[c] for c in sku_codes if c in self.table}


class _FakeLanded:
    """Стенд landed_cost: code → себес (float); неизвестный код → None."""

    def __init__(self, table):
        self.table = table

    async def last_landed_cost_batch(self, session, sku_codes):
        return {
            c: (
                {
                    "unit_landed_cost_byn": D(str(self.table[c])), "shipment_id": 7,
                    "fixed_at": datetime(2026, 6, 1, 10, 0), "stage": "closed",
                    "fx_rate": D("3.2"), "fx_date": "2026-06-01",
                }
                if c in self.table else None
            )
            for c in sku_codes
        }


async def test_null_price_ignores_1c_price_but_preserves_cost(api, session):
    """NULL remains unknown despite an available 1C selling price; cost is retained."""
    sku = await _seed_sku(session, "PCA", "АКБ")
    deal = await _new_deal(api, "PC-1", counterparty="ООО X")
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=4))
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.price_cost = _FakePriceCost(
        {"PCA": ItemPriceCost(cost_byn=100.0, price_byn=150.0, price_type="оптовая", source="onec")}
    )
    app.state.core.services.landed_cost = None
    try:
        r = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
    finally:
        app.state.core.services.price_cost = None
    line = r["lines"][0]
    assert line["unit_price"] is None and line["price_source"] is None
    assert line["unit_landed_cost"] == 100.0 and line["cost_source"] == "onec"
    assert line["status"] == "no_price" and line["revenue"] is None
    assert line["cogs"] == 400.0
    assert r["gross_profit"] is None and r["margin_pct"] is None


async def test_null_price_ignores_historical_quote_and_price_list(api, session):
    """Historical customer quote and catalog price cannot confirm a NULL line price."""
    sku = await _seed_sku(session, "PCB")
    deal = await _new_deal(api, "PC-2", counterparty="ООО Y")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=2),
        PriceQuote(sku_code="PCB", counterparty="ООО Y", price=200),  # КП=200
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.price_cost = _FakePriceCost(
        {"PCB": ItemPriceCost(cost_byn=80.0, price_byn=150.0, source="onec")}  # прайс 1С=150
    )
    try:
        r = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
    finally:
        app.state.core.services.price_cost = None
    line = r["lines"][0]
    assert line["unit_price"] is None and line["price_source"] is None
    assert line["status"] == "no_price" and r["gross_profit"] is None
    assert line["cost_source"] == "onec"


async def test_1c_cost_takes_priority_over_landed(api, session):
    """Себес из 1С (onec) приоритетнее landed; landed-провенанс не показываем (себес не из landed)."""
    sku = await _seed_sku(session, "PCC")
    deal = await _new_deal(api, "PC-3", counterparty="ООО Z")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=1, unit_price=300),
        PriceQuote(sku_code="PCC", counterparty="ООО Z", price=300),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.price_cost = _FakePriceCost(
        {"PCC": ItemPriceCost(cost_byn=90.0, source="onec")}  # только себес из 1С
    )
    app.state.core.services.landed_cost = _FakeLanded({"PCC": 120.0})  # landed 120 — уступает
    try:
        r = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
    finally:
        app.state.core.services.price_cost = None
        app.state.core.services.landed_cost = None
    line = r["lines"][0]
    assert line["unit_landed_cost"] == 90.0 and line["cost_source"] == "onec"  # 1С бьёт landed
    assert line["cost_shipment_id"] is None  # себес не из landed → провенанс партии не показываем
    assert line["unit_price"] == 300.0 and line["price_source"] == "quote"


async def test_only_landed_marks_source_landed(api, session):
    """Без price_cost — себес из landed, источник landed, провенанс партии виден (как раньше)."""
    sku = await _seed_sku(session, "PCD")
    deal = await _new_deal(api, "PC-4", counterparty="ООО W")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=1, unit_price=50),
        PriceQuote(sku_code="PCD", counterparty="ООО W", price=50),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.price_cost = None
    app.state.core.services.landed_cost = _FakeLanded({"PCD": 30.0})
    try:
        r = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
    finally:
        app.state.core.services.landed_cost = None
    line = r["lines"][0]
    assert line["cost_source"] == "landed" and line["unit_landed_cost"] == 30.0
    assert line["cost_shipment_id"] == 7  # landed-провенанс присутствует
    assert line["price_source"] == "quote"


async def test_no_facade_degradation_sources_none(api, session):
    """Ни одного источника себеса → cogs None + reason; cost_source None, price_source из КП."""
    sku = await _seed_sku(session, "PCE")
    deal = await _new_deal(api, "PC-5", counterparty="ООО Q")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=1, unit_price=50),
        PriceQuote(sku_code="PCE", counterparty="ООО Q", price=50),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.price_cost = None
    app.state.core.services.landed_cost = None
    r = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
    assert r["cogs_landed"] is None and "procurement" in (r["reason"] or "")
    line = r["lines"][0]
    assert line["cost_source"] is None and line["unit_landed_cost"] is None
    assert line["price_source"] == "quote"  # цена из КП есть, себеса нет


async def test_null_price_ignores_demo_price_list(api, session):
    """A demo catalog price also cannot replace NULL."""
    sku = await _seed_sku(session, "PCF")
    deal = await _new_deal(api, "PC-6", counterparty="ООО R")
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=2))  # НЕТ котировки КП
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.price_cost = _FakePriceCost(
        {"PCF": ItemPriceCost(cost_byn=40.0, price_byn=60.0, source="demo")}
    )
    try:
        r = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
    finally:
        app.state.core.services.price_cost = None
    line = r["lines"][0]
    assert line["unit_price"] is None and line["price_source"] is None
    assert line["status"] == "no_price" and line["revenue"] is None
    assert line["cost_source"] == "demo"
    assert r["gross_profit"] is None


async def test_forecast_uses_1c_cost_without_landed(api, session):
    """Прогноз воронки согласован с карточкой: 1С даёт себес без landed → gross_weighted не None."""
    sku = await _seed_sku(session, "PCG")
    deal = await _new_deal(api, "PC-7", counterparty="ООО T")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=1, unit_price=100),
        PriceQuote(sku_code="PCG", counterparty="ООО T", price=100),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.price_cost = _FakePriceCost(
        {"PCG": ItemPriceCost(cost_byn=70.0, source="onec")}
    )
    app.state.core.services.landed_cost = None  # landed нет — раньше это давало gross=null
    try:
        r = (await api.get("/sales/pipeline/margin-forecast")).json()
    finally:
        app.state.core.services.price_cost = None
    assert r["gross_weighted"] is not None  # себес из 1С учтён, деградации нет
    assert r["deals_priced"] >= 1 and r["reason"] is None


async def test_plan_sources_margin_default_falls_back_to_1c_catalog(api, session):
    """PC5: нет истории won → маржа-дефолт конструктора из прайса 1С (средняя маржа каталога),
    источник помечен. Средний чек из каталога НЕ выдумываем (это чек сделки, не цена SKU)."""
    await _seed_sku(session, "CAT-1")
    await _seed_sku(session, "CAT-2")
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.price_cost = _FakePriceCost({
        "CAT-1": ItemPriceCost(cost_byn=60.0, price_byn=100.0, source="demo"),  # маржа 40%
        "CAT-2": ItemPriceCost(cost_byn=80.0, price_byn=100.0, source="demo"),  # маржа 20%
    })
    try:
        r = (await api.get("/sales/plan-sources", params={"month": "2030-01"})).json()
    finally:
        app.state.core.services.price_cost = None
    d = r["defaults"]
    assert d["margin_pct"] == 30 and d["margin_pct_source"] == "demo"  # (40+20)/2
    assert d["avg_check"] is None  # чек из каталога не выдумываем


async def test_plan_sources_no_margin_default_without_facade(api, session):
    """PC5: без фасада price_cost — маржа-дефолт None (честно), источника нет."""
    await _seed_sku(session, "CAT-3")
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.price_cost = None
    r = (await api.get("/sales/plan-sources", params={"month": "2030-02"})).json()
    d = r["defaults"]
    assert d["margin_pct"] is None and d["margin_pct_source"] is None


@pytest.mark.parametrize("price", [None, D("0"), D("125.50")])
async def test_margin_confirmed_rows_are_independent(api, session, price):
    sku = await _seed_sku(session, "SAME")
    deal = await _new_deal(api, "ROW", probability=100)
    other = await _new_deal(api, "OTHER", probability=0)
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=2, unit_price=price),
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=3, unit_price=200),
        DealItem(deal_id=other["id"], sku_id=sku.id, qty=7, unit_price=900),
        PriceQuote(sku_code="SAME", counterparty="c", price=777),
    ])
    await session.commit()
    services = api._transport.app.state.core.services
    services.price_cost = _FakePriceCost({
        "SAME": ItemPriceCost(cost_byn=50, price_byn=888, source="onec"),
    })
    try:
        response = await api.get(f"/sales/deals/{deal['id']}/margin")
        assert response.status_code == 200
        margin = response.json()
        by_qty = {line["qty"]: line for line in margin["lines"]}
        assert by_qty[2]["unit_price"] == (float(price) if price is not None else None)
        assert by_qty[3]["unit_price"] == 200
        assert by_qty[2]["cost_source"] == "onec"
        expected = 450 + ((float(price) - 50) * 2 if price is not None else 0)
        assert margin["gross_profit"] == expected
        assert margin["priced_count"] == (1 if price is None else 2)
        forecast = (await api.get("/sales/pipeline/margin-forecast")).json()
        assert forecast["gross_weighted"] == expected
        other_margin = (await api.get(f"/sales/deals/{other['id']}/margin")).json()
        assert other_margin["lines"][0]["unit_price"] == 900
    finally:
        services.price_cost = None


async def test_all_null_prices_remain_unknown_in_margin_callers(api, session):
    sku = await _seed_sku(session, "UNKNOWN")
    deal = await _new_deal(api, "NULL-CALLERS", probability=100)
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=2),
        PriceQuote(sku_code="UNKNOWN", counterparty="c", price=777),
    ])
    await session.commit()
    services = api._transport.app.state.core.services
    services.price_cost = _FakePriceCost({
        "UNKNOWN": ItemPriceCost(cost_byn=50, price_byn=888, source="onec"),
    })
    try:
        margin = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
        assert margin["priced_count"] == 0
        assert margin["gross_profit"] is None and margin["margin_pct"] is None
        assert margin["lines"][0]["revenue"] is None
        forecast = (await api.get("/sales/pipeline/margin-forecast")).json()
        assert forecast["deals_priced"] == 0
        assert forecast["gross_weighted"] is None
        assert forecast["margin_pct_blended"] is None
        reconcile = (await api.get(f"/sales/deals/{deal['id']}/margin/reconcile")).json()
        assert reconcile["sales_forecast_gross"] is None
        assert reconcile["finance_actual_gross"] is None
        won = await api.post(f"/sales/deals/{deal['id']}/win")
        assert won.status_code == 200
        journal = (await api.get("/sales/journal")).json()
        row = next(row for row in journal if row["deal_id"] == deal["id"])
        assert row["gross_profit"] is None and row["margin_pct"] is None
        assert row["margin_reason"]
    finally:
        services.price_cost = None
