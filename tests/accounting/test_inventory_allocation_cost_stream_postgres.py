"""The late-cost input keeps zero portions and their real source identities."""
# ruff: noqa: F811
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import inventory_issues, sales, service
from modules.accounting.inventory_allocation_loader import load_authenticated_inventory_dispositions
from modules.accounting.production_output_cost_workflow import (
    ProductionOutputCostConfirmInput,
    ProductionOutputCostPreviewInput,
    confirm_output_cost_correction,
    preview_output_cost_correction,
)
from modules.accounting.production_output_transfer import (
    ProductionOutputTransferConfirmInput,
    confirm_output_transfer,
    prepare_output_transfer,
)
from modules.accounting.schemas import (
    InventoryIssueDocument,
    LineInput,
    PostingInput,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_production_output_transfer_postgres import (
    _seed_production_book,
    _seed_wip,
    transfer_input,
)
from tests.accounting.test_zero_value_output_cost_postgres import run_migration
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401

pytestmark = pytest.mark.integration


async def production_output_sources(factory, book, *, api, method="weighted_average", same_lot=False):
    """Two accepted physical outputs, each transferred at one cent."""
    from core.domain.models import Sku
    from core.services.auth import CurrentUser
    from modules.accounting.gateway import AccountingService
    from modules.production.accounting_ownership import (
        OwnershipCommand,
        assign_order,
        order_snapshot,
    )
    from modules.production.models import ProductionOrder
    from modules.production.output_documents import OutputCommand, confirm_output, prepare_output
    from modules.wms.models import Location, Receipt, ReceiptLine, WarehouseDirectory

    policy_id = await _seed_production_book(factory, book, method)
    await _seed_wip(factory, book, policy_id, [("SHOP", "ORDER-42", "0.01"), ("SHOP", "ORDER-43", "0.01")])
    api.headers["X-User"] = "tester"
    core = api._transport.app.state.core
    production, warehouse = core.services.production_output, core.services.wms_reservations
    gateway, user = AccountingService(), CurrentUser("tester", ["director"])
    documents = {}
    async with factory() as session:
        orders = [ProductionOrder(id=order_id, number=f"SYN-{order_id}", product="Synthetic widget", qty=2)
                  for order_id in (42, 43)]
        place = Location(warehouse="Main", code="SYN-OUTPUT")
        session.add_all([*orders, place, Sku(code="SYN-WIDGET", title="Synthetic widget", unit="шт"),
                         WarehouseDirectory(id=42, organization_id=book[0], name="Main",
                             title="Synthetic output warehouse", wms_enabled=False,
                             prohibit_negative_stock=True, is_active=True, created_by="tester")])
        await session.flush()
        for order in orders:
            digest = order_snapshot(order)[1]
            await assign_order(session, gateway, book[0], user, OwnershipCommand(
                order_id=order.id, expected_digest=digest, evidence="Synthetic reviewed owner"))
            document = await prepare_output(session, gateway, book[0], user, OutputCommand(
                request_id=uuid4(), order_id=order.id, expected_order_digest=digest,
                operation_date="2026-10-10", sku_code="SYN-WIDGET", quantity="2.00", warehouse="Main",
                location_id=place.id, lot="SHARED" if same_lot else f"LOT-{order.id}",
                evidence="Synthetic reviewed output"), warehouse_gateway=warehouse)
            await confirm_output(session, gateway, book[0], user, document.id, document.digest,
                                 warehouse_gateway=warehouse)
            documents[order.id] = document.id
        await session.commit()
    assert await core.event_bus.relay_pending(factory, core.services, event_types=("production.output.confirmed",)) == 2
    async with factory() as session:
        rows = (await session.execute(select(Receipt.id, ReceiptLine.id).join(
            ReceiptLine, ReceiptLine.receipt_id == Receipt.id).where(
                Receipt.organization_id == book[0],
                Receipt.entity_ref.in_([f"production_output:{doc_id}" for doc_id in documents.values()])))).all()
        assert len(rows) == 2
    for receipt_id, line_id in rows:
        path = f"/wms/receipts/{receipt_id}"
        detail = await api.get(path)
        assert detail.status_code == 200, detail.text
        qc = await api.post(path + "/qc", json={"expected_revision": detail.json()["qc_revision"], "decisions": [
            {"line_id": line_id, "accepted_qty": "2.00", "rejected_qty": "0.00", "reject_reason": "Synthetic accepted output"}]})
        assert qc.status_code == 200, qc.text
        accepted = await api.post(path + "/accept")
        assert accepted.status_code == 200, accepted.text
    output_ids = []
    async with factory() as session:
        for order_id in (42, 43):
            command = transfer_input(policy_id).model_copy(update={
                "order_id": order_id, "analytical_order": f"ORDER-{order_id}", "output_document_ids": [documents[order_id]]})
            preview = await prepare_output_transfer(session, book[0], "2026-10", command, production, warehouse)
            confirmation = ProductionOutputTransferConfirmInput.model_validate({
                **command.model_dump(mode="json"), "basis_digest": preview["basis_digest"], "digest": preview["digest"]})
            output = await confirm_output_transfer(session, book[0], "2026-10", confirmation, "tester",
                                                    production=production, warehouse_gateway=warehouse)
            output_ids.append(output.id)
        await session.commit()
    return policy_id, output_ids


async def mixed_production_disposal(factory, book, *, api, method="weighted_average", same_lot=False, sale=False):
    """Two real 2-unit outputs at one cent each, followed by a 2.1-unit disposal."""
    from core.domain.models import Sku
    from modules.wms.models import WarehouseDirectory

    policy_id, output_ids = await production_output_sources(
        factory, book, api=api, method=method, same_lot=same_lot)
    async with factory() as session:
        warehouse_row = (await session.scalars(select(WarehouseDirectory).where(
            WarehouseDirectory.organization_id == book[0], WarehouseDirectory.name == "Main",
            WarehouseDirectory.is_active.is_(True)))).one()
        sku_row = (await session.scalars(select(Sku).where(
            Sku.code == "SYN-WIDGET", Sku.is_active.is_(True)))).one()
        document = InventoryIssueDocument(source="mixed-output-issue", source_version=1,
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            account="43", warehouse="Main", sku="SYN-WIDGET", lot="", quantity="2.1", expense_account="90.4",
            expense_dimensions={}, explanation="Reviewed mixed output disposal",
            warehouse_identity={"id": warehouse_row.id, "name": warehouse_row.name, "title": warehouse_row.title},
            sku_identity={"id": sku_row.id, "code": sku_row.code, "title": sku_row.title, "unit": sku_row.unit})
        if sale:
            document = sales.SaleDocument(**document.model_dump(), net_amount="10.00", vat_rate="0",
                vat_basis="Synthetic exemption", buyer_account="62", revenue_account="90.1",
                vat_revenue_account="90.2", vat_payable_account="68",
                buyer_dimensions={"counterparty": "BUYER", "contract": "CONTRACT", "settlement_document": "INVOICE"})
            await inventory_issues.verify_inventory_identity(session, book[0], document)
            prepared = await sales.prepare(session, book[0], document, source_allocations=True)
            cost = prepared["cost"]
        else:
            cost, package = await inventory_issues.prepare(session, book[0], document,
                source_allocations=True, require_current_inventory=True)
        assert [layer["amount_byn"] for layer in cost["inventory_layers"]] == ["0.01", "0.00"]
        if sale:
            entry = await sales.confirm(session, book[0], document, cost["basis_digest"], prepared["digest"],
                                        "tester", source_allocations=True)
        else:
            entry = await inventory_issues.confirm(session, book[0], document, cost["basis_digest"],
                service.digest(package), "tester", source_allocations=True, require_current_inventory=True)
        await session.commit()
        events = await load_authenticated_inventory_dispositions(session, book[0])
        assert len(events) == 1
        assert events[0].allocation.quantity == Decimal("2.1")
    return policy_id, output_ids, entry.id


@pytest.mark.parametrize("same_lot", [False, True])
@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_fifo_late_cost_uses_exact_output_source_including_zero_portion(pg_factory, pg_book, same_lot, issuance_pg):
    policy_id, outputs, issue_id = await mixed_production_disposal(pg_factory, pg_book, api=issuance_pg[0], method="fifo", same_lot=same_lot)
    async with pg_factory() as session:
        await service.post(session, pg_book[0], PostingInput(source="fifo-late-wip", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic", explanation="Late WIP by exact output", lines=[
                LineInput(account="20", side="debit", amount="100", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="20", side="debit", amount="100", dimensions={"department": "SHOP", "order": "ORDER-43"}),
                LineInput(account="60", side="credit", amount="200")]), "tester")
        for index, output in enumerate(outputs):
            command = ProductionOutputCostPreviewInput(original_entry_id=output, posting_date="2026-10-31",
                                                       request_evidence="FIFO source exact correction")
            preview = await preview_output_cost_correction(session, pg_book[0], "2026-10", command)
            disposal = preview["trace"]["disposals"]
            assert len(disposal) == 1
            assert disposal[0]["entry_id"] == issue_id and disposal[0]["source_entry_id"] == output
            allocation = preview["ledger_evidence"]["allocation"]
            disposed = next(row for row in allocation if row["key"].startswith("allocation:"))
            remaining = next(row for row in allocation if row["key"] == "remaining")
            assert Decimal(str(disposed["quantity"])) == (Decimal("2") if index == 0 else Decimal("0.1"))
            assert Decimal(str(disposed["delta"])) == (Decimal("100") if index == 0 else Decimal("5"))
            assert Decimal(str(remaining["delta"])) == (Decimal("0") if index == 0 else Decimal("95"))
            await confirm_output_cost_correction(session, pg_book[0], "2026-10",
                ProductionOutputCostConfirmInput(**command.model_dump(), request_key=uuid4(), basis_digest=preview["basis_digest"]), "tester")
            await session.commit()
        unchanged = await preview_output_cost_correction(session, pg_book[0], "2026-10", command)
        assert unchanged["ledger_evidence"]["matrix"] == []


