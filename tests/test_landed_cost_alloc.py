"""Методика распределения landed cost (чистая функция, образец Odoo stock_landed_costs).

Разнос издержек партии (фрахт/пошлина/брокер/НДС) на позиции по базе вес/объём/стоимость/кол-во.
Деньги в Decimal: сумма разнесённого == сумме издержки (копейки на крупнейшую позицию), НДС
recoverable не входит в себестоимость.
"""
from decimal import Decimal

import pytest

from core.services.landed_cost import (
    LandedExpense,
    LandedLine,
    allocate_landed_cost,
)

pytestmark = pytest.mark.unit

D = Decimal


def _lines():
    # вес 6/14, объём 0.02/0.04, стоимость 100/300
    return [
        LandedLine("A", qty=D("10"), weight=D("6"), volume=D("0.02"), goods_value=D("100")),
        LandedLine("B", qty=D("30"), weight=D("14"), volume=D("0.04"), goods_value=D("300")),
    ]


def test_allocate_by_weight_shares_sum_to_expense():
    # фрахт 200 по весу: доли 6/20 и 14/20 → 60 / 140
    res = allocate_landed_cost(_lines(), [LandedExpense("фрахт", D("200"), "weight")])
    a, b = res["lines"]
    assert a["allocated"] == D("60.00")
    assert b["allocated"] == D("140.00")
    assert res["total_allocated"] == D("200.00")  # копейки не потеряны


def test_allocate_by_value():
    # пошлина 40 по стоимости: 100/400 и 300/400 → 10 / 30
    res = allocate_landed_cost(_lines(), [LandedExpense("пошлина", D("40"), "value")])
    a, b = res["lines"]
    assert a["allocated"] == D("10.00")
    assert b["allocated"] == D("30.00")


def test_allocate_by_volume():
    # логистика 60 по объёму: 0.02/0.06 и 0.04/0.06 → 20 / 40
    res = allocate_landed_cost(_lines(), [LandedExpense("логистика", D("60"), "volume")])
    a, b = res["lines"]
    assert a["allocated"] == D("20.00")
    assert b["allocated"] == D("40.00")


def test_landed_total_and_unit():
    # товар 100/300 + фрахт по весу 60/140 → landed 160/440 → unit 16 / 14.666... ≈ 14.67
    res = allocate_landed_cost(_lines(), [LandedExpense("фрахт", D("200"), "weight")])
    a, b = res["lines"]
    assert a["landed_total"] == D("160.00")
    assert a["unit_landed_cost"] == D("16.00")
    assert b["landed_total"] == D("440.00")
    assert b["unit_landed_cost"] == D("14.67")
    assert res["total_landed"] == D("600.00")  # 400 товар + 200 фрахт


def test_recoverable_vat_excluded_from_landed():
    # ввозной НДС 80 (recoverable) — НЕ в себестоимость, считается отдельно
    res = allocate_landed_cost(
        _lines(),
        [LandedExpense("ввозной НДС", D("80"), "value", recoverable=True)],
    )
    assert res["total_allocated"] == D("0.00")          # в landed не попал
    assert res["total_recoverable"] == D("80.00")        # учтён отдельно
    assert res["total_landed"] == res["total_goods"]     # себестоимость = только товар
    a, b = res["lines"]
    assert a["recoverable"] == D("20.00") and b["recoverable"] == D("60.00")


def test_rounding_drift_goes_to_largest_line():
    # 100 по стоимости при долях с бесконечной дробью: сумма долей строго == 100
    lines = [
        LandedLine("A", qty=D("1"), weight=D("1"), volume=D("0.01"), goods_value=D("100")),
        LandedLine("B", qty=D("1"), weight=D("1"), volume=D("0.01"), goods_value=D("200")),
        LandedLine("C", qty=D("1"), weight=D("1"), volume=D("0.01"), goods_value=D("400")),
    ]
    res = allocate_landed_cost(lines, [LandedExpense("брокер", D("100"), "value")])
    assert res["total_allocated"] == D("100.00")
    assert sum(ln["allocated"] for ln in res["lines"]) == D("100.00")


def test_zero_base_splits_evenly():
    # сертификация по весу, но веса нулевые → делим поровну по позициям
    lines = [
        LandedLine("A", qty=D("5"), weight=D("0"), volume=D("0"), goods_value=D("100")),
        LandedLine("B", qty=D("5"), weight=D("0"), volume=D("0"), goods_value=D("100")),
    ]
    res = allocate_landed_cost(lines, [LandedExpense("сертификация", D("50"), "weight")])
    a, b = res["lines"]
    assert a["allocated"] == D("25.00") and b["allocated"] == D("25.00")


