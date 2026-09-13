"""Branch API identity, optimistic revisions and transactional rejection."""
import pytest
from sqlalchemy import func, select

from core.domain.models import AuditLog, Counterparty, CounterpartyBranch, CounterpartyBranchAlias
from core.services import mdm
from core.services.counterparty_branches import branch_for_external_ref
from core.services.mdm import CounterpartyWriteError


async def parent(session, **values):
    cp = Counterparty(**{"name": "Legacy", "display_name": "Short", "legal_name": "Legal company",
                         "unp": "600187521", **values})
    session.add(cp)
    await session.commit()
    return cp.id, cp.revision


def path(parent_id, branch_id=None):
    return f"/system/mdm/counterparty/{parent_id}/branches" + (f"/{branch_id}" if branch_id else "")


async def create(api, parent_id, revision, **fields):
    return await api.post(path(parent_id), json={"expected_legal_entity_revision": revision,
                                               "manual": {"name": "Branch", **fields}})


async def test_create_two_branches_and_read_names_parent_audit(api, session):
    cp_id, revision = await parent(session)
    first = await create(api, cp_id, revision, portal_branch_code="0001", tax_mode="shared")
    second = await create(api, cp_id, revision, portal_branch_code="0002")
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    response = await api.get(path(cp_id))
    assert response.status_code == 200
    data = response.json()
    assert data["legal_entity"]["name"] == "Short"
    assert data["legal_entity"]["legal_name"] == "Legal company"
    assert [b["portal_branch_code"] for b in data["branches"]] == ["0001", "0002"]
    assert data["branches"][1]["tax_mode"] == "unknown"
    assert data["branches"][0]["provenance"]["portal_branch_code"]["source"] == "manual"
    audits = (await session.scalars(select(AuditLog).where(AuditLog.action == "counterparty.branch.created"))).all()
    assert len(audits) == 2
    assert {a.detail["branch_id"] for a in audits} == {first.json()["id"], second.json()["id"]}


@pytest.mark.parametrize("fields", [
    {"portal_branch_code": "12a4"}, {"portal_branch_code": "１２３４"},
    {"portal_branch_code": "001"}, {"name": "  "}, {"name": None},
    {"tax_mode": "guess"}, {"tax_mode": None}, {"legal_entity_id": 999},
])
async def test_invalid_fields_rejected_without_writes(api, session, fields):
    cp_id, revision = await parent(session)
    response = await create(api, cp_id, revision, **fields)
    assert response.status_code == 422, response.text
    assert await session.scalar(select(func.count()).select_from(CounterpartyBranch)) == 0
    assert await session.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize("values,expected", [
    ({"is_active": False}, 409), ({"merged_into_id": 777}, 409),
    ({"legal_name": None}, 422), ({"unp": None}, 422),
    ({"legal_name": "   "}, 422), ({"unp": "not-a-legal-unp"}, 422),
    ({"unp": "１２３４５６７８９"}, 422), ({"unp": "12345678"}, 422),
])
async def test_ineligible_parent_rejected(api, session, values, expected):
    cp_id, revision = await parent(session, **values)
    response = await create(api, cp_id, revision)
    assert response.status_code == expected, response.text
    assert await session.scalar(select(func.count()).select_from(CounterpartyBranch)) == 0


async def test_wrong_parent_and_stale_patch_preserve_row(api, session):
    cp_id, revision = await parent(session)
    branch = (await create(api, cp_id, revision)).json()
    other_id, other_revision = await parent(session, unp="600187522")
    payload = {"expected_legal_entity_revision": other_revision, "expected_revision": branch["revision"],
               "manual": {"name": "Wrong"}}
    response = await api.patch(path(other_id, branch["id"]), json=payload)
    assert response.status_code == 404
    payload["expected_legal_entity_revision"] = revision
    payload["manual"] = {"address": "New address"}
    changed = await api.patch(path(cp_id, branch["id"]), json=payload)
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == branch["revision"] + 1
    payload["manual"] = {"name": "Stale"}
    stale = await api.patch(path(cp_id, branch["id"]), json=payload)
    assert stale.status_code == 409
    saved = (await api.get(path(cp_id))).json()["branches"][0]
    assert saved["name"] == "Branch" and saved["address"] == "New address"
    assert await session.scalar(select(func.count()).select_from(AuditLog)) == 2


async def test_parent_revision_and_permissions(api, session):
    cp_id, revision = await parent(session)
    assert (await create(api, cp_id, revision + 1)).status_code == 409
    payload = {"expected_legal_entity_revision": revision, "manual": {"name": "Branch"}}
    denied = await api.post(path(cp_id), json=payload, headers={"X-User-Roles": "sales"})
    assert denied.status_code == 403
    denied_read = await api.get(path(cp_id), headers={"X-User-Roles": ""})
    assert denied_read.status_code == 403
    assert await session.scalar(select(func.count()).select_from(CounterpartyBranch)) == 0


async def test_same_source_ref_resolves_only_owned_active_branch(api, session):
    cp_id, revision = await parent(session)
    branch = (await create(api, cp_id, revision)).json()
    session.add(CounterpartyBranchAlias(branch_id=branch["id"], source="1c:instanceA", external_ref="ref1"))
    await session.commit()
    found = await branch_for_external_ref(session, source="1c:instanceA", external_ref="ref1", legal_entity_id=cp_id)
    assert found.id == branch["id"]
    assert await branch_for_external_ref(session, source="1c:instanceB", external_ref="ref1", legal_entity_id=cp_id) is None
    with pytest.raises(CounterpartyWriteError, match="Внешний ID"):
        await branch_for_external_ref(session, source="1c:instanceA", external_ref="ref1", legal_entity_id=999)


async def test_merge_cannot_silently_move_branches(api, session):
    first_id, revision = await parent(session)
    created = (await create(api, first_id, revision)).json()
    second_id, _ = await parent(session, unp="600187522")
    with pytest.raises(ValueError, match="филиалы"):
        await mdm.merge(session, None, second_id, first_id)
    await session.rollback()
    saved = await session.get(CounterpartyBranch, created["id"])
    assert saved.legal_entity_id == first_id
    head = await session.get(Counterparty, first_id)
    assert head.is_active and head.merged_into_id is None


async def test_merge_rejects_archived_duplicate(session):
    survivor_id, _ = await parent(session)
    duplicate_id, _ = await parent(session, unp="600187522", is_active=False)
    with pytest.raises(ValueError, match="архивирован"):
        await mdm.merge(session, None, survivor_id, duplicate_id)
    await session.rollback()
    duplicate = await session.get(Counterparty, duplicate_id)
    assert not duplicate.is_active and duplicate.merged_into_id is None