@pytest.mark.parametrize("sale", [False, True])
@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_mixed_production_late_cost_confirm_replay_and_historical_cutoff(pg_factory, pg_book, sale, issuance_pg):
    policy_id, output_ids, issue_id = await mixed_production_disposal(pg_factory, pg_book, api=issuance_pg[0], sale=sale)
    async with pg_factory() as session:
        late = PostingInput(source="mixed-late-wip", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic", explanation="Reviewed late WIP", lines=[
                LineInput(account="20", side="debit", amount="100", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="100")])
        await service.post(session, pg_book[0], late, "tester")
        command = ProductionOutputCostPreviewInput(original_entry_id=output_ids[0], posting_date="2026-10-31",
                                                   request_evidence="Mixed zero portion late cost")
        preview = await preview_output_cost_correction(session, pg_book[0], "2026-10", command)
        allocations = preview["ledger_evidence"]["allocation"]
        disposals = [row for row in allocations if row["key"].startswith("allocation:")]
        remaining = [row for row in allocations if row["key"].startswith("remaining")]
        assert [Decimal(str(row["quantity"])) for row in disposals] == [Decimal("1"), Decimal("0.05")]
        assert [Decimal(str(row["delta"])) for row in disposals] == [Decimal("50"), Decimal("2.50")]
        assert sum(Decimal(str(row["delta"])) for row in remaining) == Decimal("47.50")
        assert sum(Decimal(str(row["quantity"])) for row in allocations) == Decimal("2")
        assert all(row["entry_id"] == issue_id for row in preview["trace"]["disposals"])
        assert {row["source_entry_id"] for row in preview["trace"]["disposals"]} == set(output_ids)
        confirmation = ProductionOutputCostConfirmInput(**command.model_dump(), request_key=uuid4(),
                                                        basis_digest=preview["basis_digest"])
        revision = await confirm_output_cost_correction(session, pg_book[0], "2026-10", confirmation, "tester")
        await session.commit()
        identity = (revision.id, revision.entry_id, revision.registration_token)
    async with pg_factory() as session:
        assert (await confirm_output_cost_correction(session, pg_book[0], "2026-10", confirmation, "tester")).id == identity[0]
        unchanged = await preview_output_cost_correction(session, pg_book[0], "2026-10", command)
        assert unchanged["ledger_evidence"]["matrix"] == []
        await service.post(session, pg_book[0], late.model_copy(update={"source": "mixed-next-late-wip"}), "tester")
        second = await preview_output_cost_correction(session, pg_book[0], "2026-10", command)
        await confirm_output_cost_correction(session, pg_book[0], "2026-10",
            ProductionOutputCostConfirmInput(**command.model_dump(), request_key=uuid4(), basis_digest=second["basis_digest"]), "tester")
        await session.commit()
    async with pg_factory() as session:
        historical = await session.scalar(text(
            "SELECT accounting.output_cost_revision_evidence(:org,:output,DATE '2026-10-31',:entry,:token)::text"
        ), {"org": pg_book[0], "output": output_ids[0], "entry": identity[1], "token": identity[2]})
        assert json.loads(historical, parse_float=str) == preview["ledger_evidence"]
        with pytest.raises(DBAPIError, match="Cannot downgrade 0145"):
            async with session.begin_nested():
                await run_migration(session, "0145_inventory_allocation_cost_stream.py", "downgrade")


