"""Тесты аналитики производства (read-model): pass-rate/FPY/брак из ОТК,
эффективность/премия из табеля, серии план/факт и топ изделий."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.asyncio

YEAR = datetime.now(timezone.utc).year
P = "Аккумулятор 32 LiFePO4 (погрузчик)"


async def _approve_norm(api, title: str, nh: float) -> None:
    norm = (await api.post("/production/norms", json={"title": title, "nh": nh})).json()
    await api.post(f"/production/norms/{norm['id']}/approve")


async def test_empty_analytics_zero(api):
    a = (await api.get("/production/analytics")).json()
    assert a["fpy_pct"] == 0.0
    assert a["pass_rate_pct"] == 0.0
    assert a["scrap_pct"] == 0.0
    assert a["premium_fot_byn"] == 0.0
    assert len(a["plan_fact_by_month"]) == 12


async def test_qc_rates(api):
    for decision in ("accept", "accept", "rework", "scrap"):
        await api.post("/production/qc/decisions",
                       json={"decision": decision, "reason": "трещина" if decision == "scrap" else ""})
    a = (await api.get("/production/analytics")).json()
    assert a["fpy_pct"] == 50.0        # 2 accept / 4
    assert a["pass_rate_pct"] == 75.0  # (2 accept + 1 rework) / 4
    assert a["scrap_pct"] == 25.0      # 1 scrap / 4
    assert a["scrap_reasons"] == [{"reason": "трещина", "count": 1}]


async def test_team_and_premium(api):
    await api.post("/production/workers",
                   json={"name": "Иванов", "days_worked": 20, "nh_output": 80.0})
    await api.post("/production/workers",
                   json={"name": "Петров", "days_worked": 10, "nh_output": 20.0})
    a = (await api.get("/production/analytics")).json()
    # эффективность = выработка(100) / (часы 30×8=240) × 100
    assert a["efficiency_pct"] == round(100.0 / 240 * 100, 1)
    assert a["premium_fot_byn"] == round(100.0 * 6.25, 2)  # 625.0
    assert a["team_contribution"][0]["name"] == "Иванов"   # лидер по выработке
    assert a["team_contribution"][0]["share_pct"] == 80.0


async def test_plan_fact_series_and_top(api):
    await _approve_norm(api, P, 2.0)
    await api.post("/production/plan/position",
                   json={"year": YEAR, "product": P, "monthly": [5] * 12})
    order = (await api.post("/production/orders", json={"product": P, "qty": 3})).json()
    await api.patch(f"/production/orders/{order['id']}", json={"stage": "done"})
    a = (await api.get(f"/production/analytics?year={YEAR}")).json()
    assert a["vyrabotka_fact_nh"] == 6.0  # 3 шт × 2.0 н.ч
    assert a["top_products"][0] == {"product": P, "fact_nh": 6.0}
    assert sum(m["plan_nh"] for m in a["plan_fact_by_month"]) == 5 * 12 * 2.0  # 120
