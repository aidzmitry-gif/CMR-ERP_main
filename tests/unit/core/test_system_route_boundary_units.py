from __future__ import annotations

from types import SimpleNamespace

import pytest

from config.access import ACCESS_MATRIX, ONBOARDING_ROLE
from core.runtime import system_routes


class EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


class EmptySession:
    async def execute(self, _statement):
        return EmptyResult()


@pytest.mark.asyncio
async def test_health_returns_stable_liveness_payload():
    assert await system_routes.health() == {"status": "ok"}


@pytest.mark.asyncio
async def test_system_access_onboarding_is_fail_closed_to_its_own_home_only():
    request = SimpleNamespace(headers={"X-User-Roles": "onboarding, sales"})

    result = await system_routes.system_access(request)

    assert result == {
        "matrix": {ONBOARDING_ROLE: ACCESS_MATRIX[ONBOARDING_ROLE]},
        "roles": [{"slug": ONBOARDING_ROLE, "title": "Ознакомление с системой"}],
        "current_roles": [ONBOARDING_ROLE],
    }


@pytest.mark.asyncio
async def test_references_quality_empty_read_model_keeps_all_reference_payloads():
    result = await system_routes.references_quality(EmptySession())

    assert len(result["references"]) == 9
    assert all(row["total"] == 0 for row in result["references"])
    assert all(row["issues_count"] == 0 for row in result["references"])
    assert all(row["score"] == 1.0 for row in result["references"])
    assert result["references"][0]["by_kind"] == {
        "missing": 0,
        "duplicate": 0,
        "broken_ref": 0,
        "orphan": 0,
    }
