"""REF3-1/3 — read-фасад мастер-входов SKU + тест-мост сходимости с landed cost ядра.

Доказываем, что вес/пошлина, которые отдаёт ``core.services.sku_master.landed_inputs``,
детерминированно питают общий движок ``core.services.landed_cost.allocate_landed_cost``
(контракт на стыке reference→landed без захода в ``modules/procurement``).
"""
from datetime import date
from decimal import Decimal

from core.domain.models import Sku
from core.domain.reference import TnvedCode, VatRate
from core.services import scd2, sku_master
from core.services.landed_cost import LandedExpense, LandedLine, allocate_landed_cost


async def _seed_tnved(session) -> None:
    """ТН ВЭД 8507 с пошлиной 10% и НДС 20% на дату — известный вход для расчёта."""
    session.add(VatRate(code="НДС20", title="НДС 20%", rate=Decimal("20"), start_date=date(2020, 1, 1)))
    session.add(
        TnvedCode(
            code="8507", name="аккумуляторы", duty_rate=Decimal("10"),
            vat_code="НДС20", start_date=date(2020, 1, 1),
        )
    )


async def test_landed_inputs_own_tnved_resolves_rates(session):
    await _seed_tnved(session)
    session.add(Sku(code="A", title="Аккум", unit="шт", weight_kg=3.0, volume_m3=0.2, tnved_code="8507"))
    await session.commit()

    inp = await sku_master.landed_inputs(session, "A", date(2024, 6, 1))
    assert inp["weight_kg"] == 3.0
    assert inp["volume_m3"] == 0.2
    assert inp["duty_pct"] == 10.0
    assert inp["vat_rate"] == 20.0
    assert inp["effective_tnved"]["code"] == "8507"
    assert inp["provenance"]["tnved"] == "own"
    assert inp["provenance"]["vat"] == "tnved"  # НДС взят от кода ТН ВЭД (своего/группового нет)


async def test_landed_inputs_group_tnved_same_rates(session):
    """SKU без своего ТН ВЭД, но с кодом от группы → те же ставки, source=group."""
    from core.domain.reference import NomenclatureCategory

    await _seed_tnved(session)
    cat = NomenclatureCategory(code="CAT", name="Группа", tnved_code="8507")
    session.add(cat)
    await session.flush()
    session.add(Sku(code="B", title="Без своего ТН", unit="шт", weight_kg=1.0, category_id=cat.id))
    await session.commit()

    inp = await sku_master.landed_inputs(session, "B", date(2024, 6, 1))
    assert inp["effective_tnved"]["code"] == "8507"
    assert inp["effective_tnved"]["source"] == "group"
    assert inp["duty_pct"] == 10.0  # ставки те же, что у своего кода
    assert inp["provenance"]["tnved"] == "group"


async def test_landed_inputs_unknown_sku_is_none(session):
    assert await sku_master.landed_inputs(session, "NOPE") is None  # None, НЕ нули


async def test_landed_inputs_zero_weight_normalized_to_none(session):
    """0.0 вес/объём = дыра в данных → нормализуем в None + провенанс none (не маскируем нулём)."""
    await _seed_tnved(session)
    session.add(Sku(code="Z", title="нулевой", unit="шт", weight_kg=0.0, volume_m3=0.0, tnved_code="8507"))
    await session.commit()
    inp = await sku_master.landed_inputs(session, "Z", date(2024, 6, 1))
    assert inp["weight_kg"] is None and inp["volume_m3"] is None
    assert inp["provenance"]["weight"] == "none" and inp["provenance"]["volume"] == "none"


async def test_landed_inputs_batch_one_answer(session):
    await _seed_tnved(session)
    session.add_all([
        Sku(code="A", title="A", unit="шт", weight_kg=3.0, tnved_code="8507"),
        Sku(code="B", title="B", unit="шт", weight_kg=1.0, tnved_code="8507"),
    ])
    await session.commit()

    res = await sku_master.landed_inputs_batch(session, ["A", "B", "NOPE"], date(2024, 6, 1))
    assert set(res) == {"A", "B", "NOPE"}
    assert res["A"]["duty_pct"] == 10.0 and res["B"]["weight_kg"] == 1.0
    assert res["NOPE"] is None  # неизвестный код — связный ответ, не пропуск


