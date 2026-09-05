"""Regression contract for server-enforced per-employee deal visibility."""
from __future__ import annotations

import pytest

from core.domain.models import User


def _sales_headers(username: str) -> dict[str, str]:
    return {"X-User": username, "X-User-Roles": "sales"}


async def _create(api, number: str, **extra) -> dict:
    response = await api.post(
        "/sales/deals",
        json={"number": number, "title": number, "counterparty": "Тест", **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_all_scope_keeps_legacy_owner_and_confirms_employee_owner_id(api, session):
    session.add_all(
        [
            User(username="alice", full_name="Алиса CRM", employee_id=101, department="Продажи", role="sales", status="active"),
            User(username="bob", full_name="Боб CRM", employee_id=102, department="Продажи", role="sales", status="active"),
            User(username="finance", full_name="Финансы", employee_id=103, department="Финансы / офис", role="finance", status="active"),
        ]
    )
    await session.commit()

    legacy = await _create(api, "VIS-LEGACY", owner="Старый ответственный")
    assert legacy["owner"] == "Старый ответственный"
    assert legacy["owner_id"] is None

    confirmed = await _create(api, "VIS-CONFIRMED", owner="Подмена", owner_id=101)
    assert confirmed["owner_id"] == 101
    assert confirmed["owner"] == "Алиса CRM"

    unchanged = await api.patch(
        f"/sales/deals/{confirmed['id']}", json={"owner": "Алиса CRM"}
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["owner_id"] == 101

    unconfirmed = await api.patch(
        f"/sales/deals/{confirmed['id']}", json={"owner": "Свободный текст"}
    )
    assert unconfirmed.status_code == 200
    assert unconfirmed.json()["owner"] == "Свободный текст"
    assert unconfirmed.json()["owner_id"] is None

    invalid = await api.patch(f"/sales/deals/{confirmed['id']}", json={"owner_id": 999})
    assert invalid.status_code == 422
    non_crm = await api.patch(f"/sales/deals/{confirmed['id']}", json={"owner_id": 103})
    assert non_crm.status_code == 422


@pytest.mark.asyncio
async def test_own_scope_enforces_visibility_and_runtime_switch(api, session):
    alice = User(
        username="alice", full_name="Алиса CRM", employee_id=101,
        department="Продажи", role="sales", status="active", deal_visibility="own",
    )
    session.add_all(
        [
            alice,
            User(
                username="bob", full_name="Боб CRM", employee_id=102,
                department="Продажи", role="sales", status="active", deal_visibility="all",
            ),
        ]
    )
    await session.commit()
    own = await _create(api, "VIS-OWN", owner_id=101)
    other = await _create(api, "VIS-OTHER", owner_id=102)
    legacy = await _create(api, "VIS-NO-OWNER", owner="Старый ответственный")
    headers = _sales_headers("alice")

    listed = await api.get("/sales/deals", headers=headers)
    assert listed.status_code == 200
    assert [deal["id"] for deal in listed.json()] == [own["id"]]
    board = await api.get("/sales/board", headers=headers)
    assert board.status_code == 200
    assert {deal["id"] for column in board.json()["stages"] for deal in column["deals"]} == {own["id"]}

    assert (await api.get(f"/sales/deals/{other['id']}", headers=headers)).status_code == 404
    assert (await api.get(f"/sales/deals/{legacy['id']}", headers=headers)).status_code == 404
    assert (
        await api.post(f"/sales/deals/{other['id']}/tasks", json={"title": "leak"}, headers=headers)
    ).status_code == 404
    assert (await api.get("/sales/skus", headers=headers)).status_code == 200
    assert (await api.get("/sales/prices/MISSING", headers=headers)).status_code == 200
    assert (await api.get("/sales/journal", headers=headers)).status_code == 403

    self_assigned = await api.post(
        "/sales/deals",
        json={"number": "VIS-SELF", "title": "self", "counterparty": "Тест", "owner": "Подмена"},
        headers=headers,
    )
    assert self_assigned.status_code == 201
    assert self_assigned.json()["owner_id"] == 101
    assert self_assigned.json()["owner"] == "Алиса CRM"
    assert (
        await api.patch(f"/sales/deals/{own['id']}", json={"owner_id": 102}, headers=headers)
    ).status_code == 403

    alice.deal_visibility = "all"
    await session.commit()
    assert (await api.get(f"/sales/deals/{other['id']}", headers=headers)).status_code == 200
    alice.deal_visibility = "own"
    await session.commit()
    assert (await api.get(f"/sales/deals/{other['id']}", headers=headers)).status_code == 404