@pytest.mark.parametrize("pg_factory", ["legacy_0139"], indirect=True)
async def test_0145_empty_roundtrip_retains_legacy_evidence_definitions(pg_factory):
    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py",
                         "0144_inventory_explicit_allocation_guards.py"):
            await run_migration(session, revision, "upgrade")
        query = text("SELECT pg_get_functiondef('accounting.output_cost_revision_evidence(integer,integer,date,integer,integer)'::regprocedure)")
        before = await session.scalar(query)
        await run_migration(session, "0145_inventory_allocation_cost_stream.py", "upgrade")
        await run_migration(session, "0145_inventory_allocation_cost_stream.py", "downgrade")
        assert await session.scalar(query) == before
        assert await session.scalar(text("SELECT to_regprocedure('accounting.inventory_allocation_cost_stream(integer,text,text,text,date,integer)')")) is None
        await run_migration(session, "0145_inventory_allocation_cost_stream.py", "upgrade")
        await session.commit()


@pytest.mark.parametrize("pg_factory", ["empty_restore"], indirect=True)
@pytest.mark.parametrize("method", ["specific", "weighted_average"])
async def test_0145_preserves_legacy_monetary_sale_and_correction_history(pg_factory, tmp_path, method):
    from tests.accounting.historical_0145 import run_historical_case

    await run_historical_case(pg_factory, tmp_path, "monetary-" + method)


