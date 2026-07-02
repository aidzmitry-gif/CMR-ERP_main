"""M4: карточка номенклатуры (мастер-данные Sku + горячие поля + landed cost через фасад)."""

from datetime import date

from core.domain.models import Sku, SyncLink
from core.domain.reference import NomenclatureCategory, TnvedCode, VatRate


async def test_sku_card_returns_master_fields(api, session):
    session.add(Sku(
        code="AKB-304", title="Аккумулятор LiFePO4 304Ah", unit="шт",
        weight_kg=5.6, tnved_code="8507600000", shelf_life_days=1095,
        attributes={"voltage": "3.2V"}, provenance={"title": {"source": "1c"}},
    ))
    await session.commit()

    card = (await api.get("/system/sku/AKB-304")).json()
    assert card["code"] == "AKB-304"
    assert card["weight_kg"] == 5.6
    assert card["tnved_code"] == "8507600000"
    assert card["shelf_life_days"] == 1095
    assert card["is_active"] is True
    assert card["attributes"]["voltage"] == "3.2V"
    assert card["provenance"]["title"]["source"] == "1c"
    # без подключённого procurement-шлюза себестоимость None (не 0)
    assert card["landed_cost"] is None


async def test_sku_card_404(api):
    assert (await api.get("/system/sku/НЕТ")).status_code == 404


async def test_sku_card_requires_permission(api, session):
    """Себестоимость — коммерческая тайна: гость без права sales.deal.read получает 403."""
    session.add(Sku(code="SECRET-1", title="Секретный товар", unit="шт"))
    await session.commit()
    # роль без права sales.deal.read и не супер (латиница — заголовки HTTP ASCII)
    r = await api.get("/system/sku/SECRET-1", headers={"X-User-Roles": "warehouse"})
    assert r.status_code == 403


class _LCGateway:
    async def last_landed_cost(self, session, sku_code):
        return {"unit_landed_cost_byn": "214.80", "stage": "estimated", "shipment_id": 7}

    async def last_landed_cost_batch(self, session, sku_codes):
        return {c: await self.last_landed_cost(session, c) for c in sku_codes}


async def test_sku_card_reads_landed_cost_via_gateway(api, session):
    """Если фасад landed_cost подключён — карточка отдаёт себестоимость из него."""
    session.add(Sku(code="AKB-60", title="АКБ 60", unit="шт"))
    await session.commit()

    # подменяем фасад в core тест-приложения (ASGITransport хранит app)
    core = api._transport.app.state.core
    core.services.landed_cost = _LCGateway()
    try:
        card = (await api.get("/system/sku/AKB-60")).json()
        assert card["landed_cost"]["unit_landed_cost_byn"] == "214.80"
        assert card["landed_cost"]["stage"] == "estimated"
    finally:
        core.services.landed_cost = None  # вернуть, чтобы не течь в другие тесты


async def test_sku_card_stock_from_gateway(api, session):
    """Карточка отдаёт остатки/цену/себес по складам через фасад stock (StockItem из 1С)."""
    from decimal import Decimal

    from modules.integrations.models import StockItem

    session.add(Sku(code="ST-1", title="Товар на складе", unit="шт"))
    session.add_all([
        StockItem(sku_code="ST-1", warehouse="Минск", qty_available=Decimal("41"),
                  qty_reserved=Decimal("13"), qty_forecast=Decimal("0"),
                  price=Decimal("320"), cost=Decimal("233.6")),
        StockItem(sku_code="ST-1", warehouse="Гомель", qty_available=Decimal("18"),
                  qty_reserved=Decimal("0"), qty_forecast=Decimal("0"),
                  price=Decimal("320"), cost=Decimal("233.6")),
    ])
    await session.commit()

    st = (await api.get("/system/sku/ST-1")).json()["stock"]
    assert st["total_available"] == 59.0  # 41 + 18
    assert st["total_reserved"] == 13.0
    assert st["price"] == 320.0 and st["cost"] == 233.6  # вход маржи
    assert {r["warehouse"] for r in st["rows"]} == {"Минск", "Гомель"}


async def test_sku_card_stock_none_when_no_stock(api, session):
    """Нет остатков по коду → stock None (отсутствие не маскируем нулём)."""
    session.add(Sku(code="ST-NONE", title="Без остатка", unit="шт"))
    await session.commit()
    assert (await api.get("/system/sku/ST-NONE")).json()["stock"] is None


