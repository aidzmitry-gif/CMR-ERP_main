"""БД-зависимые тесты модуля Sales (SQLite в памяти)."""


async def test_create_and_list_deal(api):
    r = await api.post(
        "/sales/deals",
        json={
            "number": "CRM-T-1",
            "title": "Тест",
            "counterparty": "ООО Тест",
            "amount": 1000,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] is not None
    assert body["number"] == "CRM-T-1"
    assert body["stage"] == "new"

    r2 = await api.get("/sales/deals")
    assert r2.status_code == 200
    numbers = [d["number"] for d in r2.json()]
    assert "CRM-T-1" in numbers


async def test_unique_number(api):
    payload = {"number": "CRM-DUP", "title": "A", "counterparty": "X"}
    r1 = await api.post("/sales/deals", json=payload)
    assert r1.status_code == 201
    # повторный тот же номер → нарушение уникальности → 409
    r2 = await api.post("/sales/deals", json=payload)
    assert r2.status_code == 409


async def test_board_groups_by_stage(api):
    await api.post("/sales/deals", json={"number": "B1", "title": "t", "counterparty": "c", "stage": "new", "amount": 100})
    await api.post(
        "/sales/deals",
        json={"number": "B2", "title": "t", "counterparty": "c", "stage": "won", "amount": 200, "closed_date": "01.01.2025"},
    )

    r = await api.get("/sales/board")
    assert r.status_code == 200
    data = r.json()
    assert len(data["stages"]) == 5
    stages = {s["id"]: s for s in data["stages"]}
    assert stages["new"]["count"] == 1
    assert stages["new"]["sum"] == 100
    assert stages["won"]["count"] == 1
    assert stages["won"]["sum"] == 200
    assert stages["new"]["title"] == "Новая заявка"


async def test_get_deal_by_id(api):
    created = (
        await api.post(
            "/sales/deals",
            json={"number": "G1", "title": "Деталь", "counterparty": "ООО Икс", "owner": "Иванов И.И."},
        )
    ).json()
    r = await api.get(f"/sales/deals/{created['id']}")
    assert r.status_code == 200
    assert r.json()["counterparty"] == "ООО Икс"

    assert (await api.get("/sales/deals/999999")).status_code == 404


async def test_update_deal_stage(api):
    created = (
        await api.post("/sales/deals", json={"number": "U1", "title": "t", "counterparty": "c", "stage": "new"})
    ).json()

    r = await api.patch(f"/sales/deals/{created['id']}", json={"stage": "won"})
    assert r.status_code == 200
    assert r.json()["stage"] == "won"

    board = (await api.get("/sales/board")).json()
    stages = {s["id"]: s for s in board["stages"]}
    assert stages["won"]["count"] == 1
    assert stages["new"]["count"] == 0

    assert (await api.patch("/sales/deals/999999", json={"stage": "won"})).status_code == 404


async def test_kpis(session, api):
    from datetime import date

    from modules.sales.models import Activity, KpiTarget

    session.add(KpiTarget(key="calls_all", title="Всего звонков", target=100, unit="count", icon="phone", tone="indigo", sort_order=1))
    for _ in range(3):
        session.add(Activity(kpi_key="calls_all", value=1, date=date(2026, 6, 2)))
    await session.commit()

    r = await api.get("/sales/kpis")
    assert r.status_code == 200
    item = next(x for x in r.json() if x["key"] == "calls_all")
    assert item["actual"] == 3
    assert item["target"] == 100
    assert item["percent"] == 3
