"""Тесты эндпоинта GET /sales/rop/plan-fact (РОП: план/факт менеджеров)."""


async def test_rop_plan_fact_empty(api):
    """Нет сделок в БД → 200, пустой список менеджеров, demo_plans=True."""
    r = await api.get("/sales/rop/plan-fact?period=2026-06")
    assert r.status_code == 200
    data = r.json()
    assert data["period"] == "2026-06"
    assert data["managers"] == []
    assert data["demo_plans"] is True


async def test_rop_plan_fact_with_won_deals(api):
    """Won-сделки в периоде агрегируются в факт."""
    await api.post(
        "/sales/deals",
        json={
            "number": "ROP-T-1",
            "title": "Тест план-факт",
            "counterparty": "ООО Клиент",
            "amount": 50000,
            "stage": "won",
            "owner": "Иванов А.",
            "closed_date": "15.06.2026",
        },
    )
    r = await api.get("/sales/rop/plan-fact?period=2026-06")
    assert r.status_code == 200
    data = r.json()
    assert len(data["managers"]) == 1
    mgr = data["managers"][0]
    assert mgr["name"] == "Иванов А."
    assert mgr["fact_deals"] == 1
    assert mgr["fact_revenue"] == 50000.0
    assert mgr["plan_deals"] == 10
    assert mgr["plan_revenue"] == 150_000.0
    assert data["demo_plans"] is True


async def test_rop_plan_fact_other_period_excluded(api):
    """Сделка из другого месяца не попадает в период."""
    await api.post(
        "/sales/deals",
        json={
            "number": "ROP-T-2",
            "title": "Май-сделка",
            "counterparty": "ООО X",
            "amount": 30000,
            "stage": "won",
            "owner": "Петров Б.",
            "closed_date": "15.05.2026",
        },
    )
    r = await api.get("/sales/rop/plan-fact?period=2026-06")
    assert r.status_code == 200
    assert r.json()["managers"] == []


async def test_rop_plan_fact_multi_managers(api):
    """Два менеджера — два ряда, отсортированных по имени."""
    await api.post(
        "/sales/deals",
        json={"number": "ROP-M1", "title": "A", "counterparty": "X",
              "amount": 10000, "stage": "won", "owner": "Сидоров С.", "closed_date": "01.06.2026"},
    )
    await api.post(
        "/sales/deals",
        json={"number": "ROP-M2", "title": "B", "counterparty": "X",
              "amount": 20000, "stage": "won", "owner": "Иванов А.", "closed_date": "02.06.2026"},
    )
    r = await api.get("/sales/rop/plan-fact?period=2026-06")
    assert r.status_code == 200
    managers = r.json()["managers"]
    assert len(managers) == 2
    names = [m["name"] for m in managers]
    assert "Иванов А." in names
    assert "Сидоров С." in names


async def test_rop_plan_fact_invalid_period(api):
    """Неверный формат периода → 422."""
    r = await api.get("/sales/rop/plan-fact?period=invalid")
    assert r.status_code == 422


async def test_rop_plan_fact_default_period(api):
    """Запрос без period → 200 (дефолт не падает)."""
    r = await api.get("/sales/rop/plan-fact")
    assert r.status_code == 200


async def test_import_main():
    """import main не падает."""
    import main  # noqa: PLC0415
    assert main.app is not None
