"""Persistent platform identity, ordinary authorization, and exact retry contracts."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.domain.installation import PlatformInstallation
from core.domain.models import AuditLog, User
from core.services.auth import CurrentUser
from core.services.installation_settings import current_instance
from modules.accounting.models import AccessGrant

ADMIN = {"X-User": "synthetic-platform-admin", "X-User-Roles": "director"}
PATH = "/system/installation-organization"


async def organization(api, unp="987654321", headers=ADMIN):
    response = await api.post("/accounting/organizations", headers=headers,
                              json={"name": f"Synthetic company {unp}", "unp": unp})
    assert response.status_code == 201, response.text
    return response.json()


def command(organization_id, revision=0, request_id=None):
    return {"organization_id": organization_id, "expected_revision": revision,
            "request_id": request_id or str(uuid4())}


async def test_selection_is_persistent_and_shared_by_another_session(api, session):
    first = await organization(api)
    second = await organization(api, "123456789")
    before = await api.get(PATH, headers=ADMIN)
    assert before.status_code == 200
    assert before.json()["revision"] == 0
    assert before.json()["can_manage"] is True
    assert {row["id"] for row in before.json()["organizations"]} == {first["id"], second["id"]}
    saved = await api.put(PATH, headers=ADMIN, json=command(second["id"]))
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    current = await api.get("/system/instance-organization", headers=ADMIN)
    assert current.json()["organization"]["id"] == second["id"]
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    rows = [first, second]
    gateway = SimpleNamespace(source_organizations=AsyncMock(return_value=rows))
    async with factory() as other_worker:
        result = await current_instance(other_worker, CurrentUser(ADMIN["X-User"], ["director"]), gateway, first["unp"])
    assert result["organization"]["id"] == second["id"]
    assert result["configuration"] == "platform_settings"


async def test_exact_retry_has_one_revision_and_one_audit(api, session):
    own = await organization(api)
    body = command(own["id"])
    first = await api.put(PATH, headers=ADMIN, json=body)
    retry = await api.put(PATH, headers=ADMIN, json=body)
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert await session.scalar(select(func.count()).select_from(PlatformInstallation)) == 1
    assert await session.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "system.installation_organization.changed")) == 1


async def test_stale_admin_cannot_overwrite_a_saved_choice(api):
    first = await organization(api)
    second = await organization(api, "123456789")
    assert (await api.put(PATH, headers=ADMIN, json=command(first["id"]))).status_code == 200
    refused = await api.put(PATH, headers=ADMIN, json=command(second["id"]))
    assert refused.status_code == 409
    assert (await api.get(PATH, headers=ADMIN)).json()["organization"]["id"] == first["id"]


async def test_same_request_id_cannot_change_its_payload(api):
    first = await organization(api)
    second = await organization(api, "123456789")
    body = command(first["id"])
    assert (await api.put(PATH, headers=ADMIN, json=body)).status_code == 200
    assert (await api.put(PATH, headers=ADMIN, json={**body, "organization_id": second["id"]})).status_code == 409


async def test_ordinary_employee_can_read_but_cannot_select_the_platform_company(api, session):
    own = await organization(api)
    await api.put(PATH, headers=ADMIN, json=command(own["id"]))
    session.add(User(username="synthetic-platform-reader", full_name="Synthetic employee", role="sales", status="active", department="Продажи"))
    session.add(AccessGrant(organization_id=own["id"], subject="synthetic-platform-reader", role="reader"))
    await session.commit()
    employee = {"X-User": "synthetic-platform-reader", "X-User-Roles": "sales"}
    read = await api.get(PATH, headers=employee)
    assert read.status_code == 200
    assert read.json()["can_manage"] is False
    assert read.json()["organizations"] == []
    assert (await api.put(PATH, headers=employee, json=command(own["id"], 1))).status_code == 403


async def test_selecting_a_foreign_book_does_not_grant_access(api, session):
    foreign = await organization(api, headers={**ADMIN, "X-User": "another-admin"})
    denied = await api.put(PATH, headers=ADMIN, json=command(foreign["id"]))
    assert denied.status_code == 403
    assert await session.get(PlatformInstallation, 1) is None
    assert (await api.get(PATH, headers=ADMIN)).json()["organizations"] == []


@pytest.mark.parametrize("patch", [
    {"organization_id": True}, {"organization_id": 0}, {"expected_revision": -1},
    {"expected_revision": True}, {"request_id": "not-a-uuid"}, {"surprise": "forbidden"},
])
async def test_invalid_commands_never_write_settings(api, session, patch):
    own = await organization(api)
    response = await api.put(PATH, headers=ADMIN, json={**command(own["id"]), **patch})
    assert response.status_code == 422
    assert await session.get(PlatformInstallation, 1) is None


async def test_guest_cannot_read_settings(api):
    assert (await api.get(PATH, headers={"X-User-Roles": "guest"})).status_code == 403


async def test_saved_identity_never_falls_back_to_another_book(session):
    session.add(PlatformInstallation(id=1, revision=1, organization_id=7, organization_unp="987654321",
                                     request_id=str(uuid4()), command_digest="a" * 64, actor="synthetic"))
    await session.commit()
    gateway = SimpleNamespace(source_organizations=AsyncMock(return_value=[
        {"id": 8, "name": "Other book", "unp": "987654321"},
    ]))
    with pytest.raises(HTTPException) as error:
        await current_instance(session, CurrentUser("synthetic", ["seller"]), gateway, "123456789")
    assert error.value.status_code == 409
