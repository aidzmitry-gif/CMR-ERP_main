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


async def _contact_access_users(session):
    session.add_all([
        User(username="contact-owner", full_name="Contact Owner", employee_id=201,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
        User(username="contact-other", full_name="Contact Other", employee_id=202,
             department="Продажи", role="sales", status="active", deal_visibility="all"),
        User(username="contact-hr", full_name="Contact HR", department="HR",
             role="hr", status="active", deal_visibility="all"),
    ])
    await session.commit()


async def test_primary_contact_own_scope_preserves_foreign_contacts(api, session):
    from core.domain.models import Contact

    await _contact_access_users(session)
    headers = _sales_headers("contact-owner")
    for suffix, owner_id, expected in (("OWN", 201, 200), ("OTHER", 202, 404),
                                       ("UNASSIGNED", None, 404)):
        deal = await _create(api, f"CP-{suffix}", counterparty=f"Client {suffix}", owner_id=owner_id)
        first = await api.post(f"/sales/deals/{deal['id']}/contacts",
                               json={"full_name": "First", "is_primary": True})
        second = await api.post(f"/sales/deals/{deal['id']}/contacts",
                                json={"full_name": "Second"})
        assert first.status_code == second.status_code == 201
        response = await api.patch(f"/sales/contacts/{second.json()['id']}/primary", headers=headers)
        assert response.status_code == expected, response.text
        for created, was_primary in ((first, True), (second, False)):
            contact = await session.get(Contact, created.json()["id"])
            await session.refresh(contact)
            assert contact.is_primary == (not was_primary if expected == 200 else was_primary)

    orphan = Contact(full_name="Unlinked")
    session.add(orphan)
    await session.commit()
    for contact_id in (orphan.id, 999999):
        assert (await api.patch(f"/sales/contacts/{contact_id}/primary", headers=headers)).status_code == 404
    await session.refresh(orphan)
    assert orphan.is_primary is False


async def test_primary_contact_requires_write_permission(api, session):
    from core.domain.models import Contact

    await _contact_access_users(session)
    deal = await _create(api, "CP-NO-WRITE", owner_id=201)
    contact = (await api.post(f"/sales/deals/{deal['id']}/contacts",
                              json={"full_name": "Protected"})).json()
    response = await api.patch(f"/sales/contacts/{contact['id']}/primary",
                               headers={"X-User": "contact-hr", "X-User-Roles": "hr"})
    assert response.status_code == 403, response.text
    assert "sales.deal.write" in response.json()["detail"]
    persisted = await session.get(Contact, contact["id"])
    await session.refresh(persisted)
    assert persisted.is_primary is False


async def test_own_funnels_have_only_visible_counts_and_open_boards(api, session):
    await _contact_access_users(session)
    # Match the materialized stage catalog used by migrations and other board tests.
    assert (await api.get("/sales/stages")).status_code == 200
    own = await _create(api, "FUNNEL-OWN", owner_id=201)
    repeat = await _create(api, "FUNNEL-REPEAT", owner_id=201,
                           funnel="repeat_clients", stage="rp_request")
    await _create(api, "FUNNEL-OTHER", owner_id=202)
    await _create(api, "FUNNEL-UNASSIGNED")
    await _create(api, "FUNNEL-CLOSED", owner_id=201, stage="won")
    headers = _sales_headers("contact-owner")
    response = await api.get("/sales/funnels", headers=headers)
    assert response.status_code == 200, response.text
    counts = {row["code"]: row["active_deals"] for row in response.json()}
    assert counts == {"new_clients": 1, "repeat_clients": 1, "tenders": 0}
    # The combined page requests each returned board under the same identity.
    found = set()
    for code in counts:
        board = await api.get("/sales/board", params={"funnel": code}, headers=headers)
        assert board.status_code == 200
        found.update(deal["id"] for stage in board.json()["stages"] for deal in stage["deals"])
    assert own["id"] in found and repeat["id"] in found
    assert len(found) == 3  # Includes the own closed deal, never other/unassigned deals.

    all_scope = await api.get("/sales/funnels", headers=_sales_headers("contact-other"))
    assert all_scope.status_code == 200
    assert {row["code"]: row["active_deals"] for row in all_scope.json()} == {
        "new_clients": 3, "repeat_clients": 1, "tenders": 0,
    }
    denied = await api.get("/sales/funnels",
                           headers={"X-User": "contact-hr", "X-User-Roles": "hr"})
    assert denied.status_code == 403
    assert "sales.deal.read" in denied.json()["detail"]
