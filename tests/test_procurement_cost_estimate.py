"""Тесты предварительной себестоимости импорта (методика «Расчёт Китай»).

Чистый per-line buildup ДО покупки: цена поставщика + комиссия + страховка + фрахт +
пошлина → landed cost BYN/шт (буфер курса ≥10%). Граница с продажами — unit_landed_cost_byn
(цена/наценка/НДС считает полоса «Маржа/ценообразование», тут не считаются).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from modules.procurement.cost_estimate import CostLine, CostRates, estimate_china_cost

D = Decimal


def _rates(**over):
    base = dict(
        usd_byn=D("3.0"),
        cny_rub=D("10"),
        rub_byn=D("0.04"),
        usd_rub=D("90"),
        commission_pct=D("0"),
        insurance_pct=D("0"),
        freight_usd_per_kg=D("0"),
        default_duty_pct=D("0"),
        fx_buffer_pct=D("10"),
    )
    base.update(over)
    return CostRates(**base)


@pytest.mark.unit
def test_cny_path_simple_buffer_only():
    # CNY-путь, только товар + буфер курса 10%:
    # goods/шт = 10 CNY × 10 (cny_rub) = 100 RUB; ×0.04 (rub_byn) ×1.10 = 4.40 BYN
    res = estimate_china_cost(
        [CostLine("A", "cny", price=D("10"), qty=D("100"), weight=D("2"))],
        _rates(),
    )
    assert res["lines"][0]["unit_landed_cost_byn"] == D("4.40")
    assert res["total_landed_byn"] == D("440.00")  # 4.40 × 100


@pytest.mark.unit
def test_usd_path_full_chain_with_util():
    # USD-путь: товар 3000 + комиссия 60 + страховка 30 + фрахт 750 + пошлина 187.5 = 4027.5
    # ×1.10 (буфер) = 4430.25 + утиль 6800 = 11230.25 BYN/шт
    res = estimate_china_cost(
        [
            CostLine(
                "FORK",
                "usd",
                price=D("1000"),
                qty=D("1"),
                weight=D("500"),
                duty_pct=D("5"),
                util=D("6800"),
            )
        ],
        _rates(
            commission_pct=D("2"),
            insurance_pct=D("1"),
            freight_usd_per_kg=D("0.5"),
        ),
    )
    line = res["lines"][0]
    assert line["goods_byn"] == D("3000.00")
    assert line["freight_byn"] == D("750.00")
    assert line["duty_byn"] == D("187.50")
    assert line["util_byn"] == D("6800.00")
    assert line["unit_landed_cost_byn"] == D("11230.25")


@pytest.mark.unit
def test_line_duty_pct_overrides_default():
    # ставка по позиции (ТН ВЭД) важнее дефолтной
    res = estimate_china_cost(
        [CostLine("A", "usd", price=D("100"), qty=D("1"), weight=D("0"), duty_pct=D("0"))],
        _rates(default_duty_pct=D("20")),
    )
    # пошлина 0 (позиция), не 20% → landed = 100×3.0×1.10 = 330.00
    assert res["lines"][0]["unit_landed_cost_byn"] == D("330.00")
    assert res["lines"][0]["duty_byn"] == D("0.00")


@pytest.mark.unit
def test_fx_buffer_floored_at_10():
    # буфер ниже 10 поднимается до 10 (защита прибыли от курсовых колебаний)
    res = estimate_china_cost(
        [CostLine("A", "usd", price=D("100"), qty=D("1"), weight=D("0"))],
        _rates(fx_buffer_pct=D("5")),
    )
    assert res["lines"][0]["unit_landed_cost_byn"] == D("330.00")  # 100×3.0×1.10, не ×1.05


@pytest.mark.asyncio
async def test_cost_estimate_endpoint(api):
    body = {
        "rates": {"usd_byn": 3.0, "cny_rub": 10, "rub_byn": 0.04, "usd_rub": 90, "fx_buffer_pct": 10},
        "lines": [{"sku_code": "A", "path": "cny", "price": 10, "qty": 100, "weight": 2}],
    }
    r = await api.post("/procurement/cost-estimate", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["lines"][0]["unit_landed_cost_byn"] == 4.40
    assert data["total_landed_byn"] == 440.0
