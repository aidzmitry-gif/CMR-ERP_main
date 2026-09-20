"""PostgreSQL evidence for the reviewed material-to-WIP posting."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import OutboxEvent
from core.services.auth import CurrentUser, get_current_user
from modules.accounting import service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import (
    AccessGrant,
    Account,
    Entry,
    InventoryIssueReceipt,
    Line,
    Policy,
    ZeroValueInventoryDisposalReceipt,
)
from modules.accounting.production_material_cost import (
    ProductionMaterialIssuePostingConfirmInput,
    ProductionMaterialIssuePostingInput,
    confirm_material_issue_posting,
    confirm_material_zero_issue,
    prepare_material_issue_posting,
    prepare_material_zero_issue,
    verify_material_issue_receipt,
)
from modules.accounting.schemas import LineInput, PostingInput
from modules.accounting.zero_value_disposals import ProductionMaterialZeroValueDisposalCommand
from modules.production.accounting_ownership import OwnershipCommand, assign_order, order_snapshot
from modules.production.models import ProductionOrder
from modules.wms.models import StockMovement
from modules.wms.production_material_issues import (
    ProductionMaterialIssueCommand,
    record_material_issue,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_zero_value_output_cost_postgres import run_migration

pytestmark = pytest.mark.integration


class SyntheticProduction:
    async def cost_orders(self, _session, _organization_id, order_ids):
        return [{"order_id": order_ids[0], "product": "Synthetic widget", "quantity": "2.00"}]


@pytest.mark.parametrize("method,wip_delta,remaining_delta", [
    ("fifo", "2.00", "3.00"), ("weighted_average", "1.25", "3.75"),
])
@pytest.mark.parametrize("with_output", [False, True])
async def test_late_pool_reads_actual_multiple_purchases_and_material_receipt(pg_factory, pg_book, method, wip_delta, remaining_delta, with_output, monkeypatch):
    from modules.accounting import late_pool_cost, production_output_cost_workflow
    from modules.accounting.closing_controls import snapshot as closing_snapshot
    from modules.accounting.inventory_cost import issue_result
    from modules.accounting.late_cost_pool import load_expense_pools, preview_expense, project_pool
    from modules.accounting.late_cost_posting import ExpenseAccounts, pool_candidate
    from modules.accounting.late_cost_receipts import PoolLateCostCommand, verified_value_lines
    from modules.accounting.late_cost_receipts import verify_receipt as verify_late_cost
    from modules.accounting.schemas import InventoryIssuePreviewInput, LateCostPreviewInput
    from modules.procurement.additional_expenses import AdditionalExpenseCreate, save_document
    from modules.procurement.receipt_documents import (
        ReceiptAccounts,
        ReceiptConfirm,
        ReceiptCreate,
        confirm_receipt,
        create_document,
        preview_document,
    )
    from modules.procurement.source_gateway import ProcurementSourceService

    policy_id, order_id = await seed_book(pg_factory, pg_book, method, late_cost=True)
    gateway, procurement = AccountingService(), ProcurementSourceService()
    user = CurrentUser("tester", ["director"])
    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py",
                         "0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py",
                         "0146_zero_value_allocation_basis.py", "0147_zero_value_allocation_runtime.py",
                         "0148_zero_value_allocated_sales.py", "0149_production_material_allocations.py"):
            await run_migration(session, revision, "upgrade")
        receipts = []
        for index, (quantity, amount) in enumerate((("5", "31.25"), ("3", "30.00")), 1):
            day = f"2026-10-0{index}"
            primary = ReceiptCreate.model_validate({"key": f"pool-origin-{index}", "document": {
                "currency": "BYN", "invoice_reference": f"pool-origin-{index}",
                "document_date": day, "operation_date": day,
                "supplier": "supplier", "contract": "contract", "warehouse": "Main",
                "explanation": "Synthetic pool purchase", "items": [{
                    "sku": "MAT-1", "lot": "LOT-1", "quantity": quantity, "net_amount": amount,
                    "vat_rate": "0", "vat_amount": "0", "vat_basis": "Synthetic"}]}})
            receipt = await create_document(pg_book[0], primary, (session, "tester"), (session, gateway, user))
            options = ReceiptAccounts(expected_version=1, posting_date=day, policy_id=policy_id,
                settlement_account="60", vat_account=None, inventory_accounts=["10.1"])
            prepared = await preview_document(pg_book[0], receipt["id"], options, (session, gateway, user))
            await confirm_receipt(session, pg_book[0], receipt["id"], ReceiptConfirm.model_validate({
                **options.model_dump(mode="json"), "digest": prepared["digest"]}), user, gateway, None)
            receipts.append(receipt)
        await session.commit()
    _, movement_id, _ = await seed_physical_issue(pg_factory, pg_book, order_id)
    data = posting_input(policy_id).model_copy(update={"order_id": order_id, "wms_movement_id": movement_id})
    async with pg_factory() as session:
        prepared = await prepare_material_issue_posting(session, pg_book[0], "2026-10", data,
            SyntheticProduction(), procurement=procurement)
        material = await confirm_material_issue_posting(session, pg_book[0], "2026-10",
            ProductionMaterialIssuePostingConfirmInput.model_validate({**data.model_dump(mode="json"),
                "basis_digest": prepared["basis_digest"], "digest": prepared["digest"]}),
            "tester", procurement=procurement)
        output_id = None
        if with_output:
            from modules.accounting.production_output_transfer import (
                ProductionOutputTransferConfirmInput,
                confirm_output_transfer,
                prepare_output_transfer,
            )
            from tests.accounting.test_production_output_transfer_postgres import (
                SyntheticProduction as OutputProduction,
            )
            from tests.accounting.test_production_output_transfer_postgres import transfer_input

            for revision in ("0150_zero_material_allocations.py", "0151_late_material_output_cost.py",
                             "0152_signed_prospective_wip.py"):
                await run_migration(session, revision, "upgrade")
            output_data = transfer_input(policy_id).model_copy(update={
                "order_id": order_id,
                "posting_date": date(2026, 10, 10),
            })
            output_preview = await prepare_output_transfer(
                session, pg_book[0], "2026-10", output_data, OutputProduction(), object())
            output = await confirm_output_transfer(session, pg_book[0], "2026-10",
                ProductionOutputTransferConfirmInput.model_validate({**output_data.model_dump(mode="json"),
                    "basis_digest": output_preview["basis_digest"], "digest": output_preview["digest"]}),
                "tester", production=OutputProduction(), warehouse_gateway=object())
            output_id = output.id
            from modules.accounting.closing_commands import actual_posting
            from modules.accounting.models import ProductionOutputTransferReceipt

            saved_output = await session.get(ProductionOutputTransferReceipt, output_id)
            assert saved_output is not None
            expected_output = PostingInput.model_validate(saved_output.posting)
            assert service.digest(expected_output) == saved_output.digest
            assert (await actual_posting(session, output)).model_dump() == expected_output.model_dump()
            await session.commit()
        expense, _ = await save_document(session, gateway, user, pg_book[0], AdditionalExpenseCreate.model_validate({
            "key": "pool-freight", "document": {
                "invoice_reference": "pool-freight", "document_date": "2026-10-11", "operation_date": "2026-10-11",
                "supplier": "carrier", "contract": "freight", "currency": "BYN", "amount": "5.00",
                "explanation": "Synthetic pool freight", "receipt_lines": [{
                    "receipt_id": receipts[0]["id"], "version": 1, "line_number": 1}]}}))
        await session.commit()
        before = await session.scalar(select(func.count()).select_from(Entry))
        loaded = await load_expense_pools(session, pg_book[0], expense.id, 1, date(2026, 10, 11), policy_id, procurement)
        pool, = loaded["pools"]
        origin = loaded["origins"][(receipts[0]["id"], 1, 1)]
        source_line = await session.get(Line, origin[1])
        assert source_line.entry_id == origin[0] and source_line.amount == Decimal("31.25")
        result = project_pool(pool["rows"], organization_id=pg_book[0], account=pool["account"],
            warehouse=pool["warehouse"], sku=pool["sku"], method=loaded["method"], on=date(2026, 10, 11),
            additions={origin: Decimal("5.00")}, dispositions=pool["dispositions"], zeros=pool["zeros"],
            verified_values=pool["verified_values"])
        movement, = result["movements"]
        assert movement["entry_id"] == material.id and movement["delta_byn"] == wip_delta
        destination = pool["destinations"][("entry", material.id)]
        assert destination["account"] == "20" and destination["dimensions"]["order"] == "ORDER-42"
        assert sum(Decimal(row["delta_byn"]) for row in result["remaining"]) == Decimal(remaining_delta)
        assert len(result["remaining"]) == 2  # Same lot, two actual acquisition line IDs.
        assert await session.scalar(select(func.count()).select_from(Entry)) == before
        repeated = await load_expense_pools(session, pg_book[0], expense.id, 1, date(2026, 10, 11), policy_id, procurement)
        assert repeated["basis_digest"] == loaded["basis_digest"]
        request = LateCostPreviewInput(expected_version=1, policy_id=policy_id, posting_date="2026-10-11",
            capitalizable_amount_byn="5.00", excluded_amount_byn="0.00", classification_evidence="Synthetic pool freight")
        full = await preview_expense(session, pg_book[0], expense.id, request, procurement)
        candidate = pool_candidate(full, ExpenseAccounts(settlement_account="60"))
        assert sum(line.amount for line in candidate.lines if line.side == "debit" and line.account == "20") == Decimal(wip_delta)
        assert sum(line.amount for line in candidate.lines if line.side == "debit") == Decimal("5.00")
        assert full["confirmation_available"] is False and full["calculation_version"] == 3
        signed_value = PostingInput(source="pool-signed-value-validation", source_version=1,
            operation="inventory_late_cost", document_date="2026-10-11", operation_date="2026-10-11",
            posting_date="2026-10-11", policy_id=policy_id, rule_version="late-cost-pool-v3",
            explanation="Synthetic signed pool validation", lines=[
                LineInput(account="10.1", side="debit", amount="0.01",
                    dimensions={"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"}),
                LineInput(account="10.1", side="credit", amount="0.01",
                    dimensions={"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"}),
            ])
        await service.validate_posting(session, pg_book[0], signed_value, late_cost=True)
        with pytest.raises(service.AccountingError, match="quantity tracking mismatch"):
            await service.validate_posting(session, pg_book[0], signed_value.model_copy(update={
                "source": "pool-legacy-credit-rejection", "rule_version": "late-cost-byn-v1"}), late_cost=True)
        pool_command = PoolLateCostCommand(command_version=3, allocation=request,
            accounts=ExpenseAccounts(settlement_account="60"), material_outputs=(
                [{"output_entry_id": output_id, "amount_byn": wip_delta}] if with_output else []))
        pool_package = await late_pool_cost.prepare(session, pg_book[0], expense.id, pool_command, procurement)
        assert pool_package["command"] == pool_command.model_dump(mode="json")
        if with_output:
            assert pool_package["wip_origins"] == []
            assert pool_package["outputs"][0]["output_entry_id"] == output_id
            assert Decimal(pool_package["outputs"][0]["amount_byn"]) == Decimal(wip_delta)
            assert {(row["account"], row["side"], Decimal(str(row["amount"])))
                    for row in pool_package["outputs"][0]["prospective_evidence"]["matrix"]} == {
                ("20", "credit", Decimal(wip_delta)), ("43", "debit", Decimal(wip_delta))}
            # The correction is posted on the late-cost date.  A later account
            # revision may therefore require analytics absent from the original
            # output, and must make the preview fail before it can be confirmed.
            with pytest.raises(service.AccountingError, match="missing analytics.*serial"):
                async with session.begin_nested():
                    session.add(Account(
                        organization_id=pg_book[0], code="43", title="Synthetic finished goods with serial",
                        category="asset", valid_from=date(2026, 10, 11),
                        required_dimensions=["warehouse", "sku", "lot", "serial"],
                        currency_tracking=False, quantity_tracking=True, cash=False,
                        normative_ref="Synthetic later analytics requirement"))
                    await session.flush()
                    await late_pool_cost.prepare(session, pg_book[0], expense.id, pool_command, procurement)
        else:
            assert pool_package["outputs"] == []
            assert pool_package["wip_origins"][0]["order_id"] == order_id
            assert Decimal(pool_package["wip_origins"][0]["amount_byn"]) == Decimal(wip_delta)
        assert await session.scalar(select(func.count()).select_from(Entry)) == before
        revisions = (("0153_late_pool_atomic_package.py", "0154_late_pool_actual_output_evidence.py",
                      "0155_late_pool_inventory_value_links.py") if with_output else (
                "0150_zero_material_allocations.py", "0151_late_material_output_cost.py",
                "0152_signed_prospective_wip.py", "0153_late_pool_atomic_package.py",
                "0154_late_pool_actual_output_evidence.py", "0155_late_pool_inventory_value_links.py"))
        for revision in revisions:
            await run_migration(session, revision, "upgrade")
        await session.commit()
        from httpx import ASGITransport, AsyncClient

        from tests.accounting.test_inventory_allocation_api_postgres import application

        app = application(pg_factory)
        app.state.core.services.procurement_source = procurement
        pool_api = f"/accounting/organizations/{pg_book[0]}/additional-expenses/{expense.id}/pool"
        before_preview_entry_count = await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.organization_id == pg_book[0]
        ))
        before_preview_package_count = await session.scalar(text("""
            SELECT count(*) FROM accounting.late_pool_package WHERE organization_id=:org
        """), {"org": pg_book[0]})
        before_preview_outbox_count = await session.scalar(select(func.count()).select_from(OutboxEvent))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            preview_command = pool_command.model_copy(update={"material_outputs": []}) if with_output else pool_command
            preview_response = await client.post(pool_api + "/posting-preview", json=preview_command.model_dump(mode="json"))
            assert preview_response.status_code == 200, preview_response.text
            assert preview_response.headers["cache-control"] == "private, no-store"
            assert preview_response.json()["basis_digest"] == pool_package["basis_digest"]
            assert preview_response.json()["command"] == pool_package["command"]
            assert preview_response.json()["confirmation_available"] is True
            assert (await client.get(pool_api + "/posting")).status_code == 404
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.organization_id == pg_book[0]
        )) == before_preview_entry_count
        assert await session.scalar(text("""
            SELECT count(*) FROM accounting.late_pool_package WHERE organization_id=:org
        """), {"org": pg_book[0]}) == before_preview_package_count
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == before_preview_outbox_count
        if with_output:
            original_confirm_output = production_output_cost_workflow.confirm_output_cost_correction

            async def reject_output(*_args, **_kwargs):
                raise service.AccountingError("Synthetic linked-output failure")

            monkeypatch.setattr(production_output_cost_workflow, "confirm_output_cost_correction", reject_output)
            with pytest.raises(service.AccountingError, match="Synthetic linked-output failure"):
                await late_pool_cost.confirm(
                    session, pg_book[0], expense.id, pool_command, uuid4(), pool_package["basis_digest"],
                    "tester", procurement, expected_digest=pool_package["posting_digest"])
            assert await session.scalar(select(func.count()).select_from(Entry)) == before
            assert await session.scalar(text("SELECT count(*) FROM accounting.late_pool_package")) == 0
            assert await session.scalar(text("SELECT count(*) FROM accounting.late_pool_inventory_value_link")) == 0
            assert await session.scalar(text("""
                SELECT entry_id FROM accounting.source_control
                WHERE organization_id=:org AND source=:source
            """), {"org": pg_book[0], "source": pool_package["posting"]["source"]}) is None
            monkeypatch.setattr(production_output_cost_workflow,
                                "confirm_output_cost_correction", original_confirm_output)
        confirmed = await late_pool_cost.confirm(
            session, pg_book[0], expense.id, pool_command, uuid4(), pool_package["basis_digest"], "tester",
            procurement, expected_digest=pool_package["posting_digest"])
        assert confirmed.operation == "inventory_late_cost"
        saved_pool = await late_pool_cost.load_package(session, pg_book[0], confirmed.id)
        assert saved_pool["preview"] == pool_package
        assert len(saved_pool["output_revisions"]) == int(with_output)
        expected_inventory_origins = {
            (row["source_entry_id"], row["source_line_id"])
            for row in pool_package["calculation"]["destinations"]
            if row["kind"] == "inventory" and Decimal(row["delta_byn"]) != 0
        }
        assert {(row["acquisition_entry_id"], row["acquisition_line_id"])
                for row in saved_pool["inventory_value_links"]} == expected_inventory_origins
        assert {row["value_entry_id"] for row in saved_pool["inventory_value_links"]} == {confirmed.id}
        historical_rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
            Entry.organization_id == pg_book[0], Line.account_code == "10.1",
        ).order_by(Entry.posting_date, Entry.id, Line.id))).all()
        verified_values = await verified_value_lines(session, pg_book[0], historical_rows, procurement)
        assert {(row["acquisition_entry_id"], row["acquisition_line_id"])
                for row in saved_pool["inventory_value_links"]} == set(verified_values.pool_origins.values())
        historical_cost = issue_result(await session.get(Policy, policy_id), historical_rows, pg_book[0],
            InventoryIssuePreviewInput(policy_id=policy_id, posting_date="2026-10-11", account="10.1",
                warehouse="Main", sku="MAT-1", lot="LOT-1", quantity="1"),
            verified_value_lines=verified_values)
        expected_remaining = sum((Decimal(row["prospective_byn"])
                                  for row in full["pools"][0]["remaining"]), Decimal())
        assert Decimal(historical_cost["book_value_byn"]) == expected_remaining
        controls = await closing_snapshot(session, pg_book[0], "2026-10")
        assert "inventory_late_cost_receipt_gap" not in {item["code"] for item in controls["review_items"]}
        reader_grant_id = (await session.scalar(select(func.max(AccessGrant.id)))) or 0
        await session.execute(text("""
            INSERT INTO accounting.access_grant (id, organization_id, subject, role)
            VALUES (:id, :organization_id, :subject, :role)
        """), {"id": reader_grant_id + 1, "organization_id": pg_book[0],
                "subject": "pool-reader", "role": "reader"})
        await session.commit()
        before_entry_count = await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.organization_id == pg_book[0]
        ))
        before_package_count = await session.scalar(text("""
            SELECT count(*) FROM accounting.late_pool_package WHERE organization_id=:org
        """), {"org": pg_book[0]})
        before_outbox_count = await session.scalar(select(func.count()).select_from(OutboxEvent))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            original_user = app.dependency_overrides[get_current_user]
            app.dependency_overrides[get_current_user] = lambda: CurrentUser("pool-reader", ["director"])
            try:
                reader_denied = await client.post(pool_api + "/confirm", headers={"X-Expected-Principal": "pool-reader"},
                    json={**saved_pool["command"], "request_key": saved_pool["request_key"],
                          "expected_basis_digest": pool_package["basis_digest"],
                          "expected_digest": pool_package["posting_digest"]})
                assert reader_denied.status_code == 403, reader_denied.text
            finally:
                app.dependency_overrides[get_current_user] = original_user
            assert await session.scalar(select(func.count()).select_from(Entry).where(
                Entry.organization_id == pg_book[0]
            )) == before_entry_count
            assert await session.scalar(text("""
                SELECT count(*) FROM accounting.late_pool_package WHERE organization_id=:org
            """), {"org": pg_book[0]}) == before_package_count
            assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == before_outbox_count
            rejected_principal = await client.post(pool_api + "/confirm", headers={"X-Expected-Principal": "other"},
                json={**saved_pool["command"], "request_key": saved_pool["request_key"],
                      "expected_basis_digest": pool_package["basis_digest"],
                      "expected_digest": pool_package["posting_digest"]})
            assert rejected_principal.status_code == 409
            assert await session.scalar(select(func.count()).select_from(Entry).where(
                Entry.organization_id == pg_book[0]
            )) == before_entry_count
            assert await session.scalar(text("""
                SELECT count(*) FROM accounting.late_pool_package WHERE organization_id=:org
            """), {"org": pg_book[0]}) == before_package_count
            assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == before_outbox_count
            retry_response = await client.post(pool_api + "/confirm", headers={"X-Expected-Principal": "tester"},
                json={**saved_pool["command"], "request_key": saved_pool["request_key"],
                      "expected_basis_digest": pool_package["basis_digest"],
                      "expected_digest": pool_package["posting_digest"]})
            assert retry_response.status_code == 201, retry_response.text
            assert retry_response.json() == saved_pool
            readback = await client.get(pool_api + "/posting")
            assert readback.status_code == 200, readback.text
            assert readback.headers["cache-control"] == "private, no-store"
            assert readback.json() == saved_pool
        # A V3 first leg has no legacy LateCostReceipt; the shared receipt
        # verifier must resolve its immutable package for historical users.
        assert (await verify_late_cost(session, pg_book[0], confirmed.id, procurement)).model_dump() == PostingInput.model_validate(
            pool_package["posting"]).model_dump()
        # A later V3 expense uses the complete saved history on the same
        # acquisition and must not recost or reject the earlier V3 value lines.
        follow_up, _ = await save_document(session, gateway, user, pg_book[0], AdditionalExpenseCreate.model_validate({
            "key": "pool-freight-follow-up", "document": {
                "invoice_reference": "pool-freight-follow-up", "document_date": "2026-10-12", "operation_date": "2026-10-12",
                "supplier": "carrier", "contract": "freight", "currency": "BYN", "amount": "1.00",
                "explanation": "Synthetic follow-up pool freight", "receipt_lines": [{
                    "receipt_id": receipts[0]["id"], "version": 1, "line_number": 1}]}}))
        follow_up_request = LateCostPreviewInput(expected_version=1, policy_id=policy_id, posting_date="2026-10-12",
            capitalizable_amount_byn="1.00", excluded_amount_byn="0.00", classification_evidence="Synthetic follow-up pool freight")
        follow_up_preview = await preview_expense(session, pg_book[0], follow_up.id, follow_up_request, procurement)
        assert follow_up_preview["inventory_method"] == method and follow_up_preview["source_version"] == 1
        if with_output:
            saved_revision, = saved_pool["output_revisions"]
            assert saved_revision["output_entry_id"] == output_id
            assert saved_revision["amount_byn"] == wip_delta
            assert await session.scalar(text("""
                SELECT entry_id FROM accounting.production_output_cost_revision WHERE id=:revision
            """), {"revision": saved_revision["output_revision_id"]}) > confirmed.id
        repeated_confirmation = await late_pool_cost.confirm(
            session, pg_book[0], expense.id, pool_command, saved_pool["request_key"],
            pool_package["basis_digest"], "tester", procurement,
            expected_digest=pool_package["posting_digest"])
        assert repeated_confirmation.id == confirmed.id
        await session.commit()
        with pytest.raises(DBAPIError, match="Cannot downgrade V3 pool history"):
            async with session.begin_nested():
                await run_migration(session, "0155_late_pool_inventory_value_links.py", "downgrade")
        # The unlinked second purchase affects weighted cost too: authenticate
        # its primary document, not merely the receipt named by the freight.
        original_basis = procurement.posted_receipt_basis
        async def changed_basis(session, organization_id, receipt_id, expected_version):
            result = await original_basis(session, organization_id, receipt_id, expected_version)
            return {**result, "digest": "0" * 64} if receipt_id == receipts[1]["id"] else result
        monkeypatch.setattr(procurement, "posted_receipt_basis", changed_basis)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            readback = await client.get(pool_api + "/posting")
            assert readback.status_code == 200, readback.text
            assert readback.json() == saved_pool
        with pytest.raises(service.AccountingError, match="authenticated primary"):
            await load_expense_pools(session, pg_book[0], expense.id, 1, date(2026, 10, 11), policy_id, procurement)


def posting_input(policy_id: int) -> ProductionMaterialIssuePostingInput:
    return ProductionMaterialIssuePostingInput.model_validate({
        "policy_id": policy_id,
        "order_id": 42,
        "order_analytics": "ORDER-42",
        "department": "SHOP",
        "wms_movement_id": 1,
        "posting_date": "2026-10-10",
        "account": "10.1",
        "warehouse": "Main",
        "sku": "MAT-1",
        "lot": "LOT-1",
        "quantity": "2.00",
    })


async def seed_book(factory, pg_book, method="specific", *, late_cost=False):
    async with factory() as session:
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.account','id'), "
            "(SELECT max(id) FROM accounting.account))"
        ))
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.policy','id'), "
            "(SELECT max(id) FROM accounting.policy))"
        ))
        session.add_all([
            Account(organization_id=pg_book[0], code="10.1", title="Synthetic raw material",
                    category="asset", valid_from=date(2026, 1, 1),
                    required_dimensions=["warehouse", "sku", "lot"], currency_tracking=False,
                    quantity_tracking=True, cash=False, normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="20", title="Synthetic WIP",
                    category="asset", valid_from=date(2026, 1, 1),
                    required_dimensions=["department", "order"], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="25", title="Synthetic overhead",
                    category="expense", valid_from=date(2026, 1, 1),
                    required_dimensions=["department"], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
        ])
        await session.flush()
        if late_cost:
            session.add(Account(organization_id=pg_book[0], code="43", title="Synthetic finished goods",
                category="asset", valid_from=date(2026, 1, 1), required_dimensions=["warehouse", "sku", "lot"],
                currency_tracking=False, quantity_tracking=True, cash=False, normative_ref="Synthetic"))
        policy = Policy(
            organization_id=pg_book[0], effective_from=date(2026, 10, 1),
            reference="Synthetic material issue policy", inventory_method=method,
            allocation_basis="direct_cost", depreciation_method="straight_line",
            normative_reference="Synthetic only", normative_verified=late_cost, approved_by="tester",
            late_cost_allocation={"basis": "quantity", "rounding": "largest_remainder_cent"} if late_cost else None,
            production_costing={
                **({"finished_goods_account": "43"} if late_cost else {}),
                "overhead_accounts": ["25"], "wip_account": "20",
                "pool_dimensions": ["department"], "order_dimension": "order",
                "rounding": "largest_remainder_cent", "reference": "Synthetic reviewed material issue",
            },
        )
        session.add(policy)
        order = ProductionOrder(number="MATERIAL-42", product="Synthetic widget", qty=2)
        session.add(order)
        session.add(StockMovement(
            organization_id=pg_book[0], sku_code="MAT-1", warehouse="Main", kind="in",
            qty="5.00", reason="receipt", batch_ref="LOT-1", doc_ref="receipt:material-1",
            note="Synthetic inventory receipt",
        ))
        await session.flush()
        await assign_order(
            session, AccountingService(), pg_book[0], CurrentUser("tester", ["director"]),
            OwnershipCommand(order_id=order.id, expected_digest=order_snapshot(order)[1],
                             evidence="Synthetic reviewed production owner"),
        )
        await session.commit()
        return policy.id, order.id


async def seed_inventory_value(factory, pg_book, policy_id):
    async with factory() as session:
        data = PostingInput(
            source="inventory:receipt:material-1", source_version=1, operation="manual",
            document_date="2026-10-01", operation_date="2026-10-01", posting_date="2026-10-01",
            policy_id=policy_id, rule_version="synthetic-receipt-v1",
            explanation="Synthetic reviewed material receipt", lines=[
                LineInput(account="10.1", side="debit", amount="31.25", quantity="5.00",
                          dimensions={"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"}),
                LineInput(account="60", side="credit", amount="31.25", dimensions={}),
            ],
        )
        row = await service.post(session, pg_book[0], data, "tester")
        await session.commit()
        return row.id


async def seed_mixed_inventory_value(factory, pg_book, policy_id):
    async with factory() as session:
        for source, quantity, day in (("material-cent", "1.00", "2026-10-01"),
                                      ("material-fraction", "3.00", "2026-10-02")):
            await service.post(session, pg_book[0], PostingInput(
                source=f"inventory:receipt:{source}", source_version=1, operation="manual",
                document_date=day, operation_date=day, posting_date=day, policy_id=policy_id,
                rule_version="synthetic-receipt-v1", explanation="Synthetic material allocation origin", lines=[
                LineInput(account="10.1", side="debit", amount="0.01", quantity=quantity,
                              dimensions={"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"}),
                    LineInput(account="60", side="credit", amount="0.01", dimensions={}),
                ]), "tester")
        await session.commit()


async def seed_zero_rounding_inventory_value(factory, pg_book, policy_id):
    async with factory() as session:
        await service.post(session, pg_book[0], PostingInput(
            source="inventory:receipt:material-zero-rounding", source_version=1, operation="inventory_purchase",
            document_date="2026-10-01", operation_date="2026-10-01", posting_date="2026-10-01",
            policy_id=policy_id, rule_version="synthetic-receipt-v1", explanation="Synthetic zero material origin", lines=[
                LineInput(account="10.1", side="debit", amount="0.01", quantity="5.00",
                          dimensions={"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"}),
                LineInput(account="60", side="credit", amount="0.01", dimensions={}),
            ]), "tester")
        await session.commit()


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
async def test_material_allocation_requires_migration(pg_factory, pg_book, method):
    policy_id, order_id = await seed_book(pg_factory, pg_book, method)
    await seed_inventory_value(pg_factory, pg_book, policy_id)
    _, movement_id, _ = await seed_physical_issue(pg_factory, pg_book, order_id)
    data = posting_input(policy_id).model_copy(update={"order_id": order_id, "wms_movement_id": movement_id})
    async with pg_factory() as session:
        await run_migration(session, "0140_zero_value_disposals.py", "upgrade")
        with pytest.raises(service.AccountingError, match="migration 0150"):
            await prepare_material_zero_issue(session, pg_book[0], "2026-10", data, SyntheticProduction())
        with pytest.raises(service.AccountingError, match="migration 0149"):
            await prepare_material_issue_posting(session, pg_book[0], "2026-10", data, SyntheticProduction())
        command = ProductionMaterialIssuePostingConfirmInput.model_validate({
            **data.model_dump(mode="json"), "basis_digest": "0" * 64, "digest": "0" * 64})
        with pytest.raises(service.AccountingError, match="migration 0149"):
            await confirm_material_issue_posting(session, pg_book[0], "2026-10", command, "tester")


async def seed_physical_issue(factory, pg_book, order_id):
    async with factory() as session:
        command = ProductionMaterialIssueCommand(
            request_id=uuid4(), order_id=order_id, expected_order_digest="0" * 64,
            operation_date="2026-10-10", sku_code="MAT-1", quantity="2.00", warehouse="Main",
            location_id=None, lot="LOT-1", evidence="Synthetic reviewed material issue",
        )
        order = await session.get(ProductionOrder, order_id)
        command = command.model_copy(update={"expected_order_digest": order_snapshot(order)[1]})
        row, movement = await record_material_issue(
            session, AccountingService(), pg_book[0], CurrentUser("tester", ["director"]), command
        )
        await session.commit()
        return row.id, movement.id, command


async def test_material_issue_posts_one_reviewed_wip_package(pg_factory, pg_book):
    policy_id, order_id = await seed_book(pg_factory, pg_book)
    await seed_inventory_value(pg_factory, pg_book, policy_id)
    _, movement_id, physical = await seed_physical_issue(pg_factory, pg_book, order_id)
    data = posting_input(policy_id).model_copy(update={"order_id": order_id, "wms_movement_id": movement_id})
    production = SyntheticProduction()

    async with pg_factory() as session:
        await run_migration(session, "0140_zero_value_disposals.py", "upgrade")
        await session.commit()
        preview = await prepare_material_issue_posting(
            session, pg_book[0], "2026-10", data, production
        )
        assert preview["status"] == "reviewed_material_cost"
        assert preview["inventory_cost"]["issue_cost_byn"] == "12.50"
        assert preview["posting_available"] is True
        confirmed = ProductionMaterialIssuePostingConfirmInput.model_validate({
            **data.model_dump(mode="json"),
            "basis_digest": preview["basis_digest"],
            "digest": preview["digest"],
        })

    async def confirm_once():
        async with pg_factory() as session:
            entry = await confirm_material_issue_posting(
                session, pg_book[0], "2026-10", confirmed, "tester"
            )
            await session.commit()
            return entry.id

    first, second = await asyncio.gather(confirm_once(), confirm_once())
    assert first == second

    async with pg_factory() as session:
        receipt = await session.get(InventoryIssueReceipt, first)
        entry = await session.get(Entry, first)
        movement = await session.get(StockMovement, movement_id)
        assert receipt is not None and entry is not None and movement is not None
        assert entry.source == f"production:material:{pg_book[0]}:{physical.request_id}"
        assert [(line.side, line.account_code, str(line.amount), line.quantity)
                for line in (await session.scalars(
                    select(Line).where(Line.entry_id == first).order_by(Line.id)
                )).all()] == [
            ("debit", "20", "12.50", None),
            ("credit", "10.1", "12.50", 2),
        ]
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.operation == "inventory_issue")) == 1
        assert await session.scalar(select(func.count()).select_from(InventoryIssueReceipt)) == 1
        verified = await verify_material_issue_receipt(session, pg_book[0], first)
        assert service.digest(verified) == entry.digest
        from modules.accounting.models import Organization

        foreign = Organization(id=9001, name="Synthetic foreign company", unp="888888888")
        session.add(foreign)
        await session.flush()
        with pytest.raises(service.AccountingError, match="unavailable in this organization"):
            await verify_material_issue_receipt(session, foreign.id, first)
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "DELETE FROM accounting.inventory_issue_receipt WHERE entry_id=:entry"
            ), {"entry": first})
        await session.rollback()


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
async def test_material_issue_persists_complete_mixed_allocation(pg_factory, pg_book, method):
    policy_id, order_id = await seed_book(pg_factory, pg_book, method)
    await seed_mixed_inventory_value(pg_factory, pg_book, policy_id)
    _, movement_id, physical = await seed_physical_issue(pg_factory, pg_book, order_id)
    data = posting_input(policy_id).model_copy(update={"order_id": order_id, "wms_movement_id": movement_id})
    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py",
                         "0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py",
                         "0146_zero_value_allocation_basis.py", "0147_zero_value_allocation_runtime.py",
                         "0148_zero_value_allocated_sales.py", "0149_production_material_allocations.py"):
            await run_migration(session, revision, "upgrade")
        await session.commit()
        preview = await prepare_material_issue_posting(session, pg_book[0], "2026-10", data, SyntheticProduction())
        cost = preview["inventory_cost"]
        assert cost["source_allocation_version"] == 1
        assert len(cost["inventory_layers"]) == 2
        assert sum(Decimal(layer["quantity"]) for layer in cost["inventory_layers"]) == Decimal("2")
        assert [layer["amount_byn"] for layer in cost["inventory_layers"]] == ["0.01", "0.00"]
        assert preview["basis_digest"] == cost["basis_digest"]
        confirmed = ProductionMaterialIssuePostingConfirmInput.model_validate({
            **data.model_dump(mode="json"), "basis_digest": preview["basis_digest"], "digest": preview["digest"],
        })
        entry = await confirm_material_issue_posting(session, pg_book[0], "2026-10", confirmed, "tester")
        assert (await confirm_material_issue_posting(session, pg_book[0], "2026-10", confirmed, "tester")).id == entry.id
        receipt = await session.get(InventoryIssueReceipt, entry.id)
        assert receipt.cost["source_allocation_version"] == 1
        lines = (await session.scalars(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))).all()
        assert [(line.side, line.account_code, str(line.amount)) for line in lines] == [
            ("debit", "20", "0.01"), ("credit", "10.1", "0.01"),
        ]
        assert physical.lot == "LOT-1"
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        with pytest.raises(DBAPIError, match="Cannot downgrade complete material allocation history"):
            async with session.begin_nested():
                await run_migration(session, "0149_production_material_allocations.py", "downgrade")


async def test_second_reviewed_material_issue_accepts_prior_production_issue_movement(pg_factory, pg_book, monkeypatch):
    """A real prior production issue is physical history, not an unclassified movement."""
    from fastapi import HTTPException

    from modules.wms import routes as wms_routes

    policy_id, order_id = await seed_book(pg_factory, pg_book)
    await seed_inventory_value(pg_factory, pg_book, policy_id)
    _, _, first = await seed_physical_issue(pg_factory, pg_book, order_id)
    second = first.model_copy(update={"request_id": uuid4()})
    original_reasons = wms_routes._INVENTORY_PHYSICAL_REASONS

    monkeypatch.setattr(wms_routes, "_INVENTORY_PHYSICAL_REASONS",
                        original_reasons - {"production_issue"})
    async with pg_factory() as session:
        with pytest.raises(HTTPException, match="неразобранное движение"):
            await record_material_issue(
                session, AccountingService(), pg_book[0], CurrentUser("tester", ["director"]), second)
        await session.rollback()

    monkeypatch.setattr(wms_routes, "_INVENTORY_PHYSICAL_REASONS",
                        original_reasons)
    async with pg_factory() as session:
        binding, movement = await record_material_issue(
            session, AccountingService(), pg_book[0], CurrentUser("tester", ["director"]), second)
        replay, replay_movement = await record_material_issue(
            session, AccountingService(), pg_book[0], CurrentUser("tester", ["director"]), second)
        await session.commit()
        assert binding.request_key == str(second.request_id)
        assert movement.reason == "production_issue" and movement.kind == "out"
        assert replay.id == binding.id and replay_movement.id == movement.id


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
async def test_material_zero_rounding_receipt_is_entryless_and_retries(pg_factory, pg_book, method):
    policy_id, order_id = await seed_book(pg_factory, pg_book, method)
    await seed_zero_rounding_inventory_value(pg_factory, pg_book, policy_id)
    _, movement_id, _ = await seed_physical_issue(pg_factory, pg_book, order_id)
    data = posting_input(policy_id).model_copy(update={"order_id": order_id, "wms_movement_id": movement_id})
    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py",
                         "0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py",
                         "0146_zero_value_allocation_basis.py", "0147_zero_value_allocation_runtime.py",
                         "0148_zero_value_allocated_sales.py", "0149_production_material_allocations.py",
                         "0150_zero_material_allocations.py"):
            await run_migration(session, revision, "upgrade")
        await session.commit()
        prepared = await prepare_material_zero_issue(session, pg_book[0], "2026-10", data, SyntheticProduction())
        assert prepared["inventory_cost"]["issue_cost_byn"] == "0.00"
        command = prepared["zero_value_receipt"]
        assert command["command_version"] == 5 and len(command["inventory_layers"]) == 1
        import json
        for field, value in (("destination_account", "10.1"), ("operation_date", "2026-10-02")):
            forged = {**command, field: value}
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.scalar(text(
                        "SELECT accounting.zero_value_material_allocation_basis(:org, CAST(:command AS jsonb), 2147483647)"
                    ), {"org": pg_book[0], "command": json.dumps(forged)})
        for field, value in (("binding_id", str(command["material_binding"]["binding_id"])), ("quantity", 2)):
            forged = {**command, "material_binding": {**command["material_binding"], field: value}}
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.scalar(text(
                        "SELECT accounting.zero_value_material_allocation_basis(:org, CAST(:command AS jsonb), 2147483647)"
                    ), {"org": pg_book[0], "command": json.dumps(forged)})
        confirmed = ProductionMaterialIssuePostingConfirmInput.model_validate({
            **data.model_dump(mode="json"), "basis_digest": prepared["basis_digest"],
            "digest": service.digest(ProductionMaterialZeroValueDisposalCommand.model_validate(command)),
        })
        await session.rollback()
        from httpx import ASGITransport, AsyncClient

        from tests.accounting.test_inventory_allocation_api_postgres import application
        app = application(pg_factory)
        app.state.core.services.production_output = SyntheticProduction()
        base = f"/accounting/organizations/{pg_book[0]}/periods/2026-10"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            preview = await client.post(base + "/production-material-issue-posting-preview", json=data.model_dump(mode="json"))
            assert preview.status_code == 200, preview.text
            assert preview.json()["zero_value"] is True and preview.json()["digest"] == confirmed.digest
            response = await client.post(base + "/production-material-issue-confirm",
                json={**confirmed.model_dump(mode="json"), "zero_value": True})
            assert response.status_code == 201, response.text
            first = response.json()
            altered = await client.post(base + "/production-material-issue-confirm",
                json={**confirmed.model_dump(mode="json"), "zero_value": True, "quantity": "1.00"})
            assert altered.status_code == 409, altered.text
            foreign = await client.get(
                f"/accounting/organizations/{pg_book[0]+1000}/periods/2026-10/production-material-issue-posting-status/{movement_id}")
            assert foreign.status_code in {403, 404}, foreign.text

        raw_command = json.dumps(command).replace(
            f'"binding_id": {command["material_binding"]["binding_id"]}',
            f'"binding_id": {command["material_binding"]["binding_id"]}e0',
        )
        with pytest.raises(DBAPIError, match="canonical JSON integer tokens"):
            async with session.begin_nested():
                await session.execute(text("""
                    INSERT INTO accounting.inventory_zero_value_disposal_receipt
                    (organization_id,source,source_version,operation,entry_id,posting_date,policy_id,
                     command,basis_digest,digest,actor)
                    SELECT organization_id,source,source_version,operation,entry_id,posting_date,policy_id,
                           CAST(:command AS json),basis_digest,digest,actor
                    FROM accounting.inventory_zero_value_disposal_receipt WHERE id=:id
                """), {"command": raw_command, "id": first["receipt_id"]})
        second = await confirm_material_zero_issue(session, pg_book[0], "2026-10", confirmed, "tester", SyntheticProduction())
        assert first["receipt_id"] == second["receipt_id"] and first["entry_id"] is None
        receipt = await session.get(ZeroValueInventoryDisposalReceipt, first["receipt_id"])
        assert receipt is not None and receipt.entry_id is None
        await session.commit()
        with pytest.raises(DBAPIError, match="Cannot downgrade V5"):
            async with session.begin_nested():
                await run_migration(session, "0150_zero_material_allocations.py", "downgrade")
        await session.rollback()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(base + "/production-material-issue-confirm",
                json={**confirmed.model_dump(mode="json"), "zero_value": True})
            assert response.status_code == 201, response.text
            assert response.json()["receipt_id"] == first["receipt_id"]
            response = await client.get(base + f"/production-material-issue-posting-status/{movement_id}")
            assert response.status_code == 200, response.text
            assert response.json()["entry_id"] is None and response.json()["quantity_registered"] is True
            assert response.json()["digest"] == confirmed.digest
            assert response.json()["posted"] is False

@pytest.mark.parametrize("with_output,with_sale", [(False, False), (True, False), (True, True)])
async def test_purchased_material_late_expense_authenticates_production_history(pg_factory, pg_book, with_output, with_sale, monkeypatch):
    from modules.accounting.late_cost_sources import expense_history
    from modules.procurement.additional_expenses import AdditionalExpenseCreate, save_document
    from modules.procurement.receipt_documents import (
        ReceiptAccounts,
        ReceiptConfirm,
        ReceiptCreate,
        confirm_receipt,
        create_document,
        preview_document,
    )
    from modules.procurement.source_gateway import ProcurementSourceService

    policy_id, order_id = await seed_book(pg_factory, pg_book, late_cost=True)
    gateway, procurement = AccountingService(), ProcurementSourceService()
    user = CurrentUser("tester", ["director"])
    async with pg_factory() as session:
        await run_migration(session, "0140_zero_value_disposals.py", "upgrade")
        primary = ReceiptCreate.model_validate({"key": "material-late-origin", "document": {
            "currency": "BYN", "invoice_reference": "material-late-origin",
            "document_date": "2026-10-01", "operation_date": "2026-10-01",
            "supplier": "supplier", "contract": "contract", "warehouse": "Main",
            "explanation": "Synthetic purchased materials", "items": [{
                "sku": "MAT-1", "lot": "LOT-1", "quantity": "5", "net_amount": "31.25",
                "vat_rate": "0", "vat_amount": "0", "vat_basis": "Synthetic"}]}})
        receipt = await create_document(pg_book[0], primary, (session, "tester"), (session, gateway, user))
        options = ReceiptAccounts(expected_version=1, posting_date="2026-10-01", policy_id=policy_id,
                                  settlement_account="60", vat_account=None, inventory_accounts=["10.1"])
        prepared = await preview_document(pg_book[0], receipt["id"], options, (session, gateway, user))
        await confirm_receipt(session, pg_book[0], receipt["id"], ReceiptConfirm.model_validate({
            **options.model_dump(mode="json"), "digest": prepared["digest"]}), user, gateway, None)
        await session.commit()
    _, movement_id, _ = await seed_physical_issue(pg_factory, pg_book, order_id)
    data = posting_input(policy_id).model_copy(update={"order_id": order_id, "wms_movement_id": movement_id})
    async with pg_factory() as session:
        prepared = await prepare_material_issue_posting(
            session, pg_book[0], "2026-10", data, SyntheticProduction(), procurement=procurement)
        material = await confirm_material_issue_posting(session, pg_book[0], "2026-10",
            ProductionMaterialIssuePostingConfirmInput.model_validate({**data.model_dump(mode="json"),
                "basis_digest": prepared["basis_digest"], "digest": prepared["digest"]}),
            "tester", procurement=procurement)
        expense, _ = await save_document(session, gateway, user, pg_book[0], AdditionalExpenseCreate.model_validate({
            "key": "material-late-freight", "document": {
                "invoice_reference": "freight", "document_date": "2026-10-11", "operation_date": "2026-10-11",
                "supplier": "carrier", "contract": "freight", "currency": "BYN", "amount": "5.00",
                "explanation": "Synthetic late freight", "receipt_lines": [{
                    "receipt_id": receipt["id"], "version": 1, "line_number": 1}]}}))
        await session.commit()
        history = await expense_history(session, pg_book[0], expense.id, 1, date(2026, 10, 11), procurement)
        lot = history["lots"][0]
        assert Decimal(lot["received_quantity"]) == 5
        assert Decimal(lot["remaining_quantity"]) == 3
        assert Decimal(lot["production_quantity"]) == 2
        assert Decimal(lot["disposed_quantity"]) == 0
        assert lot["production_disposals"][0]["entry_id"] == material.id
        assert lot["production_disposals"][0]["expense_account"] == "20"
        replay = await expense_history(session, pg_book[0], expense.id, 1, date(2026, 10, 11), procurement)
        assert replay == history
        from modules.accounting.late_cost_pool import load_expense_pools

        original_pool = await load_expense_pools(session, pg_book[0], expense.id, 1,
            date(2026, 10, 31), policy_id, procurement)
        from modules.accounting.late_cost_posting import ExpenseAccounts
        from modules.accounting.late_cost_receipts import LateCostCommand, MaterialLateCostCommand
        from modules.accounting.late_material_cost import prepare as prepare_package
        from modules.accounting.schemas import LateCostPreviewInput

        output_id = None
        if with_output:
            from pathlib import Path

            from modules.accounting.production_output_transfer import (
                ProductionOutputTransferConfirmInput,
                confirm_output_transfer,
                prepare_output_transfer,
            )
            from tests.accounting.test_production_output_transfer_postgres import (
                SyntheticProduction as OutputProduction,
            )
            from tests.accounting.test_production_output_transfer_postgres import (
                transfer_input,
            )

            for path in sorted(Path("migrations/versions").glob("*.py")):
                if "0141" <= path.name[:4] <= "0151":
                    await run_migration(session, path.name, "upgrade")
            output_data = transfer_input(policy_id).model_copy(update={"order_id": order_id})
            output_preview = await prepare_output_transfer(session, pg_book[0], "2026-10", output_data, OutputProduction(), object())
            output = await confirm_output_transfer(session, pg_book[0], "2026-10",
                ProductionOutputTransferConfirmInput.model_validate({**output_data.model_dump(mode="json"),
                    "basis_digest": output_preview["basis_digest"], "digest": output_preview["digest"]}),
                "tester", production=OutputProduction(), warehouse_gateway=object())
            output_id = output.id
            await session.commit()
            if with_sale:
                from modules.accounting import sales

                sale = sales.SaleDocument(source="material-output-sale", source_version=1,
                    document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
                    policy_id=policy_id, account="43", warehouse="Main", sku="SYN-WIDGET", lot="LOT-1",
                    quantity="1", expense_account="90.4", expense_dimensions={}, explanation="Synthetic sale",
                    net_amount="20.00", vat_rate="0", vat_basis="Synthetic", buyer_account="62",
                    revenue_account="90.1", vat_revenue_account="90.2", vat_payable_account="68",
                    buyer_dimensions={"counterparty": "buyer", "contract": "contract", "settlement_document": "sale-1"})
                sale_preview = await sales.prepare(session, pg_book[0], sale)
                await sales.confirm(session, pg_book[0], sale, sale_preview["cost"]["basis_digest"], sale_preview["digest"], "tester")
                await session.commit()

        command = LateCostCommand(allocation=LateCostPreviewInput(expected_version=1, policy_id=policy_id,
            posting_date="2026-10-31", capitalizable_amount_byn="5.00", excluded_amount_byn="0.00",
            classification_evidence="Synthetic reviewed material freight"), accounts=ExpenseAccounts(settlement_account="60"))
        session.add(Account(organization_id=pg_book[0], code="60.99", title="Invalid settlement role",
            category="income", valid_from=date(2026, 1, 1), required_dimensions=[],
            currency_tracking=False, quantity_tracking=False, cash=False, normative_ref="Synthetic"))
        await session.flush()
        invalid_role = LateCostCommand(allocation=command.allocation,
            accounts=ExpenseAccounts(settlement_account="60.99"))
        with pytest.raises(service.AccountingError, match="account role or quantity tracking"):
            await prepare_package(session, pg_book[0], expense.id, invalid_role, procurement)
        before_count = await session.scalar(select(func.count()).select_from(Entry))
        package = await prepare_package(session, pg_book[0], expense.id, command, procurement)
        if with_output:
            assert package["wip_origins"] == []
            assert package["outputs"][0]["output_entry_id"] == output_id
            assert package["outputs"][0]["amount_byn"] == "2.00"
        else:
            assert package["outputs"] == []
            assert package["wip_origins"][0]["order_id"] == order_id
            assert package["wip_origins"][0]["amount_byn"] == "2.00"
        assert [(line["account"], line["amount"]) for line in package["posting"]["lines"]] == [
            ("10.1", "3.00"), ("20", "2.00"), ("60", "5.00")]
        assert await session.scalar(select(func.count()).select_from(Entry)) == before_count
        forged = MaterialLateCostCommand(allocation=command.allocation, accounts=command.accounts,
            material_outputs=[{"output_entry_id": material.id, "amount_byn": "2.00"}])
        with pytest.raises(service.AccountingError, match="Selected outputs differ"):
            await prepare_package(session, pg_book[0], expense.id, forged, procurement)
        from modules.accounting.late_material_cost import confirm as confirm_package

        if not with_output:
            from pathlib import Path

            for path in sorted(Path("migrations/versions").glob("*.py")):
                if "0141" <= path.name[:4] <= "0151":
                    await run_migration(session, path.name, "upgrade")
        reviewed = MaterialLateCostCommand.model_validate(package["command"])
        request_key = uuid4()
        from httpx import ASGITransport, AsyncClient

        from tests.accounting.test_inventory_allocation_api_postgres import application

        await session.commit()
        app = application(pg_factory)
        app.state.core.services.procurement_source = procurement
        api_base = f"/accounting/organizations/{pg_book[0]}/additional-expenses/{expense.id}/material"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(api_base + "/posting-preview", json=command.model_dump(mode="json"))
            assert response.status_code == 200, response.text
            assert response.json()["basis_digest"] == package["basis_digest"]
            assert response.json()["command"] == package["command"]
            assert response.json()["confirmation_available"] is True
            assert response.json()["principal"] == "tester"
            assert (await client.get(api_base + "/posting")).status_code == 404
        import json
        from copy import deepcopy

        from modules.accounting.models import LateCostReceipt

        for attack in ("missing_package", "legacy_marker", "empty_origins"):
            forged_command = reviewed.model_dump(mode="json")
            forged_calculation = deepcopy(package["calculation"])
            forged_preview = deepcopy(package)
            if attack == "legacy_marker":
                forged_command.pop("command_version")
                forged_command.pop("material_outputs")
            if attack == "empty_origins":
                forged_command["material_outputs"] = []
                forged_calculation["shares"] = []
                forged_preview.update(command=forged_command, calculation=forged_calculation, outputs=[])
            with pytest.raises(DBAPIError, match="package evidence is incomplete|requires versioned command|origins differ from actual WIP"):
                async with session.begin_nested():
                    orphan = await service.post(session, pg_book[0], PostingInput.model_validate(package["posting"]), "tester", late_cost=True)
                    session.add(LateCostReceipt(entry_id=orphan.id, organization_id=pg_book[0], expense_id=expense.id,
                        source_version=1, request_key=str(uuid4()), command=forged_command,
                        calculation=forged_calculation, posting=package["posting"], digest=package["posting_digest"], actor="tester"))
                    await session.flush()
                    await session.execute(text("UPDATE accounting.source_control SET entry_id=:entry WHERE organization_id=:org AND source=:source"),
                        {"entry": orphan.id, "org": pg_book[0], "source": f"procurement:additional-expense:{expense.id}"})
                    if attack == "empty_origins":
                        await session.execute(text("INSERT INTO accounting.late_material_package(late_entry_id,organization_id,basis_digest,preview) VALUES (:entry,:org,:basis,CAST(:preview AS jsonb))"),
                            {"entry": orphan.id, "org": pg_book[0], "basis": package["basis_digest"], "preview": json.dumps(forged_preview)})
                    await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        if with_output:
            from modules.accounting import production_output_cost_workflow

            async def fail_revision(*args, **kwargs):
                raise RuntimeError("Injected output revision failure")

            baseline_entries = await session.scalar(select(func.count()).select_from(Entry))
            with monkeypatch.context() as patch:
                patch.setattr(production_output_cost_workflow, "confirm_output_cost_correction", fail_revision)
                with pytest.raises(RuntimeError, match="Injected output revision failure"):
                    await confirm_package(session, pg_book[0], expense.id, reviewed, request_key,
                        package["basis_digest"], "tester", procurement)
            assert await session.scalar(select(func.count()).select_from(Entry)) == baseline_entries
            assert await session.scalar(text("SELECT count(*) FROM accounting.late_material_package")) == 0
            assert await session.scalar(text("SELECT count(*) FROM accounting.late_cost_receipt")) == 0
            assert await session.scalar(text("SELECT entry_id FROM accounting.source_control WHERE organization_id=:org AND source=:source"),
                {"org": pg_book[0], "source": f"procurement:additional-expense:{expense.id}"}) is None
        if with_output:
            import asyncio

            expense_id = expense.id
            await session.commit()
            ready = asyncio.Event()

            async def competing_confirmation(key):
                async with pg_factory() as competing:
                    await ready.wait()
                    result = await confirm_package(competing, pg_book[0], expense_id, reviewed, key,
                        package["basis_digest"], "tester", procurement)
                    await competing.commit()
                    return result.entry_id, key

            contenders = [asyncio.create_task(competing_confirmation(key)) for key in
                (request_key, uuid4() if with_sale else request_key)]
            ready.set()
            outcomes = await asyncio.wait_for(asyncio.gather(*contenders, return_exceptions=True), timeout=30)
            successes = [outcome for outcome in outcomes if isinstance(outcome, tuple)]
            failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
            assert len(successes) == (1 if with_sale else 2), outcomes
            assert len({outcome[0] for outcome in successes}) == 1
            if with_sale:
                assert len(failures) == 1
                assert isinstance(failures[0], service.AccountingError)
                assert "conflicts with the saved package" in str(failures[0])
            else:
                assert failures == []
            saved_entry_id, request_key = successes[0]
        else:
            await session.commit()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(api_base + "/confirm", json={**reviewed.model_dump(mode="json"),
                    "request_key": str(request_key), "expected_basis_digest": package["basis_digest"],
                    "expected_digest": package["posting_digest"]}, headers={"X-Expected-Principal": "tester"})
                assert response.status_code == 201, response.text
                saved_entry_id = response.json()["entry_id"]
        repeated = await confirm_package(session, pg_book[0], expense.id, reviewed, request_key,
            package["basis_digest"], "tester", procurement)
        assert repeated.entry_id == saved_entry_id
        from modules.accounting.late_material_cost import load_package

        persisted = await load_package(session, pg_book[0], saved_entry_id, procurement)
        historical_pool = await load_expense_pools(session, pg_book[0], expense.id, 1,
            date(2026, 10, 31), policy_id, procurement, before_entry_id=saved_entry_id)
        assert historical_pool["basis_digest"] == original_pool["basis_digest"]
        with pytest.raises(service.AccountingError, match="exact expense"):
            await load_expense_pools(session, pg_book[0], expense.id, 1,
                date(2026, 10, 31), policy_id, procurement, before_entry_id=material.id)
        assert (await gateway.additional_expense_status(session, pg_book[0], user, expense.id))["command_version"] == 2
        assert persisted["preview"] == package
        assert persisted["command"] == reviewed.model_dump(mode="json")
        assert persisted["posted"] is True
        assert len(persisted["output_revisions"]) == int(with_output)
        await session.commit()
        path = f"/accounting/organizations/{pg_book[0]}/additional-expenses/{expense.id}/material/posting"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(path)
            assert response.status_code == 200, response.text
            assert response.json() == persisted
            assert response.headers["cache-control"] == "private, no-store"
            denied = await client.get(path.replace(f"/organizations/{pg_book[0]}/", f"/organizations/{pg_book[0]+999}/"))
            assert denied.status_code == 403, denied.text
            http_command = {**reviewed.model_dump(mode="json"), "request_key": str(request_key),
                "expected_digest": package["posting_digest"], "expected_basis_digest": package["basis_digest"]}
            assert (await client.post(api_base + "/confirm", json=http_command)).status_code == 422
            assert (await client.post(api_base + "/confirm", json=http_command,
                headers={"X-Expected-Principal": "other"})).status_code == 409
            assert (await client.post(api_base + "/confirm", json={**http_command, "expected_basis_digest": "0" * 64},
                headers={"X-Expected-Principal": "tester"})).status_code == 409
            response = await client.post(api_base + "/confirm", json=http_command,
                headers={"X-Expected-Principal": "tester"})
            assert response.status_code == 201, response.text
            assert response.json() == persisted
        if with_output:
            assert persisted["output_revisions"][0]["output_entry_id"] == output_id
            assert persisted["output_revisions"][0]["amount_byn"] == "2.00"
        with pytest.raises(DBAPIError, match="Cannot downgrade late material packages with history"):
            async with session.begin_nested():
                await run_migration(session, "0151_late_material_output_cost.py", "downgrade")
        assert await session.scalar(text("SELECT count(*) FROM accounting.late_material_package")) == 1
        assert await session.scalar(text("SELECT count(*) FROM accounting.late_material_output_cost_link")) == int(with_output)
        balances = dict((await session.execute(text("""SELECT account_code,
            sum(CASE WHEN side='debit' THEN amount ELSE -amount END)
            FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id
            WHERE e.organization_id=:org AND account_code IN ('10.1','20','43','90.4') GROUP BY account_code"""),
            {"org": pg_book[0]})).all())
        assert balances["10.1"] == Decimal("21.75")
        assert balances["20"] == (Decimal("0") if with_output else Decimal("14.50"))
        if with_output:
            assert balances["43"] == Decimal("7.25" if with_sale else "14.50")
        if with_sale:
            assert balances["90.4"] == Decimal("7.25")
        if with_output:
            from modules.accounting.schemas import CloseInput

            # Synthetic verified policy exercises the real period lifecycle;
            # it does not assert approval of a legal accounting policy.
            await session.commit()
            for closing_month in ("2026-09", "2026-10"):
                closing_period = await service.period_for(session, pg_book[0], closing_month)
                await service.close_period(session, pg_book[0], closing_month, CloseInput(
                    expected_generation=closing_period.generation,
                    evidence={step: "Synthetic material package reconciliation" for step in service.CLOSE_STEPS}),
                    "tester")
                await session.commit()
            closed_count = await session.scalar(select(func.count()).select_from(Entry))
            historical = await confirm_package(session, pg_book[0], expense.id, reviewed, request_key,
                package["basis_digest"], "tester", procurement)
            assert historical.entry_id == saved_entry_id
            assert await load_package(session, pg_book[0], saved_entry_id, procurement) == persisted
            with pytest.raises(service.AccountingError, match="[Cc]losed"):
                await prepare_package(session, pg_book[0], expense.id, reviewed, procurement)
            assert await session.scalar(select(func.count()).select_from(Entry)) == closed_count
