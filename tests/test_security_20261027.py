"""Regression tests for SEC-08/09/10: denial happens before DB/LLM work."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from core.domain.models import User
from core.runtime.app import create_app
from core.runtime.contract import Role
from core.runtime.deps import get_session

REF_READS = [
    f"/system/refs/{name}"
    for name in (
        "units",
        "currencies",
        "countries",
        "banks",
        "nomenclature-groups",
        "accounts",
        "regions",
    )
] + [
    f"/system/refs/{name}{suffix}"
    for name in (
        "currency-rates",
        "vat-rates",
        "tnved",
        "sku-history",
    )
    for suffix in ("", "/current?key=QA", "/as-of?key=QA&on=2026-10-27")
]
WRITES = [
    ("sales", "POST", "/knowledge/courses", {}),
    ("sales", "PATCH", "/knowledge/courses/1", {"stage": "trial"}),
    ("sales", "POST", "/knowledge/enrollments", {"course_id": 1, "employee_name": "QA"}),
    ("sales", "PATCH", "/knowledge/enrollments/1", {"progress": 100}),
    ("hr", "POST", "/legal/cases", {}),
    ("hr", "PATCH", "/legal/cases/1", {"stage": "inbox"}),
    ("hr", "POST", "/office/docs", {}),
    ("hr", "PATCH", "/office/docs/1", {"stage": "inbox"}),
    ("hr", "POST", "/office/docs/1/carrier-request", {}),
    ("finance", "POST", "/office/contracts", {}),
    ("finance", "PATCH", "/office/contracts/1", {}),
    ("finance", "POST", "/office/claims", {}),
    ("finance", "PATCH", "/office/claims/1", {}),
]


@pytest_asyncio.fixture
async def denied_client():
    app = create_app()

    async def forbidden_session():
        raise AssertionError("denied request reached the database dependency")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = forbidden_session
    app.state.core.services.llm.enabled = True
    app.state.core.services.llm.complete = AsyncMock(side_effect=AssertionError("LLM called"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.state.core.services.llm.complete.assert_not_called()


@pytest.mark.parametrize("role", ["sales", "warehouse", "driver", "onboarding", None])
@pytest.mark.parametrize("path", REF_READS)
async def test_reference_reads_require_permission(denied_client, role, path):
    result = await denied_client.get(path, headers={"X-User-Roles": role} if role else {})
    assert result.status_code == 403


@pytest.mark.parametrize("role", ["sales", "warehouse", "driver", "onboarding", "hr", "finance"])
async def test_owner_insight_does_not_call_llm_for_employee(denied_client, role):
    result = await denied_client.get("/system/owner/insight", headers={"X-User-Roles": role})
    assert result.status_code == 403


@pytest.mark.parametrize("role,method,path,payload", WRITES)
async def test_module_access_does_not_allow_unrelated_write(
    denied_client,
    role,
    method,
    path,
    payload,
):
    result = await denied_client.request(method, path, json=payload, headers={"X-User-Roles": role})
    assert result.status_code == 403


@pytest.mark.parametrize("role", ["director", "commercial", "admin", "assistant", "sales_head", "procurement", "hr"])
async def test_leadership_can_read_reference(api, session, role):
    headers = {"X-User-Roles": role}
    if role == "sales_head":
        username = "synthetic-reference-sales-head"
        session.add(User(username=username, full_name="Synthetic reference reader", role=role, status="active"))
        await session.commit()
        headers["X-User"] = username
    result = await api.get("/system/refs/units", headers=headers)
    assert result.status_code == 200
    assert result.json() == []
    if role == "sales_head":
        spoofed = await api.get("/system/refs/units", headers={"X-User": username, "X-User-Roles": "sales"})
        assert spoofed.status_code == 403


async def test_explicit_reference_permission_still_works(session):
    app = create_app()
    app.state.core.declare_role(Role("qa_reference_reader", permissions=("refs.view",)))

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get(
            "/system/refs/banks", headers={"X-User-Roles": "qa_reference_reader"}
        )
    assert result.status_code == 200
    assert result.json() == []


@pytest.mark.parametrize("role", ["director", "commercial", "admin"])
async def test_leadership_can_request_owner_insight(ai_api, role):
    result = await ai_api.get("/system/owner/insight", headers={"X-User-Roles": role})
    assert result.status_code == 200


@pytest.mark.parametrize("role", ["hr", "director"])
async def test_training_owner_can_author_course(api, role):
    result = await api.post(
        "/knowledge/courses", json={"title": "QA course"}, headers={"X-User-Roles": role}
    )
    assert result.status_code == 201
    course = result.json()
    assert (
        await api.patch(
            f"/knowledge/courses/{course['id']}",
            json={"stage": "active"},
            headers={"X-User-Roles": role},
        )
    ).status_code == 200


@pytest.mark.parametrize("role", ["finance", "assistant"])
async def test_office_roles_keep_document_workflow(api, session, role):
    username = f"synthetic-office-{role}"
    session.add(User(username=username, full_name="Synthetic Office worker", role=role, status="active"))
    await session.commit()
    api.headers["X-User"] = username
    result = await api.post(
        "/office/docs", json={"title": "QA document"}, headers={"X-User-Roles": role}
    )
    assert result.status_code == 201


async def test_director_can_create_legal_objects(api):
    for path in ("/legal/cases", "/office/contracts", "/office/claims"):
        assert (await api.post(path, json={"counterparty_name": "QA"})).status_code == 201
