"""Фиксы code-review: authz на reference.query/MDM-reads, resolve active-only, 422 вместо 500."""
from core.domain.models import Sku


async def test_reference_query_requires_refs_view(api):
    r = await api.post(
        "/system/references/query",
        json={"ref": "core.units"},
        headers={"X-User-Roles": "warehouse"},
    )
    assert r.status_code in (401, 403)  # коммерческие мастер-данные под refs.view


async def test_mdm_duplicates_requires_refs_view(api):
    r = await api.get("/system/mdm/duplicates", headers={"X-User-Roles": "warehouse"})
    assert r.status_code in (401, 403)


async def test_mdm_fuzzy_requires_refs_view(api):
    r = await api.get(
        "/system/mdm/fuzzy", params={"name": "тест"}, headers={"X-User-Roles": "warehouse"}
    )
    assert r.status_code in (401, 403)


async def test_resolve_skips_archived_sku(api, session):
    session.add(Sku(code="ARCH-1", title="архив", unit="шт", is_active=False))
    await session.commit()
    r = await api.post("/system/references/query", json={"ref": "core.skus", "key": "ARCH-1", "resolve": True})
    assert r.json()["result"] is None  # архивный SKU не резолвится для AI


async def test_query_bad_category_id_is_422(api):
    r = await api.post("/system/references/query", json={"ref": "core.skus", "category_id": "abc"})
    assert r.status_code == 422


async def test_query_limit_clamped(api, session):
    session.add_all([Sku(code=f"S{i}", title=str(i), unit="шт") for i in range(5)])
    await session.commit()
    # огромный limit не валит и не тянет всё — clamp до _QUERY_LIMIT_MAX
    r = await api.post("/system/references/query", json={"ref": "core.skus", "limit": 100000})
    assert r.status_code == 200


async def test_add_version_bad_date_is_422(api):
    r = await api.post(
        "/system/refs/currency-rates/versions",
        json={"currency_code": "USD", "rate": 3.2, "start_date": "не-дата"},
    )
    assert r.status_code == 422