@pytest.mark.parametrize("pg_factory", ["empty_restore"], indirect=True)
async def test_0145_keeps_existing_zero_issue_late_cost(pg_factory, tmp_path):
    from tests.accounting.historical_0145 import run_historical_case

    await run_historical_case(pg_factory, tmp_path, "zero-existing-issue")


async def single_actual_output(factory, book, api, *, method="weighted_average", normative_verified=False):
    """One accepted physical output, with its reviewed 100 BYN accounting transfer."""
    from core.domain.models import Sku
    from core.services.auth import CurrentUser
    from modules.accounting.gateway import AccountingService
    from modules.production.accounting_ownership import (
        OwnershipCommand,
        assign_order,
        order_snapshot,
    )
    from modules.production.models import ProductionOrder
    from modules.production.output_documents import OutputCommand, confirm_output, prepare_output
    from modules.wms.models import Location, Receipt, ReceiptLine, WarehouseDirectory

    policy_id = await _seed_production_book(factory, book, method, normative_verified=normative_verified)
    await _seed_wip(factory, book, policy_id)
    api.headers["X-User"] = "tester"
    core = api._transport.app.state.core
    production, warehouse = core.services.production_output, core.services.wms_reservations
    gateway, user = AccountingService(), CurrentUser("tester", ["director"])
    async with factory() as session:
        order = ProductionOrder(id=42, number="SYN-42", product="Synthetic widget", qty=2)
        place = Location(warehouse="Main", code="SYN-OUTPUT")
        session.add_all([order, place, Sku(code="SYN-WIDGET", title="Synthetic widget", unit="шт"),
                        WarehouseDirectory(id=42, organization_id=book[0], name="Main",
                            title="Synthetic output warehouse", wms_enabled=False,
                            prohibit_negative_stock=True, is_active=True, created_by="tester")])
        await session.flush()
        digest = order_snapshot(order)[1]
        await assign_order(session, gateway, book[0], user, OwnershipCommand(
            order_id=order.id, expected_digest=digest, evidence="Synthetic reviewed owner"))
        physical = await prepare_output(session, gateway, book[0], user, OutputCommand(
            request_id=uuid4(), order_id=order.id, expected_order_digest=digest,
            operation_date="2026-10-10", sku_code="SYN-WIDGET", quantity="2.00", warehouse="Main",
            location_id=place.id, lot="LOT-1", evidence="Synthetic reviewed output"), warehouse_gateway=warehouse)
        await confirm_output(session, gateway, book[0], user, physical.id, physical.digest,
                             warehouse_gateway=warehouse)
        physical_id = physical.id
        await session.commit()
    assert await core.event_bus.relay_pending(factory, core.services, event_types=("production.output.confirmed",)) == 1
    async with factory() as session:
        receipt_id, line_id = (await session.execute(select(Receipt.id, ReceiptLine.id).join(
            ReceiptLine, ReceiptLine.receipt_id == Receipt.id).where(
                Receipt.organization_id == book[0], Receipt.entity_ref == f"production_output:{physical_id}"))).one()
    path = f"/wms/receipts/{receipt_id}"
    detail = await api.get(path)
    assert detail.status_code == 200, detail.text
    qc = await api.post(path + "/qc", json={"expected_revision": detail.json()["qc_revision"], "decisions": [
        {"line_id": line_id, "accepted_qty": "2.00", "rejected_qty": "0.00", "reject_reason": "Synthetic accepted output"}]})
    assert qc.status_code == 200, qc.text
    accepted = await api.post(path + "/accept")
    assert accepted.status_code == 200, accepted.text
    async with factory() as session:
        command = transfer_input(policy_id).model_copy(update={"output_document_ids": [physical_id]})
        preview = await prepare_output_transfer(session, book[0], "2026-10", command, production, warehouse)
        confirmation = ProductionOutputTransferConfirmInput.model_validate({
            **command.model_dump(mode="json"), "basis_digest": preview["basis_digest"], "digest": preview["digest"]})
        output = await confirm_output_transfer(session, book[0], "2026-10", confirmation, "tester",
                                                production=production, warehouse_gateway=warehouse)
        output_id = output.id
        await session.commit()
    return output_id


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_pool_stream_preserves_real_production_output(pg_factory, pg_book, issuance_pg):
    actual_output_id = await single_actual_output(pg_factory, pg_book, issuance_pg[0])
    async with pg_factory() as session:
        output_id = (await session.execute(text(
            "SELECT entry_id FROM accounting.production_output_transfer_receipt WHERE organization_id=:org"
        ), {"org": pg_book[0]})).scalar_one()
        assert output_id == actual_output_id
        rows = await session.scalar(text(
            "SELECT accounting.output_pool_revision_rows(:org,:output,DATE '2026-10-31',NULL,NULL)"
        ), {"org": pg_book[0], "output": output_id})
        assert len(rows) == 1
        assert rows[0]["key"] == "remaining"
        assert Decimal(str(rows[0]["quantity"])) == Decimal("2")
        assert Decimal(str(rows[0]["book"])) == Decimal("100")
        await session.rollback()


