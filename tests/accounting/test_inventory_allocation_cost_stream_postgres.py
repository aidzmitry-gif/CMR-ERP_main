"""The late-cost input keeps zero portions and their real source identities."""
# ruff: noqa: F811
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting import inventory_cost, inventory_issues, models, sales, service
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
    InventoryIssuePreviewInput,
    LineInput,
    PostingInput,
)
from tests.accounting.test_finished_goods_inventory_postgres import _confirm_output
from tests.accounting.test_inventory_allocation_loader import save_mixed_weighted_receipt
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_production_output_transfer_postgres import (
    SyntheticProduction,
    _seed_production_book,
    _seed_wip,
    transfer_input,
)
from tests.accounting.test_zero_value_output_cost_postgres import run_migration

pytestmark = pytest.mark.integration


class TwoOutputs(SyntheticProduction):
    def __init__(self, same_lot=False):
        self.same_lot = same_lot

    async def output_reconciliation(self, session, organization_id, order_id, warehouse):
        facts = await super().output_reconciliation(session, organization_id, order_id, warehouse)
        return {**facts, "lot": "SHARED" if self.same_lot else f"LOT-{order_id}",
                "documents": [{"document_id": order_id + 59, "operation_date": "2026-10-10"}]}


async def mixed_production_disposal(factory, book, *, method="weighted_average", same_lot=False, sale=False):
    """Two real 2-unit outputs at one cent each, followed by a 2.1-unit disposal."""
    policy_id = await _seed_production_book(factory, book, method)
    await _seed_wip(factory, book, policy_id, [("SHOP", "ORDER-42", "0.01"), ("SHOP", "ORDER-43", "0.01")])
    production = TwoOutputs(same_lot)
    output_ids = []
    async with factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py",
                         "0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py"):
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
        document = InventoryIssueDocument(source="mixed-output-issue", source_version=1,
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            account="43", warehouse="Main", sku="SYN-WIDGET", lot="", quantity="2.1", expense_account="90.4",
            expense_dimensions={}, explanation="Reviewed mixed output disposal")
        request = InventoryIssuePreviewInput(**document.model_dump(include=set(InventoryIssuePreviewInput.model_fields)))
        policy, rows, verified, finished = await inventory_cost._inventory_rows(session, book[0], request)
        cost = inventory_cost.issue_result(policy, rows, book[0], request,
            verified_output_lines=verified, finished_goods=finished, include_source_identity=True)
        cost["source_allocation_version"] = 1
        assert [layer["amount_byn"] for layer in cost["inventory_layers"]] == ["0.01", "0.00"]
        if sale:
            document = sales.SaleDocument(**document.model_dump(), net_amount="10.00", vat_rate="0",
                vat_basis="Synthetic exemption", buyer_account="62", revenue_account="90.1",
                vat_revenue_account="90.2", vat_payable_account="68",
                buyer_dimensions={"counterparty": "BUYER", "contract": "CONTRACT", "settlement_document": "INVOICE"})
        package = sales.posting_for(document, cost) if sale else inventory_issues.posting_for(document, cost)
        package = package.model_copy(update={"lines": [line for line in package.lines if line.amount > 0]})
        entry = await service.post(session, book[0], package, "tester", inventory_issue=not sale, inventory_sale=sale)
        receipt_type = models.InventorySaleReceipt if sale else models.InventoryIssueReceipt
        session.add(receipt_type(entry_id=entry.id, organization_id=book[0],
            command=document.model_dump(mode="json"), cost=json.loads(json.dumps(cost, default=str)),
            posting=package.model_dump(mode="json"), digest=service.digest(package), actor="tester"))
        await session.commit()
        events = await load_authenticated_inventory_dispositions(session, book[0])
        assert len(events) == 1
        assert events[0].allocation.quantity == Decimal("2.1")
    return policy_id, output_ids, entry.id


