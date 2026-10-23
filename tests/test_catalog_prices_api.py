"""Selling-price references preserve existing role boundaries and unknown stock."""
import pytest
from sqlalchemy import func, select, update

from core.domain.models import User
from core.services.auth import CurrentUser
from modules.integrations.catalog_prices import import_prices
from modules.integrations.models import CatalogPriceObservation, StockItem
from modules.sales.models import Deal, DealItem, PriceQuote
from tests.test_catalog_prices import packet, seed
from tests.test_identity_effective_access import _effective_access_client


@pytest.mark.parametrize("role", ["sales", "sales_manager", "sales_cli", "sales_head"])
async def test_existing_crm_roles_read_reference_price_without_stock_cost_or_history(session, monkeypatch, role):
    sku = await session.run_sync(seed)
    await session.run_sync(import_prices, packet())
    session.add(User(username="synthetic-price-seller", full_name="Synthetic seller",
                     keycloak_user_id="synthetic-price-subject", role=role, status="active",
                     employee_id=901, deal_visibility="own", expected_department="Продажи",
                     expected_role=role))
    foreign = Deal(number="synthetic-price-foreign", title="Synthetic foreign deal",
                   counterparty="Synthetic foreign buyer", owner_id=902)
    session.add(foreign)
    await session.commit()
    principal = CurrentUser("synthetic-price-seller", [role, "director"], "synthetic-price-subject")
    async with await _effective_access_client(session, monkeypatch, principal) as api:
        response = await api.get("/sales/picker-prices")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "reference" and payload["snapshot"]["mapped"] == 1
        assert payload["snapshot"]["full_coverage"] is payload["snapshot"]["activity_verified"] is False
        assert payload["rows"] == [{"sku_id": sku.id, "sku_code": sku.code, "unit": "unit",
            "price": "12.50", "currency": "933", "kind": "Synthetic wholesale", "price_includes_vat": False,
            "effective_at": "2026-07-01T10:00:00", "characteristic_guid": "00000000-0000-0000-0000-000000000000",
            "package_guid": "00000000-0000-0000-0000-000000000000", "application_status": "reference_only"}]
        assert (await api.get("/sales/picker-stock")).json() == []
        assert (await api.get(f"/sales/deals/{foreign.id}")).status_code == 404
        assert (await api.get("/system/mdm/counterparty/1")).status_code == 403
    for model in (StockItem, DealItem, PriceQuote):
        assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_unconfigured_price_feed_is_unavailable_not_zero(api):
    response = await api.get("/sales/picker-prices")
    assert response.status_code == 200
    assert response.json() == {"status": "unavailable", "snapshot": None, "rows": []}


async def test_unavailable_gateway_is_unknown_without_creating_prices(api):
    api._transport.app.state.core.services.stock = None
    response = await api.get("/sales/picker-prices")
    assert response.status_code == 200
    assert response.json() == {"status": "unavailable", "snapshot": None, "rows": []}


async def test_corrupt_price_snapshot_returns_safe_unavailable_error(api, session):
    await session.run_sync(seed)
    await session.run_sync(import_prices, packet())
    await session.commit()
    await session.execute(update(CatalogPriceObservation).values(price_text="999.00"))
    await session.commit()
    response = await api.get("/sales/picker-prices")
    assert response.status_code == 503
    assert response.json() == {"detail": "Прайс временно недоступен"}
