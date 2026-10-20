"""БД-тесты задач по сделке (SALES-41). SQLite в памяти."""

import pytest
import pytest_asyncio

from core.domain.models import Counterparty


@pytest_asyncio.fixture
async def api(api, session):
    """Positive deals select existing synthetic MDM parties by their exact names."""
    for name in (
        'c',
    ):
        session.add(Counterparty(name=name))
    await session.commit()
    yield api


async def _new_deal(api, number, **extra):
    r = await api.post(
        "/sales/deals", json={"number": number, "title": "t", "counterparty": "c", **extra}
    )
    assert r.status_code == 201
    return r.json()


async def test_create_and_list_tasks(session, api):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent
    from modules.sales.models import DealTaskCrmLink

    deal = await _new_deal(api, "TK-3")
    await api.post(f"/sales/deals/{deal['id']}/tasks", json={"title": "A", "kind": "call"})
    await api.post(f"/sales/deals/{deal['id']}/tasks", json={"title": "B", "kind": "email"})

    rows = (await api.get(f"/sales/deals/{deal['id']}/tasks")).json()
    assert len(rows) == 2
    assert {r["title"] for r in rows} == {"A", "B"}
    links = (await session.execute(select(DealTaskCrmLink))).scalars().all()
    assert {(link.task_id, link.ordinal, link.deal_id) for link in links} == {
        (row["id"], 0, deal["id"]) for row in rows
    }

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


async def test_task_due_at_with_timezone_is_stored_as_utc_before_commit(api, session):
    from sqlalchemy import func, select

    from modules.sales.models import DealTask

    deal = await _new_deal(api, "TK-TZ")
    response = await api.post(
        f"/sales/deals/{deal['id']}/tasks",
        json={"title": "Timezone task", "due_at": "2030-01-01T12:00:00+03:00"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["due_at"] == "2030-01-01T09:00:00"
    assert await session.scalar(select(func.count()).select_from(DealTask)) == 1
    moved = await api.patch(
        f"/sales/tasks/{response.json()['id']}",
        json={"due_at": "2030-01-02T12:00:00+03:00"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["due_at"] == "2030-01-02T09:00:00"


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


async def test_imported_multilink_tasks_are_visible_without_foreign_link_leak(api, session):
    from core.domain.models import User
    from modules.sales.models import DealTask, DealTaskCrmLink

    session.add_all([
        User(username="task-a", full_name="A", employee_id=601,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
        User(username="task-b", full_name="B", employee_id=602,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
    ])
    await session.commit()
    own = await _new_deal(api, "TASK-LINK-OWN", owner_id=601)
    other = await _new_deal(api, "TASK-LINK-OTHER", owner_id=602)
    task = DealTask(
        deal_id=other["id"], title="Shared synthetic task", source_ref="bitrix:task:801",
        description="Synthetic description", source_responsible_id="901",
        source_status_code="3", status="in_progress",
    )
    unbound = DealTask(
        deal_id=None, title="Unbound synthetic task", source_ref="bitrix:task:802",
        assignee_id=601,
    )
    foreign_only = DealTask(deal_id=other["id"], title="Foreign synthetic task")
    foreign_assigned = DealTask(
        deal_id=other["id"], title="Foreign assigned synthetic task", assignee_id=601
    )
    linked_foreign_assigned = DealTask(
        deal_id=None, title="Linked foreign assigned task", assignee_id=601
    )
    session.add_all([task, unbound, foreign_only, foreign_assigned, linked_foreign_assigned])
    await session.flush()
    session.add_all([
        DealTaskCrmLink(task_id=task.id, ordinal=0, raw_binding="D_901",
                            entity_type="DEAL", source_id="901", deal_id=other["id"]),
        DealTaskCrmLink(task_id=task.id, ordinal=1, raw_binding="D_902",
                            entity_type="DEAL", source_id="902", deal_id=own["id"]),
        DealTaskCrmLink(task_id=task.id, ordinal=2, raw_binding="PRIVATE_UNRESOLVED",
                            entity_type=None, source_id=None, deal_id=None),
        DealTaskCrmLink(task_id=foreign_only.id, ordinal=0, deal_id=other["id"]),
        DealTaskCrmLink(task_id=linked_foreign_assigned.id, ordinal=0,
                            deal_id=other["id"]),
    ])
    await session.commit()

    headers = {"X-User": "task-a", "X-User-Roles": "sales"}
    own_deal_response = await api.get(f"/sales/deals/{own['id']}/tasks", headers=headers)
    assert own_deal_response.status_code == 200, own_deal_response.text
    assert [row["id"] for row in own_deal_response.json()] == [task.id]
    own_row = own_deal_response.json()[0]
    assert own_row["deal_id"] is None
    assert own_row["description"] == "Synthetic description"
    assert own_row["source_status_code"] == "3"
    assert own_row["imported"] is True
    assert own_row["hidden_link_count"] == 2
    assert [(link["ordinal"], link["deal_id"]) for link in own_row["crm_links"]] == [
        (1, own["id"])
    ]
    assert "PRIVATE_UNRESOLVED" not in own_deal_response.text
    assert (await api.get(f"/sales/deals/{other['id']}/tasks", headers=headers)).status_code == 404

    global_response = await api.get("/sales/tasks", headers=headers)
    assert global_response.status_code == 200, global_response.text
    assert {row["id"] for row in global_response.json()} == {task.id, unbound.id}
    manager_response = await api.get("/sales/tasks")
    assert manager_response.status_code == 200
    manager_task = next(row for row in manager_response.json() if row["id"] == task.id)
    assert len(manager_task["crm_links"]) == 3
    assert manager_task["hidden_link_count"] == 0

    secondary_patch = await api.patch(
        f"/sales/tasks/{task.id}", json={"status": "done"}, headers=headers
    )
    assert secondary_patch.status_code == 409
    unbound_patch = await api.patch(
        f"/sales/tasks/{unbound.id}", json={"status": "done"}, headers=headers
    )
    assert unbound_patch.status_code == 409

    own_imported = DealTask(
        deal_id=own["id"], title="Read-only synthetic task", source_ref="bitrix:task:803"
    )
    session.add(own_imported)
    await session.commit()
    rejected = await api.patch(
        f"/sales/tasks/{own_imported.id}", json={"status": "done"}, headers=headers
    )
    assert rejected.status_code == 409
    await session.refresh(own_imported)
    assert own_imported.status == "open"
