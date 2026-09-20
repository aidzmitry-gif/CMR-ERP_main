"""Real accountant API: complete mixed-cost quantities and immutable replay."""
# ruff: noqa: F811
import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from core.runtime.deps import get_session
from core.services.auth import CurrentUser, get_current_user
from modules.accounting import models, routes, service
from modules.accounting.gateway import AccountingService
from modules.accounting.production_output_cost_workflow import (
    ProductionOutputCostPreviewInput,
    confirm_output_cost_correction,
    preview_output_cost_correction,
)
from modules.accounting.production_output_transfer import (
    ProductionOutputTransferConfirmInput,
    confirm_output_transfer,
    prepare_output_transfer,
)
from modules.accounting.schemas import LineInput, PostingInput
from tests.accounting.test_finished_goods_inventory_postgres import _output_cost_command
from tests.accounting.test_inventory_allocation_cost_stream_postgres import TwoOutputs
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_production_output_transfer_postgres import (
    _seed_production_book,
    _seed_wip,
    transfer_input,
)
from tests.accounting.test_zero_value_output_cost_postgres import run_migration

pytestmark = pytest.mark.integration


async def output_sources(factory, book, method, *, guarded=True):
    policy_id = await _seed_production_book(factory, book, method)
    await _seed_wip(factory, book, policy_id, [("SHOP", "ORDER-42", "0.01"), ("SHOP", "ORDER-43", "0.01")])
    production, output_ids = TwoOutputs(), []
    async with factory() as session:
        migrations = ["0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                      "0142_zero_value_command_dates.py", "0143_zero_value_sales.py"]
        if guarded:
            migrations += ["0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py"]
        for revision in migrations:
            await run_migration(session, revision, "upgrade")
        for order_id in (42, 43):
            command = transfer_input(policy_id).model_copy(update={
                "order_id": order_id, "analytical_order": f"ORDER-{order_id}", "output_document_ids": [order_id + 59]})
            preview = await prepare_output_transfer(session, book[0], "2026-10", command, production, object())
            confirmation = ProductionOutputTransferConfirmInput.model_validate({
                **command.model_dump(mode="json"), "basis_digest": preview["basis_digest"], "digest": preview["digest"]})
            output = await confirm_output_transfer(session, book[0], "2026-10", confirmation, "tester",
                                                   production=production, warehouse_gateway=object())
            output_ids.append(output.id)
        await session.commit()
    return policy_id, output_ids


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


def issue_document(policy_id):
    return {"source": "mixed-accountant-api", "source_version": 1, "policy_id": policy_id,
            "document_date": "2026-10-29", "operation_date": "2026-10-30", "posting_date": "2026-10-31",
            "account": "43", "warehouse": "Main", "sku": "SYN-WIDGET", "lot": "", "quantity": "2.1",
            "expense_account": "90.4", "expense_dimensions": {}, "explanation": "Reviewed mixed issue via HTTP"}


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
@pytest.mark.parametrize("sale", [False, True])
async def test_accountant_mixed_allocation_http_confirm_retry_stock_and_late_cost(pg_factory, pg_book, method, sale):
    policy_id, outputs = await output_sources(pg_factory, pg_book, method)
    payload = issue_document(policy_id)
    if sale:
        payload |= {"net_amount": "10.00", "vat_rate": "0", "vat_basis": "Synthetic exemption",
                    "buyer_account": "62", "revenue_account": "90.1", "vat_revenue_account": "90.2",
                    "vat_payable_account": "68", "buyer_dimensions": {
                        "counterparty": "BUYER", "contract": "CONTRACT", "settlement_document": "INVOICE"}}
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


async def test_missing_database_allocation_guards_refuses_mixed_packet(pg_factory, pg_book):
    policy_id, _ = await output_sources(pg_factory, pg_book, "weighted_average", guarded=False)
    async with AsyncClient(transport=ASGITransport(app=application(pg_factory)), base_url="http://test") as client:
        response = await client.post(f"/accounting/organizations/{pg_book[0]}/inventory/issues/posting-preview",
                                     json=issue_document(policy_id))
        assert response.status_code == 422 and "0144 and 0145" in response.text
