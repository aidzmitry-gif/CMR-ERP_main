"""Тесты эндпоинта GET /sales/rop/plan-fact (РОП: план/факт менеджеров).

Эндпоинт агрегирует won-сделки по ``stage_changed_at`` (момент перехода в won,
= now при создании), НЕ по строковому ``closed_date``. Поэтому тесты пляшут от
текущего месяца (``date.today``), а не от захардкоженной даты — иначе «перекат
месяца» ломает их при смене календарного месяца.
"""



async def test_rop_plan_fact_empty(api):
    """Нет сделок в БД → 200, пустой список менеджеров, demo_plans=True."""
    r = await api.get("/sales/rop/plan-fact?period=2026-06")
    assert r.status_code == 200
    data = r.json()
    assert data["period"] == "2026-06"
    assert data["managers"] == []
    assert data["demo_plans"] is True


async def test_rop_plan_fact_with_won_deals(api):
    """Won-сделка текущего месяца агрегируется в факт (фильтр по stage_changed_at=now)."""
    from datetime import date  # noqa: PLC0415

    today = date.today()
    await api.post(
        "/sales/deals",
        json={
            "number": "ROP-T-1",
            "title": "Тест план-факт",
            "counterparty": "ООО Клиент",
            "amount": 50000,
            "stage": "won",
            "owner": "Иванов А.",
            "closed_date": today.strftime("%d.%m.%Y"),
        },
    )
    r = await api.get(f"/sales/rop/plan-fact?period={today.strftime('%Y-%m')}")
    assert r.status_code == 200
    data = r.json()
    assert len(data["managers"]) == 1
    mgr = data["managers"][0]
    assert mgr["name"] == "Иванов А."
    assert mgr["fact_deals"] == 1
    assert mgr["fact_revenue"] == 50000.0
    # план — demo-дефолт эндпоинта; значения косметические, точное число не пиним
    assert mgr["plan_deals"] > 0
    assert mgr["plan_revenue"] > 0
    assert data["demo_plans"] is True


async def test_rop_plan_fact_other_period_excluded(api):
    """Сделка вне запрошенного месяца не попадает в период (stage_changed_at=now)."""
    await api.post(
        "/sales/deals",
        json={
            "number": "ROP-T-2",
            "title": "Сделка вне периода",
            "counterparty": "ООО X",
            "amount": 30000,
            "stage": "won",
            "owner": "Петров Б.",
        },
    )
    # сделка создаётся с stage_changed_at=сейчас → запрашиваем заведомо прошлый месяц
    r = await api.get("/sales/rop/plan-fact?period=2000-01")
    assert r.status_code == 200
    assert r.json()["managers"] == []


async def test_rop_plan_fact_multi_managers(api):
    """Два менеджера — два ряда."""
    from datetime import date  # noqa: PLC0415

    today = date.today()
    d = today.strftime("%d.%m.%Y")
    await api.post(
        "/sales/deals",
        json={"number": "ROP-M1", "title": "A", "counterparty": "X",
              "amount": 10000, "stage": "won", "owner": "Сидоров С.", "closed_date": d},
    )
    await api.post(
        "/sales/deals",
        json={"number": "ROP-M2", "title": "B", "counterparty": "X",
              "amount": 20000, "stage": "won", "owner": "Иванов А.", "closed_date": d},
    )
    r = await api.get(f"/sales/rop/plan-fact?period={today.strftime('%Y-%m')}")
    assert r.status_code == 200
    managers = r.json()["managers"]
    assert len(managers) == 2
    names = [m["name"] for m in managers]
    assert "Иванов А." in names
    assert "Сидоров С." in names


async def test_rop_plan_fact_invalid_period(api):
    """Неверный формат периода → 400 (эндпоинт валидирует period=YYYY-MM вручную)."""
    r = await api.get("/sales/rop/plan-fact?period=invalid")
    assert r.status_code == 400


async def test_rop_plan_fact_default_period(api):
    """Запрос без period → 200 (дефолт не падает)."""
    r = await api.get("/sales/rop/plan-fact")
    assert r.status_code == 200


async def test_import_main():
    """import main не падает."""
    import main  # noqa: PLC0415
    assert main.app is not None
