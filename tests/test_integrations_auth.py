"""Гейты доступа на роутах integrations (релиз-аудит 2026-07-16).

Префикс /integrations НЕ покрыт AccessControlMiddleware (пакет без UI-слага), поэтому защита —
пообъектно на роуте. Без require_permission GET /1c/stock отдавал себес/цены анонимно, а POST
/1c/sync позволял неавторизованный ресинк мастер-данных. Тесты пинят гейты.
"""


async def test_stock_requires_permission_denies_unprivileged(api):
    """GET /1c/stock несёт cost (себестоимость) — роль без sales.deal.read → 403, не утечка."""
    r = await api.get("/integrations/1c/stock", headers={"X-User-Roles": "warehouse"})
    assert r.status_code == 403


async def test_stock_allows_privileged(api):
    """С правом sales.deal.read (дефолт-директор фикстуры) — 200."""
    r = await api.get("/integrations/1c/stock")
    assert r.status_code == 200


async def test_sync_requires_permission_denies_unprivileged(api):
    """POST /1c/sync — мутация мастер-данных; без integrations.sync → 403."""
    r = await api.post("/integrations/1c/sync", headers={"X-User-Roles": "warehouse"})
    assert r.status_code == 403
