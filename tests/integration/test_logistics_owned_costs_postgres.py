"""Exact PostgreSQL Numeric, current registered schema and isolated owned sources."""
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from core.domain.models import OutboxEvent, User
from modules.accounting.models import SourceBinding
from modules.logistics.models import ImportShipment
from modules.wms.models import StockMovement
from tests.accounting import test_postgres as pg_sources
from tests.integration import test_invoice_issuance_postgres as issuing
from tests.test_logistics_owned_costs import add_import, review

pg_factory = pg_sources.pg_factory
issuance_pg = issuing.issuance_pg
pytestmark = pytest.mark.integration


async def test_native_decimal_ownership_unknowns_and_readonly_projection(issuance_pg):
    api, factory = issuance_pg
    async with factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0199"
        assert await session.scalar(text("SELECT to_regclass('logistics.import_shipment')")) is not None
        if await session.scalar(select(User).where(User.username == "issuer")) is None:
            session.add(User(username="issuer", full_name="Synthetic native cost owner", role="director", status="active"))
            await session.commit()
    orgs = []
    for unp in ("999999969", "999999968", "999999967"):
        response = await api.post("/accounting/organizations", json={"name": "Synthetic native costs", "unp": unp})
        assert response.status_code == 201, response.text
        orgs.append(response.json()["id"])
    own, foreign, cents = orgs
    async with factory() as session:
        await add_import(api, session, own, "12000.00")
        await add_import(api, session, own, "5000.00")
        await add_import(api, session, own, "8000.00", stage="in_transit")
        await add_import(api, session, own, "777777.00", bind=False)
        await add_import(api, session, own, "333333.00", ownership="customer")
        await add_import(api, session, foreign, "999999.00")
        for amount in ("0.01", "0.02"):
            await add_import(api, session, cents, amount)
    response = await api.get(f"/logistics/organizations/{own}/cost-insights")
    assert response.status_code == 200, response.text
    assert response.json()["principal"] == "issuer"
    assert response.headers["Cache-Control"] == "private, no-store"
    result = response.json()["import_freight"]
    assert result["total"] == "17000.00" and result["known_count"] == 2
    assert result["known_average"] == "8500.00" and result["excluded_nonwarehouse_count"] == 1
    assert (await review(api, foreign))["total"] == "999999.00"
    exact = await review(api, cents)
    assert exact["total"] == "0.03" and exact["known_average"] == "0.02"
    async with factory() as session:
        await add_import(api, session, own, "NaN")
        await add_import(api, session, own, "0.00")
        raw_nan = await session.scalar(select(ImportShipment.amount).where(
            ImportShipment.id == (await session.scalar(select(func.max(ImportShipment.id)))) - 1))
        assert isinstance(raw_nan, Decimal) and raw_nan.is_nan()
        models = (ImportShipment, SourceBinding, StockMovement, OutboxEvent)
        before = [await session.scalar(select(func.count()).select_from(model)) for model in models]
    partial = await review(api, own)
    assert partial["total"] is None and partial["status"] == "partial"
    assert partial["known_total"] == "17000.00" and partial["unpriced_count"] == 2
    async with factory() as session:
        after = [await session.scalar(select(func.count()).select_from(model)) for model in models]
        assert after == before