async def current_mixed_disposal(factory, book, posting):
    """Post the mixed-cent disposal through current directory and receipt guards."""
    from datetime import date

    from sqlalchemy import func

    from core.domain.models import Sku
    from modules.accounting.models import Account, Entry, InventoryIssueReceipt, Policy
    from modules.wms.models import WarehouseDirectory
    from tests.accounting.test_inventory_cost import move

    async with factory() as session:
        policy_id = (await session.scalar(select(func.max(Policy.id))) or 0) + 1
        account_id = (await session.scalar(select(func.max(Account.id))) or 0) + 1
        policy = Policy(id=policy_id, organization_id=book[0], effective_from=date(2026, 2, 1),
            reference="Synthetic allocation policy", inventory_method="weighted_average", allocation_basis="direct_cost",
            depreciation_method="straight_line", normative_reference="Synthetic", normative_verified=False,
            approved_by="tester")
        warehouse = WarehouseDirectory(id=42, organization_id=book[0], name="W", title="Synthetic inventory warehouse",
            wms_enabled=False, prohibit_negative_stock=True, is_active=True, created_by="tester")
        sku = Sku(code="SKU", title="Synthetic allocation item", unit="шт", is_active=True)
        session.add_all([policy, warehouse, sku, Account(id=account_id, organization_id=book[0], code="41.2",
            title="Quantitative goods", category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
            currency_tracking=True, quantity_tracking=True, cash=False, normative_ref="synthetic")])
        await session.commit()
        await move(session, (book[0], policy_id), posting, "allocation-old", "1", "0.01", day="2026-09-01", lot="old")
        await move(session, (book[0], policy_id), posting, "allocation-new", "2", "0.01", day="2026-09-02", lot="new")
        document = InventoryIssueDocument(source="allocation-weighted-cent", source_version=1,
            document_date="2026-09-03", operation_date="2026-09-03", posting_date="2026-09-03", policy_id=policy_id,
            account="41.2", warehouse="W", sku="SKU", lot="", quantity="2", expense_account="90.4",
            expense_dimensions={}, explanation="Synthetic explicit allocation",
            warehouse_identity={"id": warehouse.id, "name": warehouse.name, "title": warehouse.title},
            sku_identity={"id": sku.id, "code": sku.code, "title": sku.title, "unit": sku.unit})
        cost, package = await inventory_issues.prepare(session, book[0], document,
            source_allocations=True, require_current_inventory=True)
        assert [layer["amount_byn"] for layer in cost["inventory_layers"]] == ["0.01", "0.00"]
        digest = service.digest(package)
        entry = await inventory_issues.confirm(session, book[0], document, cost["basis_digest"], digest,
            "tester", source_allocations=True, require_current_inventory=True)
        entry_id = entry.id
        await session.commit()
    async with factory() as session:
        events = await load_authenticated_inventory_dispositions(session, book[0])
        assert len(events) == 1 and events[0].entry_id == entry_id and events[0].allocation.quantity == Decimal("2")
        entries = await session.scalar(select(func.count()).select_from(Entry).where(Entry.organization_id == book[0]))
        replay = await inventory_issues.confirm(session, book[0], document, cost["basis_digest"], digest,
            "tester", source_allocations=True, require_current_inventory=True)
        assert replay.id == entry_id
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(Entry).where(Entry.organization_id == book[0])) == entries
        assert await session.scalar(select(func.count()).select_from(InventoryIssueReceipt).where(
            InventoryIssueReceipt.organization_id == book[0])) == 1


