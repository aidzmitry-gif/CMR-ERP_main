"""Qualified source amounts are separate from complete company or posted costs."""
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from core.domain.models import OutboxEvent, User
from modules.accounting.models import AccessGrant, SourceBinding
from modules.logistics.models import ImportShipment
from modules.logistics.owned_costs import FreightAccumulator
from modules.wms.models import StockMovement


@pytest_asyncio.fixture
async def cost_book(api, session):
    username = "logistics-cost-owner"
    session.add(User(username=username, full_name="Synthetic cost owner", role="director", status="active"))
    await session.commit()
    api.headers["X-User"] = username
    response = await api.post("/accounting/organizations", json={"name": "Synthetic cost company", "unp": "999999964"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def add_import(api, session, org, amount, *, stage="warehouse", ownership="own", bind=True):
    row = ImportShipment(number="SYN-" + uuid4().hex, supplier="Synthetic", cargo="Synthetic",
                         qty=1, amount=Decimal(amount), stage=stage)
    session.add(row)
    await session.commit()
    if bind:
        response = await api.post(f"/accounting/organizations/{org}/source-bindings", json={
            "source_type": "logistics_import", "source_id": row.id, "ownership": ownership,
            "evidence": "Synthetic explicit import ownership for cost projection",
        })
        assert response.status_code == 201, response.text
    return row.id


async def review(api, org):
    response = await api.get(f"/logistics/organizations/{org}/cost-insights")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organization_id"] == org and body["version"] == 1
    assert body["complete_cost_coverage"] is False and body["status"] == "partial"
    assert body["posting_status"] == "not_verified"
    assert set(body["unavailable_sections"]) == {"tariffs", "tenders", "audit"}
    return body["import_freight"]


def test_no_qualified_rows_is_unknown_not_zero():
    result = FreightAccumulator().result()
    assert result.status == "unknown" and result.total is None and result.known_total is None
    assert result.known_average is None and result.qualified_import_count == 0


def test_decimal_total_and_half_up_average_without_float():
    summary = FreightAccumulator()
    for amount in (Decimal("0.01"), Decimal("0.02")):
        summary.add("warehouse", amount)
    result = summary.result()
    assert result.total == "0.03" and result.known_average == "0.02" and result.known_count == 2


def test_nonfinite_missing_or_unpriced_amounts_cannot_create_known_zero():
    summary = FreightAccumulator()
    for amount in (None, Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), Decimal("0"), Decimal("-1")):
        summary.add("warehouse", amount)
    result = summary.result()
    assert result.status == "unknown" and result.total is None and result.known_average is None
    assert result.unpriced_count == result.warehouse_import_count == 6


async def test_no_bound_sources_does_not_report_company_zero(api, session, cost_book):
    await add_import(api, session, cost_book, "9000.00", bind=False)
    result = await review(api, cost_book)
    assert result["status"] == "unknown" and result["total"] is None
    assert result["known_total"] is None and result["qualified_import_count"] == 0


async def test_only_exact_own_sources_and_current_book_reader_can_read(api, session, cost_book):
    other = await api.post("/accounting/organizations", json={"name": "Other synthetic cost company", "unp": "999999965"})
    assert other.status_code == 201, other.text
    foreign = other.json()["id"]
    await add_import(api, session, cost_book, "12000.00")
    await add_import(api, session, cost_book, "5000.00")
    await add_import(api, session, foreign, "999999.00")
    await add_import(api, session, cost_book, "777777.00", bind=False)
    await add_import(api, session, cost_book, "333333.00", ownership="customer")
    result = await review(api, cost_book)
    assert result["total"] == result["known_total"] == "17000.00"
    assert result["known_average"] == "8500.00" and result["known_count"] == 2
    assert result["qualified_import_count"] == 2
    session.add(User(username="cost-reader", full_name="Synthetic cost reader", role="logistics", status="active"))
    await session.commit()
    grant = await api.put(f"/accounting/organizations/{cost_book}/members", json={"subject": "cost-reader", "role": "reader"})
    assert grant.status_code == 200, grant.text
    api.headers.update({"X-User": "cost-reader", "X-User-Roles": "logistics"})
    assert (await review(api, cost_book))["total"] == "17000.00"
    denied = await api.get(f"/logistics/organizations/{foreign}/cost-insights")
    assert denied.status_code == 403, denied.text
    assert "999999" not in denied.text


@pytest.mark.parametrize("amount", ["0.00", "-1.00"])
async def test_zero_or_negative_source_is_unpriced(api, session, cost_book, amount):
    await add_import(api, session, cost_book, amount)
    result = await review(api, cost_book)
    assert result["status"] == "unknown" and result["total"] is None
    assert result["known_total"] is None and result["known_average"] is None
    assert result["unpriced_count"] == 1 and result["known_count"] == 0


async def test_known_subtotal_is_retained_but_partial_total_stays_unknown(api, session, cost_book):
    for amount in ("12000.00", "5000.00", "0.00"):
        await add_import(api, session, cost_book, amount)
    result = await review(api, cost_book)
    assert result["status"] == "partial" and result["total"] is None
    assert result["known_total"] == "17000.00" and result["known_average"] == "8500.00"
    assert result["known_count"] == 2 and result["unpriced_count"] == 1


async def test_nonwarehouse_source_does_not_count_as_arrived_cost(api, session, cost_book):
    await add_import(api, session, cost_book, "8000.00", stage="in_transit")
    result = await review(api, cost_book)
    assert result["qualified_import_count"] == result["excluded_nonwarehouse_count"] == 1
    assert result["warehouse_import_count"] == result["known_count"] == 0
    assert result["total"] is None


async def test_revoked_membership_is_rechecked(api, session, cost_book):
    await add_import(api, session, cost_book, "300.00")
    assert (await review(api, cost_book))["total"] == "300.00"
    await session.execute(delete(AccessGrant).where(AccessGrant.organization_id == cost_book,
                                                  AccessGrant.subject == "logistics-cost-owner"))
    await session.commit()
    response = await api.get(f"/logistics/organizations/{cost_book}/cost-insights")
    assert response.status_code == 403, response.text
    assert "300.00" not in response.text


async def test_inactive_user_cannot_read_amounts(api, session, cost_book):
    await add_import(api, session, cost_book, "300.00")
    user = await session.scalar(select(User).where(User.username == "logistics-cost-owner"))
    user.status = "inactive"
    await session.commit()
    response = await api.get(f"/logistics/organizations/{cost_book}/cost-insights")
    assert response.status_code == 403, response.text


async def test_absent_accounting_facade_refuses_without_data(api, monkeypatch, cost_book):
    monkeypatch.setattr(api._transport.app.state.core.services, "accounting", None)
    response = await api.get(f"/logistics/organizations/{cost_book}/cost-insights")
    assert response.status_code == 503 and response.json()["detail"] == "accounting_source_access_unavailable"


async def test_get_is_readonly_and_global_route_stays_closed(api, session, cost_book):
    await add_import(api, session, cost_book, "300.00")
    models = (SourceBinding, ImportShipment, StockMovement, OutboxEvent)
    before = [await session.scalar(select(func.count()).select_from(model)) for model in models]
    assert (await review(api, cost_book))["total"] == "300.00"
    assert (await api.get("/logistics/cost-insights")).status_code == 409
    after = [await session.scalar(select(func.count()).select_from(model)) for model in models]
    assert after == before
