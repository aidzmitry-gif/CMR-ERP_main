"""Референс-реализация контракта маржи (coordination/pricing-methodology.md §1, §5).

Чистая, без зависимостей — пиннит формулу тестами ДО того, как код ляжет в ``modules/sales``.
Деньги — ``Decimal`` (BYN), как в моделях закупок (``Numeric``/``Decimal``); проценты — доля
``Decimal`` (``Decimal("0.30")`` = 30%). Округление цены к показу — решение собственника (§7.5),
здесь НЕ применяется: маржа считается на точных значениях, округление — downstream.

Перенос в sales: положить как ``modules/sales/pricing.py``; ``unit_landed_cost`` придёт из
``core.services.<costing>.last_landed_cost`` (read-only фасад ядра), ``policy`` — из
``sales.pricing_policy`` каскадом sku→category→default. Сигнатура не меняется.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

GREEN = "green"
YELLOW = "yellow"
RED = "red"
GREY = "grey"  # себестоимость или цена неизвестна — считать маржу не на чем


@dataclass(frozen=True)
class PricingPolicy:
    """Целевые маржи (доли). Инвариант: ``floor`` ≤ ``target`` < 1."""

    target_margin_pct: Decimal
    floor_margin_pct: Decimal

    def __post_init__(self) -> None:
        if not (Decimal(0) <= self.floor_margin_pct <= self.target_margin_pct):
            raise ValueError("floor_margin_pct должен быть в [0, target_margin_pct]")
        if self.target_margin_pct >= Decimal(1):
            raise ValueError("target_margin_pct должен быть < 1 (100% маржи = деление на ноль)")


@dataclass(frozen=True)
class QuotedLine:
    """Результат контракта по строке SKU (см. §1 методики)."""

    sku_code: str
    qty: int
    price: Decimal | None
    unit_landed_cost: Decimal | None
    target_price: Decimal | None
    floor_price: Decimal | None
    line_margin_byn: Decimal | None
    line_margin_pct: Decimal | None
    verdict: str
    reason: str = ""


def price_for_margin(cost: Decimal, margin_pct: Decimal) -> Decimal:
    """Margin-based цена: ``cost / (1 − margin)``. Не cost-plus — авто-поднимает пол при росте cost."""
    return cost / (Decimal(1) - margin_pct)


def quote_line(
    sku_code: str,
    qty: int,
    price: Decimal | None,
    unit_landed_cost: Decimal | None,
    policy: PricingPolicy,
) -> QuotedLine:
    """Посчитать маржу/пороги/вердикт по одной строке SKU.

    ``unit_landed_cost is None`` → ``grey`` (нет закрытого PO — не подставлять 0, иначе
    всё покрасится зелёным и дыра спрячется). ``price is None`` → показываем ориентиры
    цены, но вердикта по цене нет (``grey``).
    """
    if unit_landed_cost is None:
        return QuotedLine(
            sku_code, qty, price, None, None, None, None, None,
            GREY, "нет закрытого PO — себестоимость неизвестна",
        )

    target_price = price_for_margin(unit_landed_cost, policy.target_margin_pct)
    floor_price = price_for_margin(unit_landed_cost, policy.floor_margin_pct)

    if price is None:
        return QuotedLine(
            sku_code, qty, None, unit_landed_cost, target_price, floor_price,
            None, None, GREY, "цена не задана",
        )

    line_margin_byn = (price - unit_landed_cost) * qty
    line_margin_pct = (price - unit_landed_cost) / price if price > 0 else Decimal(0)

    # Порядок: red первым — устойчиво при floor ≤ target (инвариант PricingPolicy).
    if price < floor_price:
        verdict = RED
    elif price >= target_price:
        verdict = GREEN
    else:
        verdict = YELLOW

    return QuotedLine(
        sku_code, qty, price, unit_landed_cost, target_price, floor_price,
        line_margin_byn, line_margin_pct, verdict,
    )


def markup_pct(price: Decimal, cost: Decimal) -> Decimal:
    """Наценка ``(price−cost)/cost`` — НЕ маржа. Только для показа рядом с подписью «наценка» (§2)."""
    return (price - cost) / cost if cost > 0 else Decimal(0)