def test_multiple_expenses_mixed_bases():
    # фрахт по весу + пошлина по стоимости + НДС recoverable
    res = allocate_landed_cost(
        _lines(),
        [
            LandedExpense("фрахт", D("200"), "weight"),
            LandedExpense("пошлина", D("40"), "value"),
            LandedExpense("ввозной НДС", D("80"), "value", recoverable=True),
        ],
    )
    a, b = res["lines"]
    assert a["allocated"] == D("70.00")   # 60 фрахт + 10 пошлина
    assert b["allocated"] == D("170.00")  # 140 + 30
    assert res["total_allocated"] == D("240.00")
    assert res["total_recoverable"] == D("80.00")
    by_name = {e["name"]: e for e in res["by_expense"]}
    assert by_name["фрахт"]["amount"] == D("200.00")
    assert by_name["пошлина"]["amount"] == D("40.00")
    # by_expense — список: возмещаемый НДС помечен, в total_allocated не входит
    nds = next(e for e in res["by_expense"] if e["recoverable"])
    assert nds["name"] == "ввозной НДС" and nds["amount"] == D("80.00")


def test_by_expense_keeps_duplicate_names_separate():
    # две издержки с одним именем но разной базой — НЕ схлопываются в одну запись
    res = allocate_landed_cost(
        _lines(),
        [LandedExpense("доставка", D("200"), "weight"), LandedExpense("доставка", D("40"), "value")],
    )
    dostavka = [e for e in res["by_expense"] if e["name"] == "доставка"]
    assert len(dostavka) == 2
    assert {e["amount"] for e in dostavka} == {D("200.00"), D("40.00")}


def test_qty_basis():
    # сбор по количеству: qty 10/30 → 50/150 при amount 200
    res = allocate_landed_cost(_lines(), [LandedExpense("сбор", D("200"), "qty")])
    a, b = res["lines"]
    assert a["allocated"] == D("50.00") and b["allocated"] == D("150.00")
    assert res["total_allocated"] == D("200.00")


def test_totals_equal_sum_of_lines_subcent():
    # sub-копеечные goods_value: итог == сумме строк (а не округление сырой суммы)
    lines = [
        LandedLine("A", qty=D("1"), weight=D("1"), volume=D("0.01"), goods_value=D("10.005")),
        LandedLine("B", qty=D("1"), weight=D("1"), volume=D("0.01"), goods_value=D("10.005")),
    ]
    res = allocate_landed_cost(lines, [])
    assert res["total_goods"] == sum(r["goods_value"] for r in res["lines"])
    assert res["total_landed"] == sum(r["landed_total"] for r in res["lines"])


def test_volume_basis_drift_sum_holds():
    # объём с дробью, дающей drift: сумма долей строго == amount
    lines = [
        LandedLine("A", qty=D("1"), weight=D("1"), volume=D("0.01"), goods_value=D("100")),
        LandedLine("B", qty=D("1"), weight=D("1"), volume=D("0.01"), goods_value=D("100")),
        LandedLine("C", qty=D("1"), weight=D("1"), volume=D("0.01"), goods_value=D("100")),
    ]
    res = allocate_landed_cost(lines, [LandedExpense("логистика", D("100"), "volume")])
    assert res["total_allocated"] == D("100.00")
    assert sum(ln["allocated"] for ln in res["lines"]) == D("100.00")


def test_unknown_basis_raises():
    with pytest.raises(ValueError):
        allocate_landed_cost(_lines(), [LandedExpense("x", D("10"), "cost")])


def test_equal_basis_fixed_fee_per_position():
    # сертификация 85 «по позиции» (equal) — поровну по позициям независимо от веса/qty
    res = allocate_landed_cost(_lines(), [LandedExpense("сертификация", D("85"), "equal")])
    a, b = res["lines"]
    assert a["allocated"] == D("42.50") and b["allocated"] == D("42.50")
    assert res["total_allocated"] == D("85.00")


def test_negative_expense_credit_note():
    # возврат части пошлины (кредит-нота) — отрицательная издержка уменьшает себестоимость
    res = allocate_landed_cost(_lines(), [LandedExpense("возврат пошлины", D("-40"), "value")])
    a, b = res["lines"]
    assert a["allocated"] == D("-10.00") and b["allocated"] == D("-30.00")
    assert res["total_allocated"] == D("-40.00")
    assert res["total_landed"] == D("360.00")  # 400 товар − 40 возврат


def test_negative_drift_sum_holds():
    # 0.20 по стоимости на 3 равные позиции → доли с отрицательным drift, сумма строго 0.20
    lines = [
        LandedLine("A", qty=D("1"), weight=D("1"), volume=D("0.01"), goods_value=D("100")),
        LandedLine("B", qty=D("1"), weight=D("1"), volume=D("0.01"), goods_value=D("100")),
        LandedLine("C", qty=D("1"), weight=D("1"), volume=D("0.01"), goods_value=D("100")),
    ]
    res = allocate_landed_cost(lines, [LandedExpense("сбор", D("0.20"), "value")])
    assert res["total_allocated"] == D("0.20")
    assert sum(ln["allocated"] for ln in res["lines"]) == D("0.20")


def test_empty_lines_returns_zeros():
    res = allocate_landed_cost([], [LandedExpense("фрахт", D("200"), "weight")])
    assert res["lines"] == []
    assert res["total_landed"] == D("0")
