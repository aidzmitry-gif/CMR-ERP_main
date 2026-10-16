"""Two explicit names must not overwrite the legacy identity string."""
from sqlalchemy import select

from core.domain.models import AuditLog, Counterparty


async def test_edit_names_retains_legacy_and_records_each_field(api, session):
    cp = Counterparty(name="Legacy link", unp="600187521")
    session.add(cp)
    await session.commit()
    cp_id, revision = cp.id, cp.revision
    response = await api.patch(f"/system/mdm/counterparty/{cp_id}", json={
        "expected_revision": revision,
        "manual": {"display_name": "Short label", "legal_name": "Official company name"},
    })
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == revision + 1
    session.expire_all()
    row = await session.get(Counterparty, cp_id)
    assert (row.name, row.display_name, row.legal_name) == ("Legacy link", "Short label", "Official company name")
    data = (await api.get(f"/system/mdm/counterparty/{cp_id}")).json()
    assert data["display_name"] == "Short label" and data["legal_name"] == "Official company name"
    assert data["provenance"]["display_name"]["source"] == "manual"
    assert data["provenance"]["legal_name"]["source"] == "manual"
    audit = (await session.scalars(select(AuditLog).where(AuditLog.action == "counterparty.updated"))).one()
    assert audit.detail["before"]["name"] == audit.detail["after"]["name"] == "Legacy link"
    assert audit.detail["before"]["legal_name"] is None
    assert audit.detail["after"]["legal_name"] == "Official company name"


async def test_create_with_two_names_then_create_branch(api):
    created = await api.post("/system/mdm/counterparty", json={"manual": {
        "display_name": "Short", "legal_name": "Legal", "unp": "600187521",
    }})
    assert created.status_code == 201, created.text
    cp = created.json()
    branch = await api.post(f"/system/mdm/counterparty/{cp['id']}/branches", json={
        "expected_legal_entity_revision": cp["revision"], "manual": {"name": "Branch"},
    })
    assert branch.status_code == 201, branch.text
    assert branch.json()["legal_entity_id"] == cp["id"]


async def test_legacy_card_does_not_invent_legal_name(api):
    created = await api.post("/system/mdm/counterparty", json={"manual": {"name": "Unverified short"}})
    data = (await api.get(f"/system/mdm/counterparty/{created.json()['id']}")).json()
    assert data["display_name"] == "Unverified short"
    assert data["legal_name"] is None
