"""M4: карточка номенклатуры (мастер-данные Sku + горячие поля + landed cost через фасад)."""
from core.domain.models import Sku


async def test_sku_card_returns_master_fields(api, session):
    session.add(Sku(
        code="AKB-304", title="Аккумулятор LiFePO4 304Ah", unit="шт",
        weight_kg=5.6, tnved_code="8507600000", shelf_life_days=1095,
        attributes={"voltage": "3.2V"}, provenance={"title": {"source": "1c"}},
    ))
    await session.commit()

    card = (await api.get("/system/sku/AKB-304")).json()
    assert card["code"] == "AKB-304"
    assert card["weight_kg"] == 5.6
    assert card["tnved_code"] == "8507600000"
    assert card["shelf_life_days"] == 1095
    assert card["is_active"] is True
    assert card["attributes"]["voltage"] == "3.2V"
    assert card["provenance"]["title"]["source"] == "1c"
    # без подключённого procurement-шлюза себестоимость None (не 0)
    assert card["landed_cost"] is None


async def test_sku_card_404(api):
    assert (await api.get("/system/sku/НЕТ")).status_code == 404


async def test_sku_card_requires_permission(api, session):
    """Себестоимость — коммерческая тайна: гость без права sales.deal.read получает 403."""
    session.add(Sku(code="SECRET-1", title="Секретный товар", unit="шт"))
    await session.commit()
    # роль без права sales.deal.read и не супер (латиница — заголовки HTTP ASCII)
    r = await api.get("/system/sku/SECRET-1", headers={"X-User-Roles": "warehouse"})
    assert r.status_code == 403


class _LCGateway:
    async def last_landed_cost(self, session, sku_code):
        return {"unit_landed_cost_byn": "214.80", "stage": "estimated", "shipment_id": 7}

    async def last_landed_cost_batch(self, session, sku_codes):
        return {c: await self.last_landed_cost(session, c) for c in sku_codes}


async def test_sku_card_reads_landed_cost_via_gateway(api, session):
    """Если фасад landed_cost подключён — карточка отдаёт себестоимость из него."""
    session.add(Sku(code="AKB-60", title="АКБ 60", unit="шт"))
    await session.commit()

    # подменяем фасад в core тест-приложения (ASGITransport хранит app)
    core = api._transport.app.state.core
    core.services.landed_cost = _LCGateway()
    try:
        card = (await api.get("/system/sku/AKB-60")).json()
        assert card["landed_cost"]["unit_landed_cost_byn"] == "214.80"
        assert card["landed_cost"]["stage"] == "estimated"
    finally:
        core.services.landed_cost = None  # вернуть, чтобы не течь в другие тесты
