"""WMS круг 3: публикация событий (`wms.stock.low`, `wms.shipment.completed`) и деньги.

Эмиссию проверяем через outbox — роуты пишут ``OutboxEvent`` в ту же сессию (фикстура
``session`` = та, что подменяет ``get_session`` у ``api``); фоновый relay в тестах не
крутится (ASGITransport без lifespan), события остаются в таблице. Шлюз 1С — реальный
``core.services.stock`` поверх ``integrations.StockItem`` (как в остальных wms-тестах).
"""

from decimal import Decimal

from sqlalchemy import select

from core.domain.models import OutboxEvent, Sku
from modules.integrations.models import StockItem


async def _events(session, etype: str) -> list[OutboxEvent]:
    rows = (
        await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == etype).order_by(OutboxEvent.id)
        )
    ).scalars().all()
    return rows


async def _seed_deficit(session) -> None:
    """AKB-60 в Минске: свободно 3 (avail 5 − reserved 2), себес 230."""
    session.add(Sku(code="AKB-60", title="Аккумулятор 60 Ач", unit="шт"))
    session.add(
        StockItem(sku_code="AKB-60", warehouse="Минск",
                  qty_available=Decimal(5), qty_reserved=Decimal(2), cost=Decimal(230))
    )
    await session.commit()


# --------------------------------------------------------------------------- #
#  WMS-R3-1 / R3-8(1): эмит wms.stock.low из /alerts/emit, канонический payload
# --------------------------------------------------------------------------- #
async def test_alerts_emit_publishes_low_stock(api, session):
    await _seed_deficit(session)
    await api.post(
        "/wms/thresholds",
        json={"sku_code": "AKB-60", "warehouse": "Минск", "min_qty": 10, "reorder_qty": 20},
    )

    r = await api.post("/wms/alerts/emit")
    assert r.status_code == 200
    assert r.json() == {"emitted": 1, "gateway": True}

    evs = await _events(session, "wms.stock.low")
    assert len(evs) == 1
    p = evs[0].payload
    assert p["sku_code"] == "AKB-60" and p["sku_title"] == "Аккумулятор 60 Ач"
    assert p["warehouse"] == "Минск"
    assert p["free_qty"] == 3.0 and p["min_qty"] == 10.0 and p["deficit"] == 7.0
    assert p["reorder_qty"] == 20.0 and p["severity"] == "below_min"
    assert p["source"] == "wms.threshold" and p["entity_ref"].startswith("threshold:")


async def test_alerts_emit_no_gateway_is_503_and_silent(api_no_gateways, session):
    """Шлюз остатков отключён → 503 (не эмитим пустоту), событий нет."""
    r = await api_no_gateways.post("/wms/alerts/emit")
    assert r.status_code == 503
    assert await _events(session, "wms.stock.low") == []


# --------------------------------------------------------------------------- #
#  WMS-R3-5 / R3-8(2): дедуп один сигнал на (sku,warehouse) + клампинг reorder
# --------------------------------------------------------------------------- #
async def test_alerts_emit_dedup_one_per_pair(api, session):
    await _seed_deficit(session)
    # два активных порога на одну (sku,warehouse) — должен лететь ОДИН сигнал
    for min_qty in (10, 8):
        await api.post(
            "/wms/thresholds",
            json={"sku_code": "AKB-60", "warehouse": "Минск", "min_qty": min_qty, "reorder_qty": 20},
        )

    r = await api.post("/wms/alerts/emit")
    assert r.json()["emitted"] == 1
    assert len(await _events(session, "wms.stock.low")) == 1


async def test_alerts_emit_clamps_negative_reorder(api, session):
    await _seed_deficit(session)
    await api.post(
        "/wms/thresholds",
        json={"sku_code": "AKB-60", "warehouse": "Минск", "min_qty": 10, "reorder_qty": -5},
    )

    await api.post("/wms/alerts/emit")
    evs = await _events(session, "wms.stock.low")
    assert evs[0].payload["reorder_qty"] == 0.0  # отрицательный дозаказ клампится в 0