async def test_sku_card_batches_fefo(api, session):
    """Карточка отдаёт партии (lot/batch) с FEFO-флагом по сроку годности, отсортированные."""
    from datetime import timedelta
    from decimal import Decimal

    from modules.integrations.models import Batch

    today = date.today()
    session.add(Sku(code="B-1", title="Товар с партиями", unit="шт"))
    session.add_all([
        # ok: срок > года; warn: < года; expired: в прошлом; none: без срока
        Batch(sku_code="B-1", lot_no="L-OK", qty=Decimal("10"),
              expiry_date=today + timedelta(days=800), unit_landed_cost=Decimal("231.50")),
        Batch(sku_code="B-1", lot_no="L-WARN", qty=Decimal("5"),
              expiry_date=today + timedelta(days=100)),
        Batch(sku_code="B-1", lot_no="L-EXP", qty=Decimal("3"),
              expiry_date=today - timedelta(days=10)),
        Batch(sku_code="B-1", lot_no="L-NONE", qty=Decimal("7"), expiry_date=None),
    ])
    await session.commit()

    b = (await api.get("/system/sku/B-1")).json()["batches"]
    assert b["total_qty"] == 25.0  # 10+5+3+7
    fefo = {r["lot_no"]: r["fefo"] for r in b["rows"]}
    assert fefo == {"L-OK": "ok", "L-WARN": "warn", "L-EXP": "expired", "L-NONE": "none"}
    # FEFO-порядок: раньше истекающие первыми, без срока — в конец
    assert [r["lot_no"] for r in b["rows"]] == ["L-EXP", "L-WARN", "L-OK", "L-NONE"]
    assert b["rows"][0]["lot_no"] == "L-EXP"
    # nearest_expiry — соонейший НЕ истёкший срок (не дата просроченной L-EXP, хоть та и первая)
    assert b["nearest_expiry"] == (today + timedelta(days=100)).isoformat()
    # landed cost партии прокидывается (вход маржи); где нет — None, не 0
    ok_row = next(r for r in b["rows"] if r["lot_no"] == "L-OK")
    assert ok_row["unit_landed_cost"] == 231.5
    assert next(r for r in b["rows"] if r["lot_no"] == "L-WARN")["unit_landed_cost"] is None


async def test_sku_card_batches_none_when_no_batches(api, session):
    """Нет партий по коду → batches None (отсутствие не маскируем)."""
    session.add(Sku(code="B-NONE", title="Без партий", unit="шт"))
    await session.commit()
    assert (await api.get("/system/sku/B-NONE")).json()["batches"] is None


async def test_sku_card_group_breadcrumb(api, session):
    """group_path — путь по дереву групп от корня к группе товара (для шапки карточки)."""
    root = NomenclatureCategory(code="G-ROOT", name="Электрооборудование")
    session.add(root)
    await session.flush()
    mid = NomenclatureCategory(code="G-MID", name="Аккумуляторы", parent_id=root.id)
    session.add(mid)
    await session.flush()
    session.add(Sku(code="BC-1", title="Товар", unit="шт", category_id=mid.id))
    await session.commit()

    card = (await api.get("/system/sku/BC-1")).json()
    # от корня к листу
    assert [g["code"] for g in card["group_path"]] == ["G-ROOT", "G-MID"]
    assert card["group_path"][1]["name"] == "Аккумуляторы"


async def test_sku_card_group_breadcrumb_empty_without_category(api, session):
    """Нет группы → group_path пустой (не падаем)."""
    session.add(Sku(code="BC-NONE", title="Без группы", unit="шт"))
    await session.commit()
    card = (await api.get("/system/sku/BC-NONE")).json()
    assert card["group_path"] == []


async def test_sku_card_tnved_rates_resolved(api, session):
    """tnved_rates — пошлина + НДС по эффективному коду на сегодня (резолв из справочников)."""
    session.add(VatRate(code="НДС20", title="НДС 20%", rate=20,
                        start_date=date(2024, 1, 1), end_date=None))
    session.add(TnvedCode(code="8507100000", name="Аккумуляторы свинцовые", duty_rate=5,
                          vat_code="НДС20", excise=None, unit="шт",
                          start_date=date(2024, 1, 1), end_date=None))
    session.add(Sku(code="RT-1", title="АКБ", unit="шт", tnved_code="8507100000"))
    await session.commit()

    card = (await api.get("/system/sku/RT-1")).json()
    assert card["tnved_rates"]["duty_rate"] == 5.0
    assert card["tnved_rates"]["vat_rate"] == 20.0


async def test_sku_card_tnved_rates_none_without_code(api, session):
    """Нет эффективного кода ТН ВЭД → tnved_rates None (не выдумываем ставку)."""
    session.add(Sku(code="RT-NONE", title="Без ТН ВЭД", unit="шт"))
    await session.commit()
    card = (await api.get("/system/sku/RT-NONE")).json()
    assert card["tnved_rates"] is None


async def test_sku_card_sync_link(api, session):
    """sync — происхождение и статус выгрузки в 1С; None, если связи нет."""
    sku = Sku(code="SY-1", title="Синк-товар", unit="шт")
    session.add(sku)
    await session.flush()
    session.add(SyncLink(entity_type="sku", entity_id=sku.id, system="1c",
                         external_ref="KA-0001", origin="1c", state="synced"))
    await session.commit()

    card = (await api.get("/system/sku/SY-1")).json()
    assert card["sync"]["origin"] == "1c"
    assert card["sync"]["state"] == "synced"
    assert card["sync"]["external_ref"] == "KA-0001"


async def test_sku_card_sync_none_when_no_link(api, session):
    """Нет SyncLink → sync None (товар не связан с 1С)."""
    session.add(Sku(code="SY-NONE", title="Без синка", unit="шт"))
    await session.commit()
    card = (await api.get("/system/sku/SY-NONE")).json()
    assert card["sync"] is None
