"""Тесты планирования производства: матрица план/факт, норма из справочника,
факт из завершённых нарядов, мощность/загрузка, YTD, удаление позиции."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc)
YEAR = NOW.year
MONTH = NOW.month  # 1..12
P = "Аккумулятор 32 LiFePO4 (погрузчик)"
Q = "Прочие АКБ и сборки"


def _row(board: dict, product: str) -> dict | None:
    return next((r for r in board["rows"] if r["product"] == product), None)


async def _approve_norm(api, title: str, nh: float) -> None:
    norm = (await api.post("/production/norms", json={"title": title, "nh": nh})).json()
    await api.post(f"/production/norms/{norm['id']}/approve")


# ===== План: ячейка и позиция =====


async def test_put_cell_creates_then_updates(api):
    b = (await api.put("/production/plan/cell",
                       json={"year": YEAR, "product": P, "month": 3, "plan_qty": 10})).json()
    assert _row(b, P)["months"][2]["plan_qty"] == 10
    # повторный PUT той же ячейки — обновляет, не дублирует строку (уникальность)
    b = (await api.put("/production/plan/cell",
                       json={"year": YEAR, "product": P, "month": 3, "plan_qty": 20})).json()
    assert [r for r in b["rows"] if r["product"] == P] != []
    assert sum(1 for r in b["rows"] if r["product"] == P) == 1
    assert _row(b, P)["months"][2]["plan_qty"] == 20


async def test_post_position_writes_year(api):
    monthly = list(range(1, 13))  # 1..12
    r = await api.post("/production/plan/position",
                       json={"year": YEAR, "product": P, "monthly": monthly})
    assert r.status_code == 201
    row = _row(r.json(), P)
    assert row["year_qty"] == sum(monthly)  # 78
    assert [c["plan_qty"] for c in row["months"]] == monthly


# ===== Норма из справочника =====


async def test_norm_nh_from_approved_norm(api):
    await _approve_norm(api, P, 2.5)
    b = (await api.put("/production/plan/cell",
                       json={"year": YEAR, "product": P, "month": 1, "plan_qty": 10})).json()
    row = _row(b, P)
    assert row["norm_nh"] == 2.5
    assert row["months"][0]["plan_nh"] == 25.0  # 10 × 2.5


async def test_no_norm_means_zero_nh(api):
    b = (await api.put("/production/plan/cell",
                       json={"year": YEAR, "product": Q, "month": 1, "plan_qty": 10})).json()
    row = _row(b, Q)
    assert row["norm_nh"] == 0.0
    assert row["months"][0]["plan_nh"] == 0.0


# ===== Факт из завершённых нарядов =====


async def test_fact_from_completed_orders(api):
    await _approve_norm(api, P, 2.0)
    order = (await api.post("/production/orders", json={"product": P, "qty": 4})).json()
    await api.patch(f"/production/orders/{order['id']}", json={"stage": "done"})
    # наряд другого изделия и незавершённый — в факт P не попадают
    other = (await api.post("/production/orders", json={"product": Q, "qty": 9})).json()
    await api.patch(f"/production/orders/{other['id']}", json={"stage": "done"})
    in_progress = (await api.post("/production/orders", json={"product": P, "qty": 7})).json()
    await api.patch(f"/production/orders/{in_progress['id']}", json={"stage": "assembly"})

    b = (await api.get(f"/production/plan?year={YEAR}")).json()
    cell = _row(b, P)["months"][MONTH - 1]
    assert cell["fact_qty"] == 4         # только завершённый наряд P
    assert cell["fact_nh"] == 8.0        # 4 × 2.0


async def test_fact_ignores_other_year(api):
    await _approve_norm(api, P, 2.0)
    order = (await api.post("/production/orders", json={"product": P, "qty": 4})).json()
    await api.patch(f"/production/orders/{order['id']}", json={"stage": "done"})
    b = (await api.get(f"/production/plan?year={YEAR - 1}")).json()
    assert _row(b, P) is None  # факт прошлого года пуст → строки нет


# ===== Мощность и загрузка =====


async def test_capacity_from_worker_count(api):
    # без сборщиков мощность = max(1,0) × 176
    b = (await api.get(f"/production/plan?year={YEAR}")).json()
    assert b["capacity_nh"] == 176.0
    for n in range(3):
        await api.post("/production/workers", json={"name": f"Сборщик {n}"})
    b = (await api.get(f"/production/plan?year={YEAR}")).json()
    assert b["capacity_nh"] == 3 * 176.0  # 528


async def test_load_pct(api):
    await _approve_norm(api, P, 100.0)  # 1 шт = 100 н.ч; мощность без рабочих = 176
    await api.put("/production/plan/cell",
                  json={"year": YEAR, "product": P, "month": 1, "plan_qty": 1})
    b = (await api.get(f"/production/plan?year={YEAR}")).json()
    assert b["totals"]["month_nh"][0] == 100.0
    assert b["totals"]["load_pct"][0] == round(100.0 / 176.0 * 100, 1)


# ===== YTD, пик/спад =====


async def test_ytd_and_peak_low(api):
    await _approve_norm(api, P, 1.0)  # н.ч = qty
    monthly = list(range(1, 13))      # month_nh = [1..12]
    await api.post("/production/plan/position",
                   json={"year": YEAR, "product": P, "monthly": monthly})
    t = (await api.get(f"/production/plan?year={YEAR}")).json()["totals"]
    assert t["peak_month"] == 11  # декабрь — макс. загрузка
    assert t["low_month"] == 0    # январь — мин.
    assert t["plan_ytd"] == float(sum(monthly[:MONTH]))  # сумма по текущий месяц включ.
    assert t["fact_ytd"] == 0.0


# ===== Удаление позиции =====


async def test_delete_position(api):
    await api.post("/production/plan/position",
                   json={"year": YEAR, "product": P, "monthly": [5] * 12})
    assert _row((await api.get(f"/production/plan?year={YEAR}")).json(), P) is not None
    r = await api.delete(f"/production/plan/position?year={YEAR}&product={P}")
    assert r.status_code == 204
    assert _row((await api.get(f"/production/plan?year={YEAR}")).json(), P) is None
