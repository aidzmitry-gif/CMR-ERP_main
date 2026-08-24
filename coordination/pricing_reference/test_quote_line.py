"""Тесты референс-реализации quote_line (пиннят формулу маржи из методики §5).

Запуск без pytest-конфига проекта (чтобы не тянуть coverage/маркеры):
    python coordination/pricing_reference/test_quote_line.py
Также совместимо с pytest (функции test_*, обычные assert).
"""
from __future__ import annotations

from decimal import Decimal

from quote_line import (
    GREEN,
    GREY,
    RED,
    YELLOW,
    PricingPolicy,
    markup_pct,
    price_for_margin,
    quote_line,
)

POL = PricingPolicy(target_margin_pct=Decimal("0.30"), floor_margin_pct=Decimal("0.18"))


def test_margin_is_not_markup():
    # классическая ловушка: наценка 50% = маржа 33%
    line = quote_line("A", 1, Decimal("150"), Decimal("100"), POL)
    assert markup_pct(Decimal("150"), Decimal("100")) == Decimal("0.5")
    assert line.line_margin_pct == (Decimal("50") / Decimal("150"))  # ≈0.3333, НЕ 0.5


def test_price_for_margin_is_margin_based():
    # target_price = cost / (1 − margin); margin-based, не cost-plus
    assert price_for_margin(Decimal("100"), Decimal("0.30")) == Decimal("100") / Decimal("0.7")


def test_verdict_green_at_and_above_target():
    target = price_for_margin(Decimal("100"), POL.target_margin_pct)
    assert quote_line("A", 1, target, Decimal("100"), POL).verdict == GREEN          # ровно target → green
    assert quote_line("A", 1, target + 1, Decimal("100"), POL).verdict == GREEN      # выше → green


def test_verdict_yellow_between_floor_and_target():
    floor = price_for_margin(Decimal("100"), POL.floor_margin_pct)
    target = price_for_margin(Decimal("100"), POL.target_margin_pct)
    mid = (floor + target) / 2
    assert floor < mid < target
    assert quote_line("A", 1, mid, Decimal("100"), POL).verdict == YELLOW
    assert quote_line("A", 1, floor, Decimal("100"), POL).verdict == YELLOW          # ровно floor → yellow (не red)


def test_verdict_red_below_floor():
    floor = price_for_margin(Decimal("100"), POL.floor_margin_pct)
    assert quote_line("A", 1, floor - 1, Decimal("100"), POL).verdict == RED


def test_grey_when_cost_unknown_never_zero():
    line = quote_line("A", 5, Decimal("100"), None, POL)
    assert line.verdict == GREY
    assert line.unit_landed_cost is None
    assert line.line_margin_byn is None          # НЕ 0 — иначе дыра спрячется
    assert "PO" in line.reason


def test_grey_when_price_not_set_shows_anchors():
    line = quote_line("A", 1, None, Decimal("100"), POL)
    assert line.verdict == GREY
    assert line.target_price == price_for_margin(Decimal("100"), POL.target_margin_pct)
    assert line.floor_price == price_for_margin(Decimal("100"), POL.floor_margin_pct)
    assert line.line_margin_pct is None


def test_line_margin_byn_multiplies_qty():
    line = quote_line("A", 4, Decimal("150"), Decimal("100"), POL)
    assert line.line_margin_byn == Decimal("200")   # (150−100)×4


def test_policy_rejects_floor_above_target():
    try:
        PricingPolicy(target_margin_pct=Decimal("0.20"), floor_margin_pct=Decimal("0.30"))
    except ValueError:
        return
    raise AssertionError("ожидался ValueError при floor > target")


def test_policy_rejects_margin_ge_one():
    try:
        PricingPolicy(target_margin_pct=Decimal("1.0"), floor_margin_pct=Decimal("0.5"))
    except ValueError:
        return
    raise AssertionError("ожидался ValueError при target_margin_pct ≥ 1 (деление на ноль)")


def _run() -> int:
    tests = sorted(n for n in globals() if n.startswith("test_"))
    failed = 0
    for name in tests:
        try:
            globals()[name]()
            print(f"  ok  {name}")
        except Exception as exc:  # noqa: BLE001 — self-runner
            failed += 1
            print(f" FAIL {name}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
