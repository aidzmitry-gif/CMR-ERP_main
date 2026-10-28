"""HTTP/PG evidence for the narrow specific zero-value issue adapter."""
# ruff: noqa: F811 -- imported fixtures are used by pytest parameter lookup.
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from core.domain.models import Sku
from core.runtime.deps import get_session
from core.services.auth import CurrentUser, get_current_user
from modules.accounting import inventory_issues, routes, service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import Audit, Organization, Period, ZeroValueInventoryDisposalReceipt
from modules.accounting.production_output_cost_workflow import confirm_output_cost_correction
from modules.accounting.schemas import LineInput, PostingInput
from modules.wms.models import WarehouseDirectory
from tests.accounting.test_finished_goods_inventory_postgres import _output_cost_command
from tests.accounting.test_inventory_allocation_api_postgres import (
    inventory_identities,
    output_sources,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_zero_value_disposals_postgres import zeroed_output
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401

pytestmark = pytest.mark.integration

@pytest.mark.parametrize("concurrent", [False, True])
async def test_http_specific_zero_issue_preview_confirm_retry_and_remaining(pg_factory, pg_book, concurrent):
    policy_id, output_id, _ = await zeroed_output(pg_factory, pg_book)
    identities = await inventory_identities(pg_factory, pg_book)
    app = FastAPI()
    app.include_router(routes.router, prefix="/accounting")
    app.state.core = SimpleNamespace(services=SimpleNamespace(event_bus=None, accounting=AccountingService()))

    async def session_dependency():
        async with pg_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["director"])
    base = f"/accounting/organizations/{pg_book[0]}/inventory/issues"
    payload = {
        "source": "inventory:zero:api", "source_version": 1, "policy_id": policy_id,
        "document_date": "2026-10-29", "operation_date": "2026-10-30", "posting_date": "2026-10-31",
        "account": "43", "warehouse": "Main", "sku": "SYN-WIDGET", "lot": "LOT-1", "quantity": "0.5",
        "expense_account": "90.4", "expense_dimensions": {},
        "explanation": "API verified zero value issue",
        **identities,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rejected_wip = await client.post(base + "/posting-preview", json={
            **payload, "expense_account": "20", "expense_dimensions": {"department": "SHOP", "order": "ORDER-42"}})
        assert rejected_wip.status_code == 422 and "expense account" in rejected_wip.text
        rejected_production = await client.post(base + "/posting-preview", json={
            **payload, "source": "production:material:forged"})
        assert rejected_production.status_code == 422 and "reviewed production workflow" in rejected_production.text
        if not concurrent:
            async with pg_factory() as session:
                foreign_org = Organization(id=999, name="Foreign directory owner", unp="888888888")
                session.add(foreign_org)
                await session.flush()
                foreign_warehouse = WarehouseDirectory(
                    organization_id=foreign_org.id, name="Foreign", title="Foreign warehouse", created_by="tester")
                session.add(foreign_warehouse)
                await session.flush()
                foreign_identity = {
                    "id": foreign_warehouse.id, "name": foreign_warehouse.name,
                    "title": foreign_warehouse.title,
                }
                await session.commit()
            rejected_foreign = await client.post(base + "/posting-preview", json={
                **payload, "warehouse": "Foreign", "warehouse_identity": foreign_identity,
            })
            assert rejected_foreign.status_code == 422 and "Warehouse directory record changed" in rejected_foreign.text
        preview = await client.post(base + "/posting-preview", json=payload)
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["kind"] == "quantity_only_receipt" and body["posting"] is None
        assert body["command"]["command_version"] == 6
        assert body["command"]["document"]["warehouse_identity"] == identities["warehouse_identity"]
        assert body["command"]["document"]["sku_identity"] == identities["sku_identity"]
        initial_lots = await client.get(f"/accounting/organizations/{pg_book[0]}/inventory/lots", params={
            "policy_id": policy_id, "posting_date": "2026-10-31", "account": "43", "warehouse": "Main", "sku": "SYN-WIDGET",
        })
        assert initial_lots.status_code == 200 and initial_lots.json()["lots"][0]["selectable"] is True
        async with pg_factory() as reader:
            before_org = (await reader.get(Organization, pg_book[0])).generation
            before_period = await reader.scalar(select(Period).where(
                Period.organization_id == pg_book[0], Period.month == "2026-10"))
            before_period.evidence = {"synthetic": "pre-confirm evidence"}
            await reader.commit()
            before_audit = await reader.scalar(select(func.count()).select_from(Audit).where(
                Audit.organization_id == pg_book[0], Audit.action == "zero_value_disposal_registered"))
            before_generation = before_period.generation
        confirmation = {**payload, "basis_digest": body["cost"]["basis_digest"], "digest": body["digest"]}
        if concurrent:
            responses = await asyncio.gather(*(client.post(base + "/confirm", json=confirmation) for _ in range(2)))
            assert all(response.status_code == 201 for response in responses), [response.text for response in responses]
            assert responses[0].json()["receipt_id"] == responses[1].json()["receipt_id"]
            saved = responses[0]
        else:
            saved = await client.post(base + "/confirm", json=confirmation)
        assert saved.status_code == 201, saved.text
        assert saved.json()["receipt_id"] and saved.json()["registration_token"]
        async with pg_factory() as reader:
            assert await reader.scalar(select(func.count()).select_from(ZeroValueInventoryDisposalReceipt).where(
                ZeroValueInventoryDisposalReceipt.organization_id == pg_book[0],
                ZeroValueInventoryDisposalReceipt.source == payload["source"])) == 1
            assert (await reader.get(Organization, pg_book[0])).generation == before_org + 1
            period = await reader.scalar(select(Period).where(
                Period.organization_id == pg_book[0], Period.month == "2026-10"))
            assert period.generation == before_generation + 1 and period.evidence == {}
            assert await reader.scalar(select(func.count()).select_from(Audit).where(
                Audit.organization_id == pg_book[0], Audit.action == "zero_value_disposal_registered")) == before_audit + 1
        repeated = await client.post(base + "/confirm", json={**payload, "basis_digest": body["cost"]["basis_digest"], "digest": body["digest"]})
        assert repeated.status_code == 201 and repeated.json()["receipt_id"] == saved.json()["receipt_id"]
        async with pg_factory() as reader:
            assert (await reader.get(Organization, pg_book[0])).generation == before_org + 1
            assert await reader.scalar(select(func.count()).select_from(Audit).where(
                Audit.organization_id == pg_book[0], Audit.action == "zero_value_disposal_registered")) == before_audit + 1
        changed = await client.post(base + "/confirm", json={
            **payload, "document_date": "2026-10-28", "basis_digest": body["cost"]["basis_digest"], "digest": body["digest"],
        })
        assert changed.status_code == 422 and "different content" in changed.text
        remaining = await client.post(f"/accounting/organizations/{pg_book[0]}/inventory/issues/preview", json={
            "policy_id": policy_id, "posting_date": "2026-10-31", "account": "43", "warehouse": "Main",
            "sku": "SYN-WIDGET", "lot": "LOT-1", "quantity": "1.5",
        })
        assert remaining.status_code == 200, remaining.text
        assert remaining.json()["book_quantity"] == "1.500000"
        lots = await client.get(f"/accounting/organizations/{pg_book[0]}/inventory/lots", params={
            "policy_id": policy_id, "posting_date": "2026-10-31", "account": "43", "warehouse": "Main", "sku": "SYN-WIDGET",
        })
        assert lots.status_code == 200 and lots.json()["lots"] == [{
            "lot": "LOT-1", "book_quantity": "1.500000", "book_value_byn": "0.00",
            "selectable": True, "reason": None,
        }]
        overdraw = await client.post(base + "/posting-preview", json={**payload, "source": "inventory:zero:overdraw", "quantity": "2"})
        assert overdraw.status_code == 422 and "Insufficient book quantity" in overdraw.text

        if not concurrent:
            async with pg_factory() as session:
                await service.post(session, pg_book[0], PostingInput(
                    source="zero-api-late-wip", source_version=1, operation="manual",
                    document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
                    policy_id=policy_id, rule_version="synthetic", explanation="Late production cost",
                    lines=[LineInput(account="20", side="debit", amount="100",
                                     dimensions={"department": "SHOP", "order": "ORDER-42"}),
                           LineInput(account="60", side="credit", amount="100")]), "tester")
                await confirm_output_cost_correction(session, pg_book[0], "2026-10",
                    await _output_cost_command(session, pg_book[0], output_id), "tester")
                await session.commit()
            monetary = {**payload, "source": "inventory:money:after-zero", "quantity": "1.5",
                        "expense_account": "90.4", "expense_dimensions": {}}
            money_preview = await client.post(base + "/posting-preview", json=monetary)
            assert money_preview.status_code == 200, money_preview.text
            money_body = money_preview.json()
            assert money_body["cost"]["issue_cost_byn"] == "75.00"
            money_confirm = {**monetary, "basis_digest": money_body["cost"]["basis_digest"],
                             "digest": money_body["digest"]}
            money_saved = await client.post(base + "/confirm", json=money_confirm)
            assert money_saved.status_code == 201, money_saved.text
            money_id = money_saved.json()["id"]
            money_retry = await client.post(base + "/confirm", json=money_confirm)
            assert money_retry.status_code == 201, money_retry.text
            assert money_retry.json()["id"] == money_id
            async with pg_factory() as session:
                original = await inventory_issues.verify_receipt(session, pg_book[0], money_id)
                await service.post(session, pg_book[0], PostingInput(
                    source="zero-api-subsequent", source_version=1, operation="manual",
                    document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
                    policy_id=policy_id, rule_version="synthetic", explanation="Subsequent cost",
                    lines=[LineInput(account="20", side="debit", amount="20",
                                     dimensions={"department": "SHOP", "order": "ORDER-42"}),
                           LineInput(account="60", side="credit", amount="20")]), "tester")
                await session.commit()
            async with pg_factory() as session:
                historical = await inventory_issues.verify_receipt(session, pg_book[0], money_id)
                assert historical.model_dump() == original.model_dump()
                warehouse = await session.get(WarehouseDirectory, identities["warehouse_identity"]["id"])
                sku = await session.get(Sku, identities["sku_identity"]["id"])
                warehouse.title = "Renamed warehouse"
                sku.title = "Renamed synthetic widget"
                await session.commit()
            zero_after_rename = await client.post(base + "/confirm", json=confirmation)
            assert zero_after_rename.status_code == 201
            assert zero_after_rename.json()["receipt_id"] == saved.json()["receipt_id"]
            money_after_rename = await client.post(base + "/confirm", json=money_confirm)
            assert money_after_rename.status_code == 201 and money_after_rename.json()["id"] == money_id
            stale_new = await client.post(base + "/posting-preview", json={
                **payload, "source": "inventory:stale:after-directory-rename",
            })
            assert stale_new.status_code == 422 and "record changed" in stale_new.text

    app.dependency_overrides[get_current_user] = lambda: CurrentUser("outsider", ["director"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.post(base + "/posting-preview", json=payload)
        assert denied.status_code == 403


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
async def test_http_v4_zero_issue_multi_source_confirm_retry_after_late_cost(pg_factory, pg_book, method, issuance_pg):
    """The public issue route persists the complete server-selected V4 packet."""
    policy_id, outputs = await output_sources(pg_factory, pg_book, method, api=issuance_pg[0])
    async with pg_factory() as session:
        await service.post(session, pg_book[0], PostingInput(
            source="v4-zero-reverse-wip", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Reverse initial output cost", lines=[
                LineInput(account="60", side="debit", amount="0.02"),
                *[LineInput(account="20", side="credit", amount="0.01",
                            dimensions={"department": "SHOP", "order": order})
                  for order in ("ORDER-42", "ORDER-43")],
            ]), "tester")
        for output_id in outputs:
            await confirm_output_cost_correction(session, pg_book[0], "2026-10",
                                                 await _output_cost_command(session, pg_book[0], output_id), "tester")
        await session.commit()
    identities = await inventory_identities(pg_factory, pg_book)

    app = FastAPI()
    app.include_router(routes.router, prefix="/accounting")
    app.state.core = SimpleNamespace(services=SimpleNamespace(event_bus=None, accounting=AccountingService()))

    async def session_dependency():
        async with pg_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["director"])
    base = f"/accounting/organizations/{pg_book[0]}/inventory/issues"
    payload = {"source": f"v4-zero-issue:{method}", "source_version": 1, "policy_id": policy_id,
               "document_date": "2026-10-29", "operation_date": "2026-10-30", "posting_date": "2026-10-31",
               "account": "43", "warehouse": "Main", "sku": "SYN-WIDGET", "lot": "", "quantity": "3.1",
               "expense_account": "90.4", "expense_dimensions": {}, "explanation": "Reviewed zero allocation issue",
               **identities}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        preview = await client.post(base + "/posting-preview", json=payload)
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["kind"] == "quantity_only_receipt" and body["posting"] is None
        assert body["command"]["command_version"] == 4
        assert body["command"]["document"]["warehouse_identity"] == identities["warehouse_identity"]
        assert body["command"]["document"]["sku_identity"] == identities["sku_identity"]
        assert body["receipt"]["zero_byn"] is True and "source_layer" not in body["receipt"]
        assert len(body["receipt"]["source_layers"]) == 2
        confirmation = {**payload, "basis_digest": body["basis_digest"], "digest": body["digest"]}
        saved = await client.post(base + "/confirm", json=confirmation)
        assert saved.status_code == 201, saved.text
        changed = await client.post(base + "/confirm", json={**confirmation, "explanation": "changed"})
        assert changed.status_code == 422 and "different content" in changed.text

        async with pg_factory() as session:
            await service.post(session, pg_book[0], PostingInput(
                source=f"v4-zero-late-wip:{method}", source_version=1, operation="manual",
                document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
                policy_id=policy_id, rule_version="synthetic", explanation="Late output cost", lines=[
                    LineInput(account="20", side="debit", amount="1.00",
                              dimensions={"department": "SHOP", "order": "ORDER-42"}),
                    LineInput(account="60", side="credit", amount="1.00"),
                ]), "tester")
            await confirm_output_cost_correction(session, pg_book[0], "2026-10",
                                                 await _output_cost_command(session, pg_book[0], outputs[0]), "tester")
            await session.commit()
        retry = await client.post(base + "/confirm", json=confirmation)
        assert retry.status_code == 201, retry.text
        assert retry.json()["receipt_id"] == saved.json()["receipt_id"]
