"""PC3 — потребление цены/себеса из 1С в марже сделки: приоритет источников (1С→landed),
дефолт цены из прайса 1С, КП перекрывает прайс, провенанс cost_source/price_source, честная
деградация без фасадов. Фасады подменяются стендами на ``app.state.core.services`` (как v2-тесты).
"""
from datetime import datetime
from decimal import Decimal as D

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


async def test_price_cost_provides_cost_and_price_from_1c(api, session):
    """1С даёт и цену, и себес (нет КП, нет landed) → маржа из 1С, источники onec."""
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
    assert line["unit_price"] == 150.0 and line["price_source"] == "onec"
    assert line["unit_landed_cost"] == 100.0 and line["cost_source"] == "onec"
    assert line["status"] == "priced"
    assert r["revenue"] == 600.0 and r["cogs_landed"] == 400.0 and r["gross_profit"] == 200.0
    assert r["margin_pct"] == 33  # (150-100)/150 → 33


async def test_quote_overrides_1c_price_list(api, session):
    """КП клиента перекрывает прайс 1С; себес всё равно из 1С."""
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
    assert line["unit_price"] == 200.0 and line["price_source"] == "quote"  # КП перекрыл прайс
    assert line["cost_source"] == "onec"


async def test_1c_cost_takes_priority_over_landed(api, session):
    """Себес из 1С (onec) приоритетнее landed; landed-провенанс не показываем (себес не из landed)."""
    sku = await _seed_sku(session, "PCC")
    deal = await _new_deal(api, "PC-3", counterparty="ООО Z")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=1),
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
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=1),
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
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=1),
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


async def test_price_defaulted_from_1c_list_when_no_quote(api, session):
    """Нет КП → цена клиенту дефолтится из прайса 1С, строка становится priced (цена+себес)."""
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
    assert line["unit_price"] == 60.0 and line["price_source"] == "demo"  # дефолт из прайса 1С
    assert line["status"] == "priced"  # есть и цена (прайс), и себес → priced
    assert r["revenue"] == 120.0


async def test_forecast_uses_1c_cost_without_landed(api, session):
    """Прогноз воронки согласован с карточкой: 1С даёт себес без landed → gross_weighted не None."""
    sku = await _seed_sku(session, "PCG")
    deal = await _new_deal(api, "PC-7", counterparty="ООО T")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=1),
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
