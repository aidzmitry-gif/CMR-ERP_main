"""LOG3-6 — аналитика стоимости с импорт-фрахтом (analytics.import_freight_summary + summarize).

Бизнес-задача: китайское плечо ОТРАЖАЕТ деньги в KPI cost-insights (раньше выпадало).
"""
from __future__ import annotations

import pytest

from modules.logistics.analytics import import_freight_summary, summarize


@pytest.mark.unit
def test_import_freight_summary_empty():
    """Пустой вход → нули."""
    r = import_freight_summary([])
    assert r == {"total": 0.0, "count": 0, "avg": 0.0}


@pytest.mark.unit
def test_import_freight_summary_single():
    """Одна поставка — total=avg=она."""
    r = import_freight_summary([1234.56])
    assert r["total"] == 1234.56
    assert r["count"] == 1
    assert r["avg"] == 1234.56


@pytest.mark.unit
def test_import_freight_summary_multiple():
    """Несколько поставок — корректная сумма и среднее с округлением до копейки."""
    r = import_freight_summary([1000.0, 2000.0, 3000.0])
    assert r["total"] == 6000.0
    assert r["count"] == 3
    assert r["avg"] == 2000.0


@pytest.mark.unit
def test_import_freight_summary_ignores_zero_and_negative():
    """amount<=0 не размывает среднее (это «фрахт ещё не оценён», не «бесплатно»)."""
    r = import_freight_summary([0, 1000, -50, 2000])
    assert r["total"] == 3000.0
    assert r["count"] == 2
    assert r["avg"] == 1500.0


@pytest.mark.unit
def test_summarize_carries_import_freight():
    """summarize встраивает import_freight_* в общий отчёт."""
    r = summarize(
        reference_weight_kg=30,
        zones=[],
        tenders=[],
        audit_to_recover=0,
        import_freight={"total": 5500.0, "avg": 1100.0, "count": 5},
    )
    assert r["import_freight_total"] == 5500.0
    assert r["import_freight_avg"] == 1100.0
    assert r["import_freight_count"] == 5


@pytest.mark.unit
def test_summarize_without_import_freight_defaults_zero():
    """Опускать import_freight можно — выходит нулями (обратная совместимость)."""
    r = summarize(reference_weight_kg=30, zones=[], tenders=[], audit_to_recover=0)
    assert r["import_freight_total"] == 0
    assert r["import_freight_count"] == 0


@pytest.mark.api
async def test_cost_insights_endpoint_returns_import_freight(api):
    """GET /logistics/cost-insights возвращает import_freight_total ровно по warehouse-поставкам.

    B1 ревью круга 3: KPI считается ровно по тем поставкам, фрахт которых УЖЕ ушёл в
    finance (stage='warehouse' + amount>0). Поставка в in_transit — пока не «деньги в финансах».
    """
    # in_transit — НЕ в KPI (фрахт ещё не эмитился в finance)
    await api.post("/logistics/imports", json={
        "supplier": "Shenzhen", "cargo": "Контейнер 1", "qty": 1,
        "amount": 8000.0, "stage": "in_transit", "po_ref": "purchase:c1",
    })
    # 2 warehouse-поставки — попадут в KPI
    await api.post("/logistics/imports", json={
        "supplier": "Shenzhen", "cargo": "Контейнер 2", "qty": 1,
        "amount": 12000.0, "stage": "warehouse", "po_ref": "purchase:c2",
    })
    await api.post("/logistics/imports", json={
        "supplier": "Shenzhen", "cargo": "Контейнер 3", "qty": 1,
        "amount": 5000.0, "stage": "warehouse", "po_ref": "purchase:c3",
    })

    r = await api.get("/logistics/cost-insights")
    assert r.status_code == 200
    body = r.json()
    assert body["import_freight_total"] == 17000.0, "только warehouse-поставки (B1)"
    assert body["import_freight_count"] == 2
    assert body["import_freight_avg"] == 8500.0