@pytest.mark.parametrize("same_lot", [False, True])
async def test_fifo_late_cost_uses_exact_output_source_including_zero_portion(pg_factory, pg_book, same_lot):
    policy_id, outputs, issue_id = await mixed_production_disposal(pg_factory, pg_book, method="fifo", same_lot=same_lot)
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
async def test_mixed_production_late_cost_confirm_replay_and_historical_cutoff(pg_factory, pg_book, sale):
    policy_id, output_ids, issue_id = await mixed_production_disposal(pg_factory, pg_book, sale=sale)
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


@pytest.mark.parametrize("method", ["specific", "weighted_average"])
async def test_0145_preserves_legacy_monetary_sale_and_correction_history(pg_factory, pg_book, method):
    from tests.accounting.test_finished_goods_inventory_postgres import (
        test_output_cost_preview_authenticates_late_wip_and_sale_destinations as legacy_scenario,
    )

    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py",
                         "0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py"):
            await run_migration(session, revision, "upgrade")
        await session.commit()
    await legacy_scenario(pg_factory, pg_book, method)


async def test_0145_keeps_existing_zero_issue_late_cost(pg_factory, pg_book):
    from modules.accounting.zero_value_disposals import (
        preview_standalone_zero_value_issue_basis,
        register_standalone_zero_value_issue,
    )
    from tests.accounting.test_zero_value_disposals_postgres import command, zeroed_output

    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py"):
            await run_migration(session, revision, "upgrade")
        await session.commit()
    policy_id, output_id, line_id = await zeroed_output(pg_factory, pg_book)
    async with pg_factory() as session:
        draft = command(policy_id, output_id, line_id, destination_account="90.4", destination_dimensions={})
        basis = await preview_standalone_zero_value_issue_basis(session, pg_book[0], draft)
        await register_standalone_zero_value_issue(session, pg_book[0], "tester", draft.model_copy(update={"basis_digest": basis}))
        for revision in ("0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py"):
            await run_migration(session, revision, "upgrade")
        await service.post(session, pg_book[0], PostingInput(source="legacy-zero-late-wip", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic", explanation="Legacy zero issue late cost", lines=[
                LineInput(account="20", side="debit", amount="100", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="100")]), "tester")
        request = ProductionOutputCostPreviewInput(original_entry_id=output_id, posting_date="2026-10-31",
                                                  request_evidence="Legacy zero receipt survives 0145")
        preview = await preview_output_cost_correction(session, pg_book[0], "2026-10", request)
        assert preview["trace"]["disposals"][0]["kind"] == "zero"
        assert sorted(row["amount_byn"] for row in preview["destinations"]) == ["25.00", "75.00"]
        await confirm_output_cost_correction(session, pg_book[0], "2026-10",
            ProductionOutputCostConfirmInput(**request.model_dump(), request_key=uuid4(), basis_digest=preview["basis_digest"]), "tester")
        await session.commit()


async def test_pool_stream_preserves_real_production_output(pg_factory, pg_book):
    await _confirm_output(pg_factory, pg_book, method="weighted_average")
    async with pg_factory() as session:
        for revision in ("0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py"):
            await run_migration(session, revision, "upgrade")
        output_id = await session.scalar(text(
            "SELECT entry_id FROM accounting.production_output_transfer_receipt WHERE organization_id=:org"
        ), {"org": pg_book[0]})
        rows = await session.scalar(text(
            "SELECT accounting.output_pool_revision_rows(:org,:output,DATE '2026-10-31',NULL,NULL)"
        ), {"org": pg_book[0], "output": output_id})
        assert len(rows) == 1
        assert rows[0]["key"] == "remaining"
        assert Decimal(str(rows[0]["quantity"])) == Decimal("2")
        assert Decimal(str(rows[0]["book"])) == Decimal("100")
        await session.rollback()


async def test_full_allocation_stream_preserves_zero_portion_and_cutoff(pg_factory, pg_book, posting):
    async with pg_factory() as session:
        for revision in ("0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py"):
            await run_migration(session, revision, "upgrade")
        await session.commit()
    await save_mixed_weighted_receipt(pg_factory, pg_book, posting)
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
