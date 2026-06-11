"""Тесты выработки: табель сборщиков и расчёт ЗП (оклад × дни/22 + н.ч × 6,25)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _add(api, name, salary, days, nh):
    return (
        await api.post(
            "/production/workers",
            json={"name": name, "salary": salary, "days_worked": days, "nh_output": nh},
        )
    ).json()


async def test_create_and_list_workers(api):
    await _add(api, "Михаил", 700.0, 22, 6.3)
    await _add(api, "Артём", 700.0, 22, 4.2)
    rows = (await api.get("/production/workers")).json()
    assert [w["name"] for w in rows] == ["Михаил", "Артём"]


async def test_payroll_formula(api):
    # оклад 660 × 22/22 + 40 н.ч × 6,25 = 660 + 250 = 910; вклад = 40 × 25 = 1000
    await _add(api, "Николай", 660.0, 22, 40.0)
    row = (await api.get("/production/payroll")).json()["rows"][0]
    assert row["base"] == 660.0
    assert row["premium"] == 250.0
    assert row["total"] == 910.0
    assert row["contribution"] == 1000.0


async def test_payroll_partial_days(api):
    # оклад 660 × 11/22 = 330; премия 0 (нет выработки); итог 330
    await _add(api, "Руслан", 660.0, 11, 0.0)
    row = (await api.get("/production/payroll")).json()["rows"][0]
    assert row["base"] == 330.0
    assert row["premium"] == 0.0
    assert row["total"] == 330.0


async def test_payroll_sorted_by_contribution(api):
    await _add(api, "Малый вклад", 700.0, 22, 5.0)
    await _add(api, "Большой вклад", 700.0, 22, 30.0)
    rows = (await api.get("/production/payroll")).json()["rows"]
    assert rows[0]["name"] == "Большой вклад"  # лидер по вкладу первым
    assert rows[0]["contribution"] > rows[1]["contribution"]


async def test_payroll_totals(api):
    await _add(api, "A", 440.0, 22, 10.0)  # base 440, prem 62.5
    await _add(api, "B", 440.0, 22, 20.0)  # base 440, prem 125
    totals = (await api.get("/production/payroll")).json()
    assert totals["total_nh"] == 30.0
    assert totals["total_base"] == 880.0
    assert totals["total_premium"] == 187.5
    assert totals["total_payroll"] == 1067.5


async def test_payroll_empty(api):
    totals = (await api.get("/production/payroll")).json()
    assert totals["rows"] == []
    assert totals["total_payroll"] == 0.0


async def test_update_worker_recalculates(api):
    wid = (await _add(api, "Евгений", 660.0, 22, 0.0))["id"]
    await api.patch(f"/production/workers/{wid}", json={"nh_output": 8.0})
    row = (await api.get("/production/payroll")).json()["rows"][0]
    assert row["premium"] == 50.0  # 8 × 6,25
    assert row["total"] == 710.0   # 660 + 50


async def test_update_worker_404(api):
    assert (await api.patch("/production/workers/999", json={"nh_output": 1.0})).status_code == 404
