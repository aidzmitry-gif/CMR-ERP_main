"""Контракт шлюза landed cost — фасад ядра к себестоимости партии (читать, не считать).

Себестоимость считает модуль ``procurement`` (партия/инвойс/фрахт/пошлина ТН ВЭД/брокер) и
регистрирует реализацию в фасаде: ``core.services.landed_cost = LandedCostService()``. Ядро
держит лишь протокол — карточка номенклатуры и расчёт маржи в сделке читают себестоимость через
``core.services.landed_cost``, НЕ импортируя procurement и не дублируя транзакционные данные (CQRS,
§6). Пока модуль не реализовал — поле ``None``, потребители деградируют (нет себестоимости, не 0).

Возврат ``last_landed_cost`` — ``{unit_landed_cost_byn, shipment_id, fixed_at, stage, fx_rate,
fx_date}`` или ``None`` (нет закрытого расчёта по этой номенклатуре). ``None`` ≠ 0: отсутствие
себестоимости не маскируем нулём (скрыло бы дыру в марже).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class LandedCostGateway(Protocol):
    """Чтение последней посчитанной себестоимости номенклатуры (по коду SKU)."""

    async def last_landed_cost(self, session: AsyncSession, sku_code: str) -> dict | None: ...

    async def last_landed_cost_batch(
        self, session: AsyncSession, sku_codes: list[str]
    ) -> dict[str, dict | None]: ...


# ───────────────────────── Методика распределения (чистая, без БД) ─────────────────────────
# Образец — Odoo ``stock_landed_costs``: общие издержки партии (фрахт/пошлина/брокер/страховка)
# разносятся на позиции по выбранной БАЗЕ (вес/объём/стоимость/кол-во). Чистая функция: ни сессии,
# ни I/O — её зовёт и procurement (фиксация landed партии → ``Batch.unit_landed_cost``), и любой
# калькулятор/прогноз. Деньги в ``Decimal`` (не float), копейки не теряем: остаток округления
# добавляем крупнейшей по базе позиции (как Odoo), чтобы сумма долей == сумме издержки.

Basis = Literal["weight", "volume", "value", "qty", "equal"]  # equal — «по позиции» (фикс-расход)
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class LandedLine:
    """Позиция партии. ``goods_value`` — стоимость товара в валюте расчёта (BYN);
    ``weight``/``volume`` — брутто на всю позицию; ``qty`` — количество."""
    sku_code: str
    qty: Decimal
    weight: Decimal       # кг, брутто на позицию
    volume: Decimal       # м³ на позицию
    goods_value: Decimal  # стоимость товара позиции (без издержек), BYN


@dataclass(frozen=True)
class LandedExpense:
    """Издержка партии, подлежащая разнесению. ``basis`` — база распределения.
    ``recoverable=True`` (ввозной НДС) — не входит в себестоимость, считается отдельно."""
    name: str
    amount: Decimal
    basis: Basis
    recoverable: bool = False


def _money(x: Decimal) -> Decimal:
    return x.quantize(_CENT, rounding=ROUND_HALF_UP)


def _basis_weight(line: LandedLine, basis: Basis) -> Decimal:
    # "equal" — фикс-расход на партию (сертификация и т.п.): база = 1 на позицию → делится поровну.
    table = {"weight": line.weight, "volume": line.volume, "value": line.goods_value,
             "qty": line.qty, "equal": Decimal("1")}
    if basis not in table:  # граница доверия: basis может прийти из БД/JSON, не из Literal
        raise ValueError(f"неизвестная база распределения landed cost: {basis!r}")
    return table[basis]


def allocate_landed_cost(
    lines: list[LandedLine], expenses: list[LandedExpense]
) -> dict:
    """Разнести издержки партии на позиции и вернуть себестоимость единицы.

    Возврат::

        {
          "lines": [{sku_code, goods_value, allocated, landed_total, unit_landed_cost,
                     recoverable}],  # recoverable — разнесённый возмещаемый НДС (справочно)
          "total_goods": Decimal, "total_allocated": Decimal,
          "total_recoverable": Decimal, "total_landed": Decimal,
          "by_expense": [{name, amount, recoverable}, ...],  # список (НЕ по имени: имена
              # могут повторяться, recoverable отделён от себестоимости)
        }

    Каждая издержка делится между позициями пропорционально её доле в выбранной базе.
    При нулевой суммарной базе (напр. нет весов) — делим поровну по количеству позиций.
    Возмещаемые издержки (НДС) разносятся отдельно и НЕ входят в ``landed_total``/``total_allocated``.
    Деньги в копейках: суммовые поля считаются из УЖЕ округлённых строк, поэтому итог == сумме строк.
    ``exp.amount`` пред-округляется до копейки (вход в деньгах и так в центах); базы (вес/объём/
    стоимость) не округляются — используются как пропорции. Сумма долей издержки == её ``amount``.
    """
    if not lines:
        return {"lines": [], "total_goods": Decimal("0"), "total_allocated": Decimal("0"),
                "total_recoverable": Decimal("0"), "total_landed": Decimal("0"), "by_expense": []}

    n = len(lines)
    alloc = [Decimal("0")] * n        # разнесённые НЕвозмещаемые издержки на позицию
    recov = [Decimal("0")] * n        # разнесённый возмещаемый НДС на позицию (справочно)
    by_expense: list[dict] = []

    for exp in expenses:
        amount = _money(exp.amount)
        by_expense.append({"name": exp.name, "amount": amount, "recoverable": exp.recoverable})
        if amount == 0:
            continue
        bases = [_basis_weight(ln, exp.basis) for ln in lines]
        total_base = sum(bases, Decimal("0"))
        # доли по базе; при НУЛЕВОЙ суммарной базе — поровну (ненулевая, в т.ч. отрицательная — пропорция)
        if total_base != 0:
            shares = [_money(amount * b / total_base) for b in bases]
        else:
            even = _money(amount / n)
            shares = [even] * n
        # копейки округления → позиции с наибольшей |долей| (Odoo-стиль), чтобы сумма долей == amount
        drift = amount - sum(shares, Decimal("0"))
        if drift != 0:
            big = max(range(n), key=lambda i: abs(bases[i]) if total_base != 0 else abs(lines[i].qty))
            shares[big] = _money(shares[big] + drift)
        target = recov if exp.recoverable else alloc
        for i, s in enumerate(shares):
            target[i] += s

    out_lines = []
    for i, ln in enumerate(lines):
        goods = _money(ln.goods_value)
        allocated = _money(alloc[i])
        landed_total = _money(goods + allocated)
        unit = _money(landed_total / ln.qty) if ln.qty else Decimal("0")
        out_lines.append({
            "sku_code": ln.sku_code,
            "goods_value": goods,
            "allocated": allocated,
            "landed_total": landed_total,
            "unit_landed_cost": unit,
            "recoverable": _money(recov[i]),
        })

    # итоги — из УЖЕ округлённых строк (иначе итог разойдётся со строками на копейки)
    total_goods = sum((r["goods_value"] for r in out_lines), Decimal("0"))
    total_alloc = sum((r["allocated"] for r in out_lines), Decimal("0"))
    total_recov = sum((r["recoverable"] for r in out_lines), Decimal("0"))
    return {
        "lines": out_lines,
        "total_goods": total_goods,
        "total_allocated": total_alloc,
        "total_recoverable": total_recov,
        "total_landed": sum((r["landed_total"] for r in out_lines), Decimal("0")),
        "by_expense": by_expense,
    }