async def test_bridge_weight_and_duty_feed_allocation(session):
    """Вес+duty_pct из фасада → детерминированная база разнесения и сумма пошлины."""
    await _seed_tnved(session)
    session.add_all([
        Sku(code="A", title="A", unit="шт", weight_kg=3.0, tnved_code="8507"),
        Sku(code="B", title="B", unit="шт", weight_kg=1.0, tnved_code="8507"),
    ])
    await session.commit()

    on = date(2024, 6, 1)
    inp = await sku_master.landed_inputs_batch(session, ["A", "B"], on)
    lines = [
        LandedLine(
            sku_code=c, qty=Decimal("1"),
            weight=Decimal(str(inp[c]["weight_kg"])), volume=Decimal("0"),
            goods_value=Decimal("1000"),
        )
        for c in ("A", "B")
    ]
    # пошлина по ставке справочника на каждую позицию (база — стоимость 1:1)
    duty_total = sum(
        (Decimal("1000") * Decimal(str(inp[c]["duty_pct"])) / Decimal("100") for c in ("A", "B")),
        Decimal("0"),
    )
    res = allocate_landed_cost(
        lines,
        [LandedExpense("фрахт", Decimal("400"), basis="weight"),
         LandedExpense("пошлина", duty_total, basis="value")],
    )
    by = {ln["sku_code"]: ln for ln in res["lines"]}
    # фрахт 400 по весу 3:1 → 300/100; пошлина 200 по стоимости 1:1 → 100/100
    assert by["A"]["allocated"] == Decimal("400.00")
    assert by["B"]["allocated"] == Decimal("200.00")
    assert res["total_landed"] == Decimal("2600.00")  # 2000 товар + 400 фрахт + 200 пошлина


async def test_bridge_rate_change_shifts_input_by_delta(session):
    """Смена ставки ТН ВЭД новой SCD2-версией → landed-вход меняется ровно на дельту."""
    await _seed_tnved(session)
    session.add(Sku(code="A", title="A", unit="шт", weight_kg=2.0, tnved_code="8507"))
    await session.commit()

    before = await sku_master.landed_inputs(session, "A", date(2024, 1, 1))
    # новая версия пошлины 15% с 2025-01-01 (закрывает текущую)
    await scd2.add_version(
        session, TnvedCode, "code", "8507", date(2025, 1, 1),
        name="аккумуляторы", duty_rate=Decimal("15"), vat_code="НДС20",
    )
    await session.commit()
    after = await sku_master.landed_inputs(session, "A", date(2025, 6, 1))

    assert before["duty_pct"] == 10.0
    assert after["duty_pct"] == 15.0
    # пошлина на товар 1000 BYN сдвигается ровно на дельту ставки (5% → 50 BYN)
    delta = (Decimal("1000") * Decimal(str(after["duty_pct"])) / 100) - (
        Decimal("1000") * Decimal(str(before["duty_pct"])) / 100
    )
    assert delta == Decimal("50")


# ── REF3-2 эндпоинт GET /system/sku/{code}/landed-inputs ──────────────────────


async def test_landed_inputs_endpoint_returns_rates(api, session):
    await _seed_tnved(session)
    session.add(Sku(code="A", title="A", unit="шт", weight_kg=3.0, volume_m3=0.2, tnved_code="8507"))
    await session.commit()
    r = await api.get("/system/sku/A/landed-inputs?on_date=2024-06-01")
    assert r.status_code == 200
    body = r.json()
    assert body["duty_pct"] == 10.0 and body["vat_rate"] == 20.0
    assert body["weight_kg"] == 3.0 and body["volume_m3"] == 0.2


async def test_landed_inputs_endpoint_requires_sales_read(api, session):
    await _seed_tnved(session)
    session.add(Sku(code="A", title="A", unit="шт", weight_kg=3.0, tnved_code="8507"))
    await session.commit()
    r = await api.get("/system/sku/A/landed-inputs", headers={"X-User-Roles": "warehouse"})
    assert r.status_code in (401, 403)  # коммерческий вход маржи — под sales.deal.read


async def test_landed_inputs_endpoint_before_version_is_none(api, session):
    await _seed_tnved(session)  # версия ТН ВЭД открыта с 2020-01-01
    session.add(Sku(code="A", title="A", unit="шт", weight_kg=3.0, tnved_code="8507"))
    await session.commit()
    r = await api.get("/system/sku/A/landed-inputs?on_date=2019-01-01")
    assert r.status_code == 200
    assert r.json()["duty_pct"] is None  # до открытия версии — None, не падение


async def test_landed_inputs_endpoint_unknown_404(api):
    assert (await api.get("/system/sku/NOPE/landed-inputs")).status_code == 404
