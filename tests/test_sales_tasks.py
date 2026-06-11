"""БД-тесты задач по сделке (SALES-41). SQLite в памяти."""


async def _new_deal(api, number, **extra):
    r = await api.post(
        "/sales/deals", json={"number": number, "title": "t", "counterparty": "c", **extra}
    )
    assert r.status_code == 201
    return r.json()


async def test_create_and_list_tasks(session, api):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent

    deal = await _new_deal(api, "TK-3")
    await api.post(f"/sales/deals/{deal['id']}/tasks", json={"title": "A", "kind": "call"})
    await api.post(f"/sales/deals/{deal['id']}/tasks", json={"title": "B", "kind": "email"})

    rows = (await api.get(f"/sales/deals/{deal['id']}/tasks")).json()
    assert len(rows) == 2
    assert {r["title"] for r in rows} == {"A", "B"}

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "sales.task.created" in types

    # несуществующая сделка → 404
    assert (await api.post("/sales/deals/999999/tasks", json={"title": "x"})).status_code == 404


async def test_task_overdue_flag(api):
    deal = await _new_deal(api, "TK-1")
    past = (
        await api.post(
            f"/sales/deals/{deal['id']}/tasks",
            json={"title": "call", "due_at": "2020-01-01T00:00:00"},
        )
    ).json()
    assert past["overdue"] is True

    future = (
        await api.post(
            f"/sales/deals/{deal['id']}/tasks",
            json={"title": "meet", "due_at": "2999-01-01T00:00:00"},
        )
    ).json()
    assert future["overdue"] is False

    nodue = (
        await api.post(f"/sales/deals/{deal['id']}/tasks", json={"title": "x"})
    ).json()
    assert nodue["overdue"] is False


async def test_complete_task(session, api):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent

    deal = await _new_deal(api, "TK-2")
    t = (
        await api.post(
            f"/sales/deals/{deal['id']}/tasks",
            json={"title": "call", "due_at": "2020-01-01T00:00:00"},
        )
    ).json()
    assert t["overdue"] is True

    r = await api.patch(f"/sales/tasks/{t['id']}", json={"status": "done", "result": "перезвонил"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["result"] == "перезвонил"
    assert body["overdue"] is False  # выполненная не просрочена, даже если срок прошёл

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "sales.task.completed" in types

    # перенос срока
    r2 = await api.patch(f"/sales/tasks/{t['id']}", json={"due_at": "2999-01-01T00:00:00"})
    assert r2.status_code == 200

    assert (await api.patch("/sales/tasks/999999", json={"status": "done"})).status_code == 404


async def test_deals_without_open_task(api):
    d1 = await _new_deal(api, "NT-1")  # без задачи
    d2 = await _new_deal(api, "NT-2")  # с открытой задачей
    task = (
        await api.post(f"/sales/deals/{d2['id']}/tasks", json={"title": "call"})
    ).json()

    rows = (await api.get("/sales/deals?has_open_task=false")).json()
    ids = {d["id"] for d in rows}
    assert d1["id"] in ids
    assert d2["id"] not in ids  # есть открытая задача → не «брошен»

    # закрыли задачу → d2 снова без открытой задачи
    await api.patch(f"/sales/tasks/{task['id']}", json={"status": "done"})
    ids2 = {d["id"] for d in (await api.get("/sales/deals?has_open_task=false")).json()}
    assert d2["id"] in ids2
