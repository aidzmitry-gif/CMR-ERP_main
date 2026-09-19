"""БД-тесты задач по сделке (SALES-41). SQLite в памяти."""

import pytest


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


@pytest.mark.parametrize("visibility", ["own", "all"])
async def test_employee_can_update_visible_task_without_duplicate_completion(api, session, visibility):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent, User
    from modules.sales.models import DealTask

    session.add(User(
        username="task-owner", full_name="Task Owner", employee_id=101,
        department="Продажи", role="sales", status="active", deal_visibility=visibility,
    ))
    await session.commit()
    deal = await _new_deal(api, "TK-OWN", owner_id=101)
    headers = {"X-User": "task-owner", "X-User-Roles": "sales"}
    created = await api.post(
        f"/sales/deals/{deal['id']}/tasks", json={"title": "Follow up"}, headers=headers,
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    moved = await api.patch(
        f"/sales/tasks/{task_id}", json={"due_at": "2999-01-01T00:00:00"}, headers=headers,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["due_at"] == "2999-01-01T00:00:00"
    assert moved.json()["status"] == "open"
    for _ in range(2):
        completed = await api.patch(
            f"/sales/tasks/{task_id}",
            json={"status": "done", "result": "Called back"}, headers=headers,
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "done"
        assert completed.json()["result"] == "Called back"

    task = await session.get(DealTask, task_id)
    await session.refresh(task)
    assert task.status == "done"
    assert task.done_at is not None
    events = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.task.completed",
    ))).scalars().all()
    assert [event.payload["task_id"] for event in events] == [task_id]


async def test_own_scope_cannot_update_foreign_or_unassigned_tasks(api, session):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent, User
    from modules.sales.models import DealTask

    session.add_all([
        User(username="alice", full_name="Alice", employee_id=101, department="Продажи",
             role="sales", status="active", deal_visibility="own"),
        User(username="bob", full_name="Bob", employee_id=102, department="Продажи",
             role="sales", status="active"),
    ])
    await session.commit()
    headers = {"X-User": "alice", "X-User-Roles": "sales"}
    for number, owner_id in (("TK-FOREIGN", 102), ("TK-UNASSIGNED", None)):
        deal = await _new_deal(api, number, owner_id=owner_id)
        created = await api.post(f"/sales/deals/{deal['id']}/tasks", json={"title": "Private"})
        assert created.status_code == 201
        task_id = created.json()["id"]
        response = await api.patch(
            f"/sales/tasks/{task_id}",
            json={"status": "done", "result": "Unauthorized"}, headers=headers,
        )
        assert response.status_code == 404, response.text
        task = await session.get(DealTask, task_id)
        await session.refresh(task)
        assert task.status == "open"
        assert task.result is None
        assert task.done_at is None

    missing = await api.patch("/sales/tasks/999999", json={"status": "done"}, headers=headers)
    assert missing.status_code == 404
    assert (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.task.completed",
    ))).scalars().all() == []


async def test_task_update_requires_write_permission(api, session):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent, User
    from modules.sales.models import DealTask

    # HR can enter the CRM module, but has no sales.deal.write capability.
    session.add(User(username="hr-reader", full_name="HR Reader", department="HR",
                     role="hr", status="active", deal_visibility="all"))
    await session.commit()
    deal = await _new_deal(api, "TK-NO-WRITE")
    created = await api.post(f"/sales/deals/{deal['id']}/tasks", json={"title": "Protected"})
    assert created.status_code == 201
    task_id = created.json()["id"]
    response = await api.patch(
        f"/sales/tasks/{task_id}", json={"status": "done", "result": "Unauthorized"},
        headers={"X-User": "hr-reader", "X-User-Roles": "hr"},
    )
    assert response.status_code == 403, response.text
    assert "sales.deal.write" in response.json()["detail"]
    task = await session.get(DealTask, task_id)
    await session.refresh(task)
    assert task.status == "open"
    assert task.result is None
    assert task.done_at is None
    assert (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.task.completed",
    ))).scalars().all() == []
