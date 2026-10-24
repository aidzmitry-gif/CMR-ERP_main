"""Real accountant API: complete mixed-cost quantities and immutable replay."""
# ruff: noqa: F811
import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import Sku
from core.runtime.deps import get_session
from core.services.auth import CurrentUser, get_current_user
from modules.accounting import models, routes, service
from modules.accounting.gateway import AccountingService
from modules.accounting.production_output_cost_workflow import (
    ProductionOutputCostPreviewInput,
    confirm_output_cost_correction,
    preview_output_cost_correction,
)
from modules.accounting.schemas import LineInput, PostingInput
from modules.wms.models import WarehouseDirectory
from tests.accounting.test_finished_goods_inventory_postgres import _output_cost_command
from tests.accounting.test_inventory_allocation_cost_stream_postgres import (
    production_output_sources,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_zero_value_output_cost_postgres import run_migration
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401

pytestmark = pytest.mark.integration


async def inventory_identities(factory, book):
    """Seed and return the two directory snapshots required by a public issue."""
    async with factory() as session:
        warehouse = await session.scalar(select(WarehouseDirectory).where(
            WarehouseDirectory.organization_id == book[0], WarehouseDirectory.name == "Main"))
        if warehouse is None:
            warehouse = WarehouseDirectory(
                organization_id=book[0], name="Main", title="Main warehouse", created_by="tester")
            session.add(warehouse)
        sku = await session.scalar(select(Sku).where(Sku.code == "SYN-WIDGET"))
        if sku is None:
            sku = Sku(code="SYN-WIDGET", title="Synthetic widget", unit="шт", is_active=True)
            session.add(sku)
        await session.flush()
        result = {
            "warehouse_identity": {"id": warehouse.id, "name": warehouse.name, "title": warehouse.title},
            "sku_identity": {"id": sku.id, "code": sku.code, "title": sku.title, "unit": sku.unit},
        }
        await session.commit()
        return result


async def output_sources(factory, book, method, *, api):
    result = await production_output_sources(factory, book, api=api, method=method)
    await inventory_identities(factory, book)
    return result


async def prepare_allocation_revision_0145(factory):
    """Exercise 0146-0150 functions on owned modern data; this is not a schema restore."""
    import re

    from tests.accounting.historical_0145 import portable_snapshot

    async with factory() as session:
        database = await session.scalar(text("SELECT current_database()"))
        assert re.fullmatch(r"acc_test_[a-f0-9]{32}", database)
        marker = await session.scalar(text(
            "SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"))
        assert marker == f"crm-acc-fixture:{database}"
        assert (await session.scalars(text("SELECT version_num FROM alembic_version"))).all() == ["0199"]
        assert await session.scalar(text("SELECT count(*) FROM accounting.inventory_zero_value_disposal_receipt")) == 0
        assert await session.scalar(text("""SELECT count(*) FROM accounting.inventory_issue_receipt
            WHERE command::jsonb->>'source' LIKE 'production:material:%'
              AND cost::jsonb ? 'source_allocation_version'""")) == 0
    before = await portable_snapshot(factory)
    async with factory() as session:
        for revision in (
            "0150_zero_material_allocations.py", "0149_production_material_allocations.py",
            "0148_zero_value_allocated_sales.py", "0147_zero_value_allocation_runtime.py",
            "0146_zero_value_allocation_basis.py",
        ):
            await run_migration(session, revision, "downgrade")
        for signature in (
            "accounting.production_material_zero_allocation_version()",
            "accounting.production_material_allocation_version()",
            "accounting.zero_value_allocated_sale_version()",
            "accounting.zero_value_allocation_runtime_version()",
            "accounting.zero_value_allocation_basis(integer,jsonb,integer)",
            "accounting.zero_value_material_allocation_basis(integer,jsonb,integer)",
            "accounting.zero_allocation_cost_stream(integer,text,text,text,date,integer)",
        ):
            assert await session.scalar(text("SELECT to_regprocedure(:signature)"), {"signature": signature}) is None
        await session.commit()
    assert await portable_snapshot(factory) == before


def application(factory):
    app = FastAPI()
    app.include_router(routes.router, prefix="/accounting")
    app.state.core = SimpleNamespace(services=SimpleNamespace(event_bus=None, accounting=AccountingService()))

    async def sessions():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["director"])
    return app


