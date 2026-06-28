"""LOG3-5 — GET /logistics/imports/in-transit (pull-провайдер нетто-пополнения).

Логистика — read-only источник «что уже едет». MRP-lite круга 4 будет вычитать это
из спроса при заказе закупке (не дозаказывать то, что в пути).

Контракт:
- stage ∈ {factory, consolidation, in_transit, customs} → видим;
- stage == warehouse → НЕ видим (уже приехал);
- пустой результат = 200 [], не 404.
"""
from __future__ import annotations

import pytest


@pytest.mark.api
async def test_in_transit_empty_returns_200_not_404(api):
    """Нет импорт-поставок → 200 [], а не 404 (пусто — валидный ответ)."""
    r = await api.get("/logistics/imports/in-transit")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.api
async def test_in_transit_returns_only_moving_stages(api):
    """Возвращает только грузы в движении, не warehouse."""
    for stage in ("factory", "consolidation", "in_transit", "customs", "warehouse"):
        await api.post("/logistics/imports", json={
            "supplier": f"Поставщик-{stage}", "cargo": f"Груз-{stage}", "qty": 10,
            "po_ref": f"purchase:in-{stage}", "stage": stage, "eta": "2026-08-01",
        })

    r = await api.get("/logistics/imports/in-transit")
    assert r.status_code == 200
    rows = r.json()
    stages = {row["stage"] for row in rows}
    assert stages == {"factory", "consolidation", "in_transit", "customs"}, (
        "warehouse не должен попадать в in-transit"
    )


@pytest.mark.api
async def test_in_transit_shape_has_required_fields(api):
    """Поля ответа: po_ref, cargo, qty, eta, stage."""
    await api.post("/logistics/imports", json={
        "supplier": "X", "cargo": "Чехлы", "qty": 250,
        "po_ref": "purchase:1001", "stage": "in_transit", "eta": "2026-07-30",
    })
    r = await api.get("/logistics/imports/in-transit")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["po_ref"] == "purchase:1001"
    assert row["cargo"] == "Чехлы"
    assert row["qty"] == 250
    assert row["eta"] == "2026-07-30"
    assert row["stage"] == "in_transit"


@pytest.mark.api
async def test_in_transit_excludes_warehouse_only(api):
    """Только warehouse исключается; новые-сторонние стадии НЕ возвращаются (whitelist)."""
    await api.post("/logistics/imports", json={
        "supplier": "Y", "cargo": "Тест", "qty": 1,
        "po_ref": "purchase:wh", "stage": "warehouse",
    })
    rows = (await api.get("/logistics/imports/in-transit")).json()
    assert rows == [], "warehouse не in-transit"
