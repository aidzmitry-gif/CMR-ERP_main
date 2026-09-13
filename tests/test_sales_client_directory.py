"""The directory must not widen the existing per-deal contact visibility."""
import pytest

from core.domain.models import Contact, Counterparty, User
from modules.sales.models import Deal


async def seed(session):
    users = [User(username="directory-own", full_name="Owner", employee_id=401,
                  department="Sales", role="sales", status="active", deal_visibility="own"),
             User(username="directory-all", full_name="All", employee_id=402,
                  department="Sales", role="sales", status="active", deal_visibility="all")]
    clients = [Counterparty(name=name, unp=str(100000000 + i)) for i, name in enumerate(
        ["Own", "Foreign", "Unassigned", "Shared", "Ambiguous", "Ambiguous", "No deal"])]
    # Archived duplicates still make name resolution ambiguous.
    clients[5].is_active = False
    session.add_all(users + clients)
    await session.flush()
    for cp in clients:
        session.add(Contact(counterparty_id=cp.id, full_name=f"Person {cp.id}",
                            phone=f"+3752900000{cp.id:02}", email=f"p{cp.id}@example.invalid"))
    session.add(Contact(full_name="Orphan"))
    deals = []
    for i, (name, owner) in enumerate([
        ("Own", 401), ("Foreign", 402), ("Unassigned", None), ("Shared", 402),
        ("Shared", 401), ("Ambiguous", 401), ("Own", 401),
    ]):
        deal = Deal(number=f"DIR-{i}", title=f"Directory {i}", counterparty=name, owner_id=owner)
        session.add(deal)
        deals.append(deal)
    await session.commit()
    return users, clients, deals


OWN = {"X-User": "directory-own", "X-User-Roles": "sales"}
ALL = {"X-User": "directory-all", "X-User-Roles": "sales"}


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["clients", "contacts"])
async def test_scoped_rows_totals_pages_and_links(api, session, endpoint):
    _, clients, deals = await seed(session)
    response = await api.get(f"/sales/{endpoint}", headers=OWN)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2
    id_key = "id" if endpoint == "clients" else "counterparty_id"
    assert {r[id_key] for r in data["rows"]} == {clients[0].id, clients[3].id}
    assert {r["deal_id"] for r in data["rows"]} == {deals[0].id, deals[4].id}
    for row in data["rows"]:
        linked = await api.get(f"/sales/deals/{row['deal_id']}", headers=OWN)
        assert linked.status_code == 200
        assert linked.json()["owner_id"] == 401
        assert not {"audit", "aliases", "touches", "amount", "merged_duplicates"}.intersection(row)
    first = (await api.get(f"/sales/{endpoint}?limit=1", headers=OWN)).json()
    second = (await api.get(f"/sales/{endpoint}?limit=1&offset=1", headers=OWN)).json()
    beyond = (await api.get(f"/sales/{endpoint}?limit=1&offset=2", headers=OWN)).json()
    assert first["total"] == second["total"] == beyond["total"] == 2
    assert first["rows"][0]["id"] != second["rows"][0]["id"]
    assert beyond["rows"] == []
    forged = (await api.get(f"/sales/{endpoint}?owner_id=402&visibility=all", headers=OWN)).json()
    assert forged == data


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["clients", "contacts"])
async def test_foreign_search_and_ambiguous_names_do_not_leak(api, session, endpoint):
    _, clients, _ = await seed(session)
    terms = ["Foreign", "Unassigned", "Ambiguous", "No deal", "Orphan", "%", "_"]
    terms += [clients[1].unp] if endpoint == "clients" else [
        f"p{clients[1].id}@example.invalid", f"+3752900000{clients[1].id:02}",
    ]
    for term in terms:
        response = await api.get(f"/sales/{endpoint}", params={"q": term}, headers=OWN)
        assert response.status_code == 200
        assert response.json() == {"rows": [], "total": 0}, term


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["clients", "contacts"])
async def test_all_scope_and_scope_change(api, session, endpoint):
    users, _, _ = await seed(session)
    result = await api.get(f"/sales/{endpoint}", headers=ALL)
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 7
    name_key = "name" if endpoint == "clients" else "counterparty_name"
    for row in result.json()["rows"]:
        if row[name_key] in {"Ambiguous", "No deal"}:
            assert row["deal_id"] is None
    users[0].deal_visibility = "all"
    await session.commit()
    assert (await api.get(f"/sales/{endpoint}", headers=OWN)).json()["total"] == 7
    users[0].deal_visibility = "own"
    await session.commit()
    assert (await api.get(f"/sales/{endpoint}", headers=OWN)).json()["total"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["clients", "contacts"])
async def test_identity_denials_and_query_validation(api, session, endpoint):
    users, _, _ = await seed(session)
    for roles in ["hr", "", "onboarding"]:
        response = await api.get(f"/sales/{endpoint}", headers={"X-User-Roles": roles})
        assert response.status_code == 403
    users[0].employee_id = None
    await session.commit()
    assert (await api.get(f"/sales/{endpoint}", headers=OWN)).status_code == 403
    users[0].employee_id = 401
    users[0].status = "disabled"
    await session.commit()
    assert (await api.get(f"/sales/{endpoint}", headers=OWN)).status_code == 403
    for params in [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": "x" * 121}]:
        assert (await api.get(f"/sales/{endpoint}", params=params, headers=ALL)).status_code == 422


@pytest.mark.asyncio
async def test_manager_keeps_no_system_write_and_directory_is_read_only(api, session):
    _, clients, _ = await seed(session)
    for headers in [OWN, ALL]:
        response = await api.patch(f"/system/mdm/counterparty/{clients[0].id}",
                                   json={"manual": {"name": "Changed"}, "expected_revision": 1},
                                   headers=headers)
        assert response.status_code == 403
        for path in ["/sales/clients", "/sales/contacts"]:
            assert (await api.post(path, json={}, headers=headers)).status_code in {403, 405}
    await session.refresh(clients[0])
    assert clients[0].name == "Own"