def issue_document(policy_id, identities):
    return {"source": "mixed-accountant-api", "source_version": 1, "policy_id": policy_id,
            "document_date": "2026-10-29", "operation_date": "2026-10-30", "posting_date": "2026-10-31",
            "account": "43", "warehouse": "Main", "sku": "SYN-WIDGET", "lot": "", "quantity": "2.1",
            "expense_account": "90.4", "expense_dimensions": {}, "explanation": "Reviewed mixed issue via HTTP",
            **identities}


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
@pytest.mark.parametrize("sale", [False, True])
@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_accountant_mixed_allocation_http_confirm_retry_stock_and_late_cost(pg_factory, pg_book, method, sale, issuance_pg):
    policy_id, outputs = await output_sources(pg_factory, pg_book, method, api=issuance_pg[0])
    payload = issue_document(policy_id, await inventory_identities(pg_factory, pg_book))
    if sale:
        payload |= {"net_amount": "10.00", "vat_rate": "0", "vat_basis": "Synthetic exemption",
                    "buyer_account": "62", "revenue_account": "90.1", "vat_revenue_account": "90.2",
                    "vat_payable_account": "68", "buyer_dimensions": {
                        "counterparty_id": "1", "counterparty": "supplier1",
                        "counterparty_unp": "190000001", "counterparty_revision": "1",
                        "contract": "CONTRACT", "settlement_document": "INVOICE"}}
    org_url = f"/accounting/organizations/{pg_book[0]}"
    base = org_url + ("/sales" if sale else "/inventory/issues")
    async with AsyncClient(transport=ASGITransport(app=application(pg_factory)), base_url="http://test") as client:
        preview = await client.post(base + "/posting-preview", json=payload)
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["cost"]["source_allocation_version"] == 1
        assert [layer["amount_byn"] for layer in body["cost"]["inventory_layers"]] == ["0.01", "0.00"]
        assert body["posting"]["rule_version"].endswith(":a1")
        assert all(Decimal(line["amount"]) > 0 for line in body["posting"]["lines"])
        confirmation = {**payload, "basis_digest": body["cost"]["basis_digest"], "digest": body["digest"]}
        posted = await asyncio.gather(*(client.post(base + "/confirm", json=confirmation) for _ in range(2)))
        assert all(row.status_code == 201 for row in posted), [row.text for row in posted]
        entry_id = posted[0].json()["id"]
        assert posted[1].json()["id"] == entry_id
        async with pg_factory() as reader:
            with pytest.raises(DBAPIError, match="explicit inventory disposal history"):
                async with reader.begin_nested():
                    await run_migration(reader, "0145_inventory_allocation_cost_stream.py", "downgrade")
        for changed in ({"document_date": "2026-10-28"}, {"source": "other-source"}, {"source_version": 2}):
            response = await client.post(base + "/confirm", json={**confirmation, **changed})
            assert response.status_code == 422, response.text
        foreign = await client.post(f"/accounting/organizations/{pg_book[0] + 1000}/sales/posting-preview" if sale else
                                    f"/accounting/organizations/{pg_book[0] + 1000}/inventory/issues/posting-preview", json=payload)
        assert foreign.status_code in {403, 404}, foreign.text
        lots = await client.get(org_url + "/inventory/lots", params={
            "policy_id": policy_id, "posting_date": "2026-10-31", "account": "43", "warehouse": "Main", "sku": "SYN-WIDGET"})
        assert lots.status_code == 200, lots.text
        assert sum(Decimal(row["book_quantity"]) for row in lots.json()["lots"]) == Decimal("1.9")
        assert sum(Decimal(row["book_value_byn"]) for row in lots.json()["lots"]) == Decimal("0.01")
        next_payload = {**payload, "source": "mixed-accountant-api-rest", "quantity": "1.9"}
        remaining = await client.post(base + "/posting-preview", json=next_payload)
        assert remaining.status_code == 200, remaining.text
        next_body = remaining.json()
        assert next_body["cost"]["issue_cost_byn"] == "0.01"
        consumed = await client.post(base + "/confirm", json={**next_payload,
            "basis_digest": next_body["cost"]["basis_digest"], "digest": next_body["digest"]})
        assert consumed.status_code == 201, consumed.text
        retry = await client.post(base + "/confirm", json=confirmation)
        assert retry.status_code == 201 and retry.json()["id"] == entry_id, retry.text
    async with pg_factory() as session:
        receipt_type = models.InventorySaleReceipt if sale else models.InventoryIssueReceipt
        assert await session.scalar(select(func.count()).select_from(receipt_type)) == 2
        await service.post(session, pg_book[0], PostingInput(source="mixed-api-late-cost", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic", explanation="Late WIP after actual API disposal", lines=[
                LineInput(account="20", side="debit", amount="100", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="100")]), "tester")
        command = await _output_cost_command(session, pg_book[0], outputs[0])
        preview = await preview_output_cost_correction(session, pg_book[0], "2026-10",
            ProductionOutputCostPreviewInput(**command.model_dump(include=set(ProductionOutputCostPreviewInput.model_fields))))
        assert sum(row["delta_cents"] for row in preview["destinations"] if row["kind"] == "disposed") == 10000
        assert not any(row["delta_cents"] for row in preview["destinations"] if row["kind"] == "remaining")
        await confirm_output_cost_correction(session, pg_book[0], "2026-10", command, "tester")
        await session.commit()
        original_policy = await session.get(models.Policy, policy_id)
        next_policy = models.Policy(organization_id=pg_book[0], effective_from=date(2026, 11, 1),
            reference="Synthetic changed method", inventory_method="specific", allocation_basis="direct_cost",
            depreciation_method="straight_line", normative_reference="Synthetic", normative_verified=False,
            approved_by="tester", production_costing=original_policy.production_costing)
        session.add(next_policy)
        await session.commit()
        next_policy_id = next_policy.id
    async with AsyncClient(transport=ASGITransport(app=application(pg_factory)), base_url="http://test") as client:
        retry_after_correction = await client.post(base + "/confirm", json=confirmation)
        assert retry_after_correction.status_code == 201 and retry_after_correction.json()["id"] == entry_id, retry_after_correction.text
        changed_policy_lots = await client.get(org_url + "/inventory/lots", params={
            "policy_id": next_policy_id, "posting_date": "2026-11-01", "account": "43", "warehouse": "Main", "sku": "SYN-WIDGET"})
        assert changed_policy_lots.status_code == 200, changed_policy_lots.text
        lot_rows = changed_policy_lots.json()["lots"]
        assert lot_rows and all(not row["selectable"] and row["book_quantity"] is None for row in lot_rows)
        assert all("FIFO or weighted-average" in row["reason"] for row in lot_rows)
        blocked = await client.post(org_url + "/inventory/issues/preview", json={
            "policy_id": next_policy_id, "posting_date": "2026-11-01", "account": "43", "warehouse": "Main",
            "sku": "SYN-WIDGET", "lot": "LOT-43", "quantity": "0.1"})
        assert blocked.status_code == 422 and "FIFO or weighted-average" in blocked.text


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_public_issue_requires_both_directory_snapshots(pg_factory, pg_book, issuance_pg):
    policy_id, _ = await output_sources(pg_factory, pg_book, "weighted_average", api=issuance_pg[0])
    payload = issue_document(policy_id, await inventory_identities(pg_factory, pg_book))
    payload.pop("warehouse_identity")
    payload.pop("sku_identity")
    async with AsyncClient(transport=ASGITransport(app=application(pg_factory)), base_url="http://test") as client:
        response = await client.post(f"/accounting/organizations/{pg_book[0]}/inventory/issues/posting-preview",
                                     json=payload)
        assert response.status_code == 422 and "warehouse and item" in response.text