@pytest.mark.parametrize("pg_factory", ["registered_head"], indirect=True)
async def test_full_allocation_stream_preserves_zero_portion_and_cutoff(pg_factory, pg_book, posting):
    await current_mixed_disposal(pg_factory, pg_book, posting)
    query = text("SELECT * FROM accounting.inventory_allocation_cost_stream(:org,'41.2','W','SKU',CAST(:cutoff AS date),:token)")
    async with pg_factory() as session:
        params = {"org": pg_book[0], "cutoff": "2026-09-04", "token": None}
        portions = (await session.execute(query, params)).mappings().all()
        assert [row["quantity"] for row in portions] == [Decimal(1), Decimal(1)]
        assert [row["book"] for row in portions] == [Decimal("0.01"), Decimal("0.00")]
        assert len({row["event_key"] for row in portions}) == 2
        assert all(row["destination_account"] == "90.4" and row["source_entry_id"] < row["disposition_entry_id"] for row in portions)
        assert not (await session.execute(query, {**params, "token": portions[0]["disposition_entry_id"]})).all()
        assert not (await session.execute(query, {**params, "org": pg_book[0] + 1000})).all()
        with pytest.raises(DBAPIError, match="future explicit allocation"):
            await session.execute(query, {**params, "cutoff": "2026-09-02"})
        await session.rollback()