# --------------------------------------------------------------------------- #
#  WMS-R3-3 / R3-8(3): эмит wms.shipment.completed из /wms/shipment
# --------------------------------------------------------------------------- #
async def test_shipment_emits_completed_with_doc_ref(api, session):
    r = await api.post(
        "/wms/shipment",
        json={"sku_code": "AKB-60", "qty": 5, "warehouse": "Минск", "doc_ref": "ДОК-2026-0007"},
    )
    assert r.status_code == 201

    evs = await _events(session, "wms.shipment.completed")
    assert len(evs) == 1
    p = evs[0].payload
    # все три ключа матча office = doc_ref
    assert p["shipment_ref"] == "ДОК-2026-0007"
    assert p["sales_ref"] == "ДОК-2026-0007"
    assert p["doc_number"] == "ДОК-2026-0007"
    assert p["sku_code"] == "AKB-60" and p["warehouse"] == "Минск" and p["qty"] == 5.0
    assert p["entity_ref"].startswith("shipment:")


async def test_shipment_silent_without_doc_ref(api, session):
    r = await api.post("/wms/shipment", json={"sku_code": "AKB-60", "qty": 5, "warehouse": "Минск"})
    assert r.status_code == 201
    assert await _events(session, "wms.shipment.completed") == []


# --------------------------------------------------------------------------- #
#  WMS-R3-4 / R3-8(4): оценка остатка в деньгах /wms/balances/valued
# --------------------------------------------------------------------------- #
async def test_balances_valued_money(api, session):
    session.add_all([
        Sku(code="AKB-60", title="АКБ 60", unit="шт"),
        Sku(code="AKB-100", title="АКБ 100", unit="шт"),
        StockItem(sku_code="AKB-60", warehouse="Минск", qty_available=Decimal(0), cost=Decimal(230)),
        StockItem(sku_code="AKB-100", warehouse="Минск", qty_available=Decimal(0), cost=Decimal(500)),
    ])
    await session.commit()
    # движения WMS (теневой остаток): AKB-60 in 10 → 2300; AKB-100 in 4 → 2000
    await api.post("/wms/movements", json={"sku_code": "AKB-60", "warehouse": "Минск", "kind": "in", "qty": 10})
    await api.post("/wms/movements", json={"sku_code": "AKB-100", "warehouse": "Минск", "kind": "in", "qty": 4})

    data = (await api.get("/wms/balances/valued")).json()
    assert data["gateway"] is True
    assert data["total_value"] == 4300.0
    # сорт по |value| убыв. — AKB-60 (2300) первым
    assert data["rows"][0]["sku_code"] == "AKB-60"
    row = next(r for r in data["rows"] if r["sku_code"] == "AKB-60")
    assert row["qty"] == 10.0 and row["unit_cost"] == 230.0 and row["value"] == 2300.0


async def test_balances_valued_no_gateway(api_no_gateways):
    data = (await api_no_gateways.get("/wms/balances/valued")).json()
    assert data["gateway"] is False and data["rows"] == [] and data["total_value"] == 0.0


# --------------------------------------------------------------------------- #
#  WMS-R3-6 / R3-8(5): деньги на дашборде (дефицит + оценка остатка)
# --------------------------------------------------------------------------- #
async def test_dashboard_money_fields(api, session):
    await _seed_deficit(session)  # free=3, cost=230
    await api.post(
        "/wms/thresholds",
        json={"sku_code": "AKB-60", "warehouse": "Минск", "min_qty": 10, "reorder_qty": 20},
    )
    # теневой остаток для оценки: in 10 → 10×230 = 2300
    await api.post("/wms/movements", json={"sku_code": "AKB-60", "warehouse": "Минск", "kind": "in", "qty": 10})

    data = (await api.get("/wms/dashboard")).json()
    assert data["gateway"] is True
    assert data["alerts_count"] == 1
    assert data["alerts_deficit_value"] == 1610.0  # дефицит 7 × себес 230
    assert data["inventory_value"] == 2300.0


async def test_dashboard_money_no_gateway(api_no_gateways):
    data = (await api_no_gateways.get("/wms/dashboard")).json()
    assert data["gateway"] is False
    assert data["alerts_deficit_value"] == 0.0 and data["inventory_value"] == 0.0
