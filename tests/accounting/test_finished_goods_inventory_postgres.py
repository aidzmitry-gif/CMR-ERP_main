# ruff: noqa: F811 -- imported fixtures are used by pytest parameter lookup.
"""PostgreSQL evidence for policy-bound finished-goods disposal."""
import runpy
from datetime import date
from decimal import Decimal

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text

from modules.accounting import inventory_cost, inventory_issues, sales, service
from modules.accounting.models import Line, ProductionOutputTransferReceipt
from modules.accounting.production_output_cost_trace import trace_output_layer
from modules.accounting.production_output_cost_workflow import (
    ProductionOutputCostPreviewInput,
    preview_output_cost_correction,
)
from modules.accounting.production_output_transfer import (
    ProductionOutputTransferConfirmInput,
    prepare_output_transfer,
)
from modules.accounting.schemas import InventoryIssuePreviewInput, LineInput, PostingInput
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_production_output_transfer_postgres import (
    SyntheticProduction,
    _seed_production_book,
    _seed_wip,
    _upgrade_group_guard,
    transfer_input,
)
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401

pytestmark = pytest.mark.integration


async def _upgrade_output_cost_revision(session):
    if await session.scalar(text("SELECT to_regclass('accounting.production_output_cost_revision')")):
        return  # The shared PG fixture now installs this actual migration.
    def upgrade(connection):
        migration = runpy.run_path("migrations/versions/0139_production_output_cost_revision.py")
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()

    await (await session.connection()).run_sync(upgrade)


async def _run_output_cost_revision_migration(session, action):
    def run(connection):
        migration = runpy.run_path("migrations/versions/0139_production_output_cost_revision.py")
        with Operations.context(MigrationContext.configure(connection)):
            migration[action]()

    await (await session.connection()).run_sync(run)


async def _confirm_output(factory, book, method="specific", *, normative_verified=False):
    policy_id = await _seed_production_book(factory, book, method, normative_verified=normative_verified)
    await _seed_wip(factory, book, policy_id)
    production = SyntheticProduction()
    command = transfer_input(policy_id)
    async with factory() as session:
        preview = await prepare_output_transfer(session, book[0], "2026-10", command, production, object())
        confirmed = ProductionOutputTransferConfirmInput.model_validate({
            **command.model_dump(mode="json"), "basis_digest": preview["basis_digest"], "digest": preview["digest"],
        })
        await _upgrade_group_guard(session)
        await session.commit()
    async with factory() as session:
        from modules.accounting.production_output_transfer import confirm_output_transfer

        await confirm_output_transfer(session, book[0], "2026-10", confirmed, "tester",
                                      production=production, warehouse_gateway=object())
        await session.commit()
    return policy_id


def sale_document(policy_id):
    return sales.SaleDocument.model_validate({
        "policy_id": policy_id, "posting_date": "2026-10-31", "account": "43", "warehouse": "Main",
        "sku": "SYN-WIDGET", "lot": "LOT-1", "quantity": "1", "source": "sale:fg:1", "source_version": 1,
        "document_date": "2026-10-31", "operation_date": "2026-10-31", "expense_account": "90.4",
        "expense_dimensions": {}, "explanation": "Synthetic finished-goods sale", "net_amount": "100.00",
        "vat_rate": "0", "vat_basis": "Synthetic explicit zero VAT basis", "buyer_account": "62",
        "revenue_account": "90.1", "vat_revenue_account": "90.2", "vat_payable_account": "68.2",
        "buyer_dimensions": {"counterparty": "buyer", "contract": "contract", "settlement_document": "sale:fg:1"},
    })


async def test_finished_goods_sale_uses_immutable_output_layer_and_replays(pg_factory, pg_book):
    policy_id = await _confirm_output(pg_factory, pg_book)
    document = sale_document(policy_id)
    async with pg_factory() as session:
        prepared = await sales.prepare(session, pg_book[0], document)
        assert prepared["cost"]["issue_cost_byn"] == "50.00"
        entry = await sales.confirm(session, pg_book[0], document, prepared["cost"]["basis_digest"], prepared["digest"], "tester")
        await session.commit()
    async with pg_factory() as session:
        output = await session.scalar(select(ProductionOutputTransferReceipt).where(
            ProductionOutputTransferReceipt.organization_id == pg_book[0]))
        trace = await trace_output_layer(session, pg_book[0], output, date(2026, 10, 31))
        assert (trace["received_quantity"], trace["received_value_byn"], trace["remaining_quantity"],
                trace["remaining_value_byn"]) == ("2.000000", "100.00", "1.000000", "50.00")
        assert [(row["quantity"], row["applied_cost_byn"], row["destination_account"])
                for row in trace["disposals"]] == [("1.000000", "50.00", "90.4")]
        repeated = await sales.confirm(session, pg_book[0], document, prepared["cost"]["basis_digest"], prepared["digest"], "tester")
        assert repeated.id == entry.id
        remaining = await inventory_cost.preview_issue(session, pg_book[0], InventoryIssuePreviewInput(
            policy_id=policy_id, posting_date=date(2026, 10, 31), account="43", warehouse="Main",
            sku="SYN-WIDGET", lot="LOT-1", quantity=Decimal("1"),
        ))
        assert (remaining["book_quantity"], remaining["book_value_byn"]) == ("1.000000", "50.00")
        late_wip = PostingInput(
            source="production:late-cost:42", source_version=1, operation="manual", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic-late-wip-v1", explanation="Synthetic same-day late WIP", lines=[
                LineInput(account="20", side="debit", amount="10.00", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="10.00", dimensions={}),
            ],
        )
        await service.post(session, pg_book[0], late_wip, "tester")
        await session.commit()
    async with pg_factory() as session:
        assert (await sales.confirm(session, pg_book[0], document, prepared["cost"]["basis_digest"], prepared["digest"], "tester")).id == entry.id
        new_document = sales.SaleDocument.model_validate({**document.model_dump(mode="json"), "source": "sale:fg:2",
                                                          "buyer_dimensions": {**document.buyer_dimensions, "settlement_document": "sale:fg:2"}})
        with pytest.raises(service.AccountingError, match="output cost basis is stale"):
            await sales.prepare(session, pg_book[0], new_document)


@pytest.mark.parametrize("method", ["specific", "fifo", "weighted_average"])
async def test_output_cost_preview_authenticates_late_wip_and_sale_destinations(pg_factory, pg_book, method):
    """2 units / 100, one sale / 50, then WIP +20 -> +10 stock and +10 expense."""
    policy_id = await _confirm_output(pg_factory, pg_book, method)
    document = sale_document(policy_id)
    async with pg_factory() as session:
        await _upgrade_output_cost_revision(session)
        prepared = await sales.prepare(session, pg_book[0], document)
        sale = await sales.confirm(session, pg_book[0], document, prepared["cost"]["basis_digest"],
                                   prepared["digest"], "tester")
        await service.post(session, pg_book[0], PostingInput(
            source="production:late-wip:output-preview", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic-late-wip-v1",
            explanation="Synthetic late WIP for output correction preview", lines=[
                LineInput(account="20", side="debit", amount="20.00",
                          dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="20.00", dimensions={}),
            ],
        ), "tester")
        await session.commit()
    async with pg_factory() as session:
        receipt = await session.scalar(select(ProductionOutputTransferReceipt).where(
            ProductionOutputTransferReceipt.organization_id == pg_book[0]))
        preview = await preview_output_cost_correction(
            session, pg_book[0], "2026-10", ProductionOutputCostPreviewInput(
                original_entry_id=receipt.entry_id, posting_date=date(2026, 10, 31),
                request_evidence="late WIP document was reviewed",
            ),
        )
        assert preview["source"]["candidate_transfer_byn"] == "120.00"
        assert preview["trace"]["disposals"] == [{
            "entry_id": sale.id, "line_id": preview["trace"]["disposals"][0]["line_id"],
            "receipt_entry_id": sale.id, "quantity": "1.000000", "applied_cost_byn": "50.00",
            "destination_account": "90.4", "destination_dimensions": {},
        }]
        deltas = {row["key"]: row["delta_cents"] for row in preview["destinations"]}
        assert deltas == {"remaining": 1000, f"disposed:{sale.id}:{preview['trace']['disposals'][0]['line_id']}": 1000}
        assert preview["delta_cents"] == 2000
        assert preview["confirmation_available"] is True
        from uuid import uuid4

        from modules.accounting.production_output_cost_workflow import (
            ProductionOutputCostConfirmInput,
            confirm_output_cost_correction,
        )

        confirmation = ProductionOutputCostConfirmInput(
            original_entry_id=receipt.entry_id, posting_date=date(2026, 10, 31),
            request_evidence="late WIP document was reviewed", request_key=uuid4(), basis_digest=preview["basis_digest"])
        wrong = confirmation.model_copy(update={"basis_digest": "0" * 64})
        with pytest.raises(service.AccountingError, match="basis changed"):
            await confirm_output_cost_correction(session, pg_book[0], "2026-10", wrong, "tester")
        revision = await confirm_output_cost_correction(session, pg_book[0], "2026-10", confirmation, "tester")
        await session.commit()
        first_revision_id = revision.id
    async with pg_factory() as session:
        repeated = await confirm_output_cost_correction(session, pg_book[0], "2026-10", confirmation, "tester")
        assert repeated.id == first_revision_id
        empty = await preview_output_cost_correction(session, pg_book[0], "2026-10", ProductionOutputCostPreviewInput(
            original_entry_id=confirmation.original_entry_id, posting_date=date(2026, 10, 31), request_evidence="No new costs"))
        assert empty["posting_document"] is None
        assert empty["delta_cents"] == 0
        assert empty["sequence"] == 2
        zero = ProductionOutputCostConfirmInput(original_entry_id=confirmation.original_entry_id,
            posting_date=date(2026, 10, 31), request_evidence="No new costs", request_key=uuid4(), basis_digest=empty["basis_digest"])
        second = await confirm_output_cost_correction(session, pg_book[0], "2026-10", zero, "tester")
        assert second.entry_id is None
        await session.commit()


    async with pg_factory() as session:
        # The second unit consumes the corrected 60; historical sale remains 50.
        next_document = sales.SaleDocument.model_validate({**document.model_dump(mode="json"),
            "source": "sale:fg:after-correction", "buyer_dimensions": {
                **document.buyer_dimensions, "settlement_document": "sale:fg:after-correction"}})
        next_preview = await sales.prepare(session, pg_book[0], next_document)
        assert next_preview["cost"]["issue_cost_byn"] == "60.00"
        second_sale = await sales.confirm(session, pg_book[0], next_document,
            next_preview["cost"]["basis_digest"], next_preview["digest"], "tester")
        await session.commit()
    async with pg_factory() as session:
        await service.post(session, pg_book[0], PostingInput(
            source="production:late-after-second-sale", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Costs after both sales", lines=[
                LineInput(account="20", side="debit", amount="20", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="20"),
            ]), "tester")
        third_preview = await preview_output_cost_correction(session, pg_book[0], "2026-10", ProductionOutputCostPreviewInput(
            original_entry_id=confirmation.original_entry_id, posting_date=date(2026, 10, 31), request_evidence="After second sale"))
        assert third_preview["sequence"] == 3
        assert third_preview["delta_cents"] == 2000
        assert {r["account"] for r in third_preview["posting_document"]["lines"]} == {"20", "90.4"}
        third_command = ProductionOutputCostConfirmInput(original_entry_id=confirmation.original_entry_id,
            posting_date=date(2026, 10, 31), request_evidence="After second sale", request_key=uuid4(),
            basis_digest=third_preview["basis_digest"])
        await confirm_output_cost_correction(session, pg_book[0], "2026-10", third_command, "tester")
        await session.commit()
    async with pg_factory() as session:
        assert (await sales.confirm(session, pg_book[0], document, prepared["cost"]["basis_digest"], prepared["digest"], "tester")).id == sale.id
        assert (await sales.confirm(session, pg_book[0], next_document, next_preview["cost"]["basis_digest"], next_preview["digest"], "tester")).id == second_sale.id
        from modules.accounting.production_output_transfer import (
            validate_output_transfers_for_close,
        )

        await validate_output_transfers_for_close(session, pg_book[0], "2026-10")


async def _output_cost_command(session, org_id, receipt_id):
    from uuid import uuid4

    from modules.accounting.production_output_cost_workflow import ProductionOutputCostConfirmInput

    preview = await preview_output_cost_correction(session, org_id, "2026-10", ProductionOutputCostPreviewInput(
        original_entry_id=receipt_id, posting_date=date(2026, 10, 31),
        request_evidence="Reviewed late WIP correction",
    ))
    return ProductionOutputCostConfirmInput(
        original_entry_id=receipt_id, posting_date=date(2026, 10, 31),
        request_evidence="Reviewed late WIP correction", request_key=uuid4(), basis_digest=preview["basis_digest"],
    )


async def test_output_cost_confirm_same_command_concurrently_creates_one_revision(pg_factory, pg_book):
    """Two sessions retrying one request key serialize to the same immutable revision."""
    from sqlalchemy import func

    from modules.accounting.models import Entry, ProductionOutputCostRevision
    from modules.accounting.production_output_cost_workflow import confirm_output_cost_correction

    policy_id = await _confirm_output(pg_factory, pg_book)
    async with pg_factory() as session:
        output = await session.scalar(select(ProductionOutputTransferReceipt).where(
            ProductionOutputTransferReceipt.organization_id == pg_book[0]))
        await service.post(session, pg_book[0], PostingInput(
            source="production:late-wip:concurrent", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Late WIP for concurrent correction", lines=[
                LineInput(account="20", side="debit", amount="20", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="20"),
            ]), "tester")
        command = await _output_cost_command(session, pg_book[0], output.entry_id)
        await session.commit()

    async def confirm_once():
        async with pg_factory() as session:
            revision = await confirm_output_cost_correction(session, pg_book[0], "2026-10", command, "tester")
            await session.commit()
            return revision.id, revision.entry_id

    import asyncio

    left, right = await asyncio.gather(confirm_once(), confirm_once())
    assert left == right
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionOutputCostRevision).where(
            ProductionOutputCostRevision.organization_id == pg_book[0],
            ProductionOutputCostRevision.request_key == str(command.request_key),
        )) == 1
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.organization_id == pg_book[0],
            Entry.operation == "production_output_cost_correction",
            Entry.source == f"production:output-cost-revision:{pg_book[0]}:{output.entry_id}:1",
        )) == 1


async def test_negative_output_cost_revision_changes_future_sale_not_historical_replay(pg_factory, pg_book):
    """A -20 WIP revision makes remaining stock 40 while the old sale stays 50."""
    from modules.accounting.production_output_cost_workflow import confirm_output_cost_correction

    policy_id = await _confirm_output(pg_factory, pg_book)
    document = sale_document(policy_id)
    async with pg_factory() as session:
        prepared = await sales.prepare(session, pg_book[0], document)
        original_sale = await sales.confirm(session, pg_book[0], document, prepared["cost"]["basis_digest"],
                                            prepared["digest"], "tester")
        output = await session.scalar(select(ProductionOutputTransferReceipt).where(
            ProductionOutputTransferReceipt.organization_id == pg_book[0]))
        await service.post(session, pg_book[0], PostingInput(
            source="production:reverse-wip:remaining", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Negative late WIP", lines=[
                LineInput(account="20", side="credit", amount="20", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="debit", amount="20"),
            ]), "tester")
        command = await _output_cost_command(session, pg_book[0], output.entry_id)
        revision = await confirm_output_cost_correction(session, pg_book[0], "2026-10", command, "tester")
        assert revision.entry_id is not None
        await session.commit()
    async with pg_factory() as session:
        next_document = sales.SaleDocument.model_validate({**document.model_dump(mode="json"),
            "source": "sale:fg:negative-revision", "buyer_dimensions": {
                **document.buyer_dimensions, "settlement_document": "sale:fg:negative-revision"}})
        next_preview = await sales.prepare(session, pg_book[0], next_document)
        assert next_preview["cost"]["issue_cost_byn"] == "40.00"
        await sales.confirm(session, pg_book[0], next_document, next_preview["cost"]["basis_digest"],
                            next_preview["digest"], "tester")
        await session.commit()
    async with pg_factory() as session:
        replay = await sales.confirm(session, pg_book[0], document, prepared["cost"]["basis_digest"],
                                     prepared["digest"], "tester")
        assert replay.id == original_sale.id


async def test_output_cost_revision_downgrade_preserves_populated_history(pg_factory, pg_book):
    from sqlalchemy.exc import DBAPIError

    from modules.accounting.models import Entry, ProductionOutputCostRevision
    from modules.accounting.production_output_cost_workflow import confirm_output_cost_correction

    policy_id = await _confirm_output(pg_factory, pg_book)
    async with pg_factory() as session:
        output = await session.scalar(select(ProductionOutputTransferReceipt).where(
            ProductionOutputTransferReceipt.organization_id == pg_book[0]))
        await service.post(session, pg_book[0], PostingInput(
            source="production:late-wip:downgrade", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Late WIP before downgrade check", lines=[
                LineInput(account="20", side="debit", amount="20", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="20"),
            ]), "tester")
        command = await _output_cost_command(session, pg_book[0], output.entry_id)
        revision = await confirm_output_cost_correction(session, pg_book[0], "2026-10", command, "tester")
        await session.commit()
        revision_id, entry_id = revision.id, revision.entry_id
    async with pg_factory() as session:
        with pytest.raises(DBAPIError, match="Cannot downgrade output cost revisions"):
            await _run_output_cost_revision_migration(session, "downgrade")
        await session.rollback()
        retained = await session.get(ProductionOutputCostRevision, revision_id)
        assert retained is not None and retained.entry_id == entry_id
        assert await session.get(Entry, entry_id) is not None


async def test_empty_output_cost_revision_downgrades_and_upgrades(pg_factory, pg_book):
    async with pg_factory() as session:
        await _upgrade_output_cost_revision(session)
        await _run_output_cost_revision_migration(session, "downgrade")
        assert await session.scalar(text("SELECT to_regclass('accounting.production_output_cost_revision')")) is None
        await _run_output_cost_revision_migration(session, "upgrade")
        assert await session.scalar(text("SELECT to_regclass('accounting.production_output_cost_revision')")) == (
            "accounting.production_output_cost_revision"
        )
        await session.commit()


async def test_output_cost_correction_marks_downstream_output_stale_without_rewriting_material_history(issuance_pg, pg_book):
    """Real output -> accepted WMS receipt -> material issue -> second output."""
    from types import SimpleNamespace
    from uuid import uuid4

    from core.domain.models import Sku
    from core.services.auth import CurrentUser
    from core.services.eventbus import OutboxEventBus
    from modules.accounting.gateway import AccountingService
    from modules.accounting.production_material_cost import (
        ProductionMaterialIssuePostingConfirmInput,
        ProductionMaterialIssuePostingInput,
        confirm_material_issue_posting,
        prepare_material_issue_posting,
    )
    from modules.accounting.production_output_cost_workflow import confirm_output_cost_correction
    from modules.accounting.production_output_transfer import (
        confirm_output_transfer,
        output_transfer_source_state,
        validate_output_transfers_for_close,
    )
    from modules.production.accounting_ownership import (
        OwnershipCommand,
        assign_order,
        order_snapshot,
    )
    from modules.production.models import ProductionOrder
    from modules.production.output_documents import (
        OutputCommand,
        ProductionOutputService,
        confirm_output,
        prepare_output,
    )
    from modules.wms.events import on_goods_received
    from modules.wms.models import Location, Receipt, ReceiptLine
    from modules.wms.production_material_issues import (
        ProductionMaterialIssueCommand,
        record_material_issue,
    )
    from modules.wms.reservation_gateway import WmsReservationService

    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    gateway, user = AccountingService(), CurrentUser("tester", ["director"])
    production, warehouse = ProductionOutputService(), WmsReservationService()
    policy_id = await _seed_production_book(factory, pg_book)
    await _seed_wip(factory, pg_book, policy_id)
    async with factory() as session:
        place = Location(warehouse="Main", code="COST-CHAIN")
        session.add_all([place, Sku(code="SYN-WIDGET", title="First output", unit="шт"),
                        Sku(code="SYN-WIDGET-2", title="Second output", unit="шт")])
        for order_id, qty in ((42, 2), (43, 1)):
            order = ProductionOrder(id=order_id, number=f"COST-CHAIN-{order_id}", product="Cost-chain widget", qty=qty)
            session.add(order)
            await session.flush()
            await assign_order(session, gateway, pg_book[0], user, OwnershipCommand(order_id=order.id,
                expected_digest=order_snapshot(order)[1], evidence="Reviewed cost-chain owner"))
        await _upgrade_group_guard(session)
        await session.commit()
        place_id = place.id

    async def accepted_output(order_id, sku, lot, qty):
        async with factory() as session:
            order = await session.get(ProductionOrder, order_id)
            doc = await prepare_output(session, gateway, pg_book[0], user, OutputCommand(
                request_id=uuid4(), order_id=order_id, expected_order_digest=order_snapshot(order)[1],
                operation_date=date(2026, 10, 31), sku_code=sku, quantity=qty, warehouse="Main",
                location_id=place_id, lot=lot, evidence="Reviewed physical production output"), warehouse_gateway=warehouse)
            await confirm_output(session, gateway, pg_book[0], user, doc.id, doc.digest, warehouse_gateway=warehouse)
            await session.commit()
            document_id = doc.id
        bus = OutboxEventBus()
        bus.subscribe("production.output.confirmed", on_goods_received)
        assert await bus.relay_pending(factory, SimpleNamespace(production_output=production),
                                       event_types=("production.output.confirmed",)) == 1
        async with factory() as session:
            receipt = await session.scalar(select(Receipt).where(Receipt.entity_ref == f"production_output:{document_id}"))
            line = await session.scalar(select(ReceiptLine).where(ReceiptLine.receipt_id == receipt.id))
            receipt_id, line_id = receipt.id, line.id
        path = f"/wms/receipts/{receipt_id}"
        detail = await api.get(path)
        assert detail.status_code == 200, detail.text
        qc = await api.post(path + "/qc", json={"expected_revision": detail.json()["qc_revision"],
            "decisions": [{"line_id": line_id, "accepted_qty": qty, "rejected_qty": "0.00"}]})
        assert qc.status_code == 200, qc.text
        accepted = await api.post(path + "/accept")
        assert accepted.status_code == 200, accepted.text
        async with factory() as session:
            command = transfer_input(policy_id).model_copy(update={"order_id": order_id,
                "analytical_order": f"ORDER-{order_id}", "output_document_ids": [document_id]})
            preview = await prepare_output_transfer(session, pg_book[0], "2026-10", command, production, warehouse)
            confirmed = ProductionOutputTransferConfirmInput.model_validate({**command.model_dump(mode="json"),
                "basis_digest": preview["basis_digest"], "digest": preview["digest"]})
            entry = await confirm_output_transfer(session, pg_book[0], "2026-10", confirmed, "tester",
                                                 production=production, warehouse_gateway=warehouse)
            await session.commit()
            return entry.id

    original_id = await accepted_output(42, "SYN-WIDGET", "LOT-1", "2.00")
    async with factory() as session:
        order = await session.get(ProductionOrder, 43)
        physical = ProductionMaterialIssueCommand(request_id=uuid4(), order_id=43,
            expected_order_digest=order_snapshot(order)[1], operation_date=date(2026, 10, 31),
            sku_code="SYN-WIDGET", quantity="1.00", warehouse="Main", location_id=place_id,
            lot="LOT-1", evidence="Reviewed second-stage material issue")
        _, movement = await record_material_issue(session, gateway, pg_book[0], user, physical)
        material = ProductionMaterialIssuePostingInput(policy_id=policy_id, order_id=43,
            order_analytics="ORDER-43", department="SHOP", wms_movement_id=movement.id,
            posting_date=date(2026, 10, 31), account="43", warehouse="Main", sku="SYN-WIDGET", lot="LOT-1", quantity="1.00")
        prepared = await prepare_material_issue_posting(session, pg_book[0], "2026-10", material, production)
        assert prepared["inventory_cost"]["issue_cost_byn"] == "50.00"
        command = ProductionMaterialIssuePostingConfirmInput.model_validate({**material.model_dump(mode="json"),
            "basis_digest": prepared["basis_digest"], "digest": prepared["digest"]})
        material_entry = await confirm_material_issue_posting(session, pg_book[0], "2026-10", command, "tester")
        await session.commit()
        material_entry_id = material_entry.id
    downstream_id = await accepted_output(43, "SYN-WIDGET-2", "LOT-2", "1.00")
    async with factory() as session:
        await service.post(session, pg_book[0], PostingInput(source="production:late-wip:downstream",
            source_version=1, operation="manual", document_date="2026-10-31", operation_date="2026-10-31",
            posting_date="2026-10-31", policy_id=policy_id, rule_version="synthetic", explanation="Late source WIP",
            lines=[LineInput(account="20", side="debit", amount="20", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                   LineInput(account="60", side="credit", amount="20")]), "tester")
        revision = await confirm_output_cost_correction(session, pg_book[0], "2026-10",
                                                       await _output_cost_command(session, pg_book[0], original_id), "tester")
        await session.commit()
    async with factory() as session:
        lines = (await session.scalars(select(Line).where(Line.entry_id == revision.entry_id))).all()
        assert {(line.account_code, line.side, line.amount, tuple(sorted(line.dimensions.items()))) for line in lines} == {
            ("20", "credit", Decimal("20.00"), (("department", "SHOP"), ("order", "ORDER-42"))),
            ("43", "debit", Decimal("10.00"), (("lot", "LOT-1"), ("sku", "SYN-WIDGET"), ("warehouse", "Main"))),
            ("20", "debit", Decimal("10.00"), (("department", "SHOP"), ("order", "ORDER-43"))),
        }
        downstream_receipt = await session.get(ProductionOutputTransferReceipt, downstream_id)
        assert await output_transfer_source_state(session, downstream_receipt, "2026-10") == "changed"
        with pytest.raises(service.AccountingError, match="order 43"):
            await validate_output_transfers_for_close(session, pg_book[0], "2026-10")
        assert (await confirm_material_issue_posting(session, pg_book[0], "2026-10", command, "tester")).id == material_entry_id
        await session.commit()


    async with factory() as session:
        downstream_command = await _output_cost_command(session, pg_book[0], downstream_id)
        downstream_revision = await confirm_output_cost_correction(session, pg_book[0], "2026-10", downstream_command, "tester")
        await session.commit()
    async with factory() as session:
        await validate_output_transfers_for_close(session, pg_book[0], "2026-10")
        lines = (await session.scalars(select(Line).where(Line.entry_id == downstream_revision.entry_id))).all()
        assert {(line.account_code, line.side, line.amount, tuple(sorted(line.dimensions.items()))) for line in lines} == {
            ("20", "credit", Decimal("10.00"), (("department", "SHOP"), ("order", "ORDER-43"))),
            ("43", "debit", Decimal("10.00"), (("lot", "LOT-2"), ("sku", "SYN-WIDGET-2"), ("warehouse", "Main"))),
        }
        for sku, lot in (("SYN-WIDGET", "LOT-1"), ("SYN-WIDGET-2", "LOT-2")):
            stock = await inventory_cost.preview_issue(session, pg_book[0], InventoryIssuePreviewInput(
                policy_id=policy_id, posting_date=date(2026, 10, 31), account="43", warehouse="Main",
                sku=sku, lot=lot, quantity="1"))
            assert stock["book_quantity"] == "1.000000" and stock["book_value_byn"] == "60.00"
        assert (await confirm_material_issue_posting(session, pg_book[0], "2026-10", command, "tester")).id == material_entry_id
        await session.commit()


async def test_finished_goods_manual_layer_is_not_an_output_source(pg_factory, pg_book):
    policy_id = await _confirm_output(pg_factory, pg_book)
    async with pg_factory() as session:
        manual = PostingInput(
            source="manual:forged-fg", source_version=1, operation="manual", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic-manual-fg-v1", explanation="Synthetic unreceipted finished goods", lines=[
                LineInput(account="43", side="debit", amount="10.00", quantity="1",
                          dimensions={"warehouse": "Main", "sku": "FORGED", "lot": "LOT-F"}),
                LineInput(account="60", side="credit", amount="10.00", dimensions={}),
            ],
        )
        await service.post(session, pg_book[0], manual, "tester")
        with pytest.raises(service.AccountingError, match="no verified production output receipt"):
            await inventory_issues.prepare(session, pg_book[0], inventory_issues.InventoryIssueDocument(
                policy_id=policy_id, posting_date=date(2026, 10, 31), account="43", warehouse="Main",
                sku="FORGED", lot="LOT-F", quantity=Decimal("1"), source="issue:forged", source_version=1,
                document_date=date(2026, 10, 31), operation_date=date(2026, 10, 31), expense_account="90.4",
                explanation="Synthetic forged finished-goods issue",
            ))


@pytest.mark.parametrize("method", ["specific", "fifo", "weighted_average"])
async def test_unrelated_stale_output_does_not_block_selected_finished_goods(pg_factory, pg_book, method):
    policy_id = await _confirm_output(pg_factory, pg_book, method)

    class OtherProduction(SyntheticProduction):
        async def cost_orders(self, _session, _organization_id, _order_ids):
            return [{"order_id": 43, "product": "Other widget", "quantity": "1.00"}]

        async def output_reconciliation(self, _session, _organization_id, _order_id, _warehouse):
            return {"planned_quantity": "1.00", "confirmed_quantity": "1.00", "accepted_quantity": "1.00",
                    "rejected_quantity": "0.00", "pending_quantity": "0.00", "sku_code": "OTHER-WIDGET",
                    "unit": "шт", "lot": "LOT-2", "documents": [{"document_id": 102, "operation_date": "2026-10-10"}]}

    other = OtherProduction()
    command = ProductionOutputTransferConfirmInput.model_validate({
        "policy_id": policy_id, "order_id": 43, "analytical_order": "ORDER-43", "department": "SHOP",
        "warehouse": "Main", "posting_date": "2026-10-31", "output_document_ids": [102],
        "basis_digest": "0" * 64, "digest": "0" * 64,
    })
    async with pg_factory() as session:
        await service.post(session, pg_book[0], PostingInput(
            source="production:wip:43", source_version=1, operation="manual", document_date="2026-10-10",
            operation_date="2026-10-10", posting_date="2026-10-10", policy_id=policy_id,
            rule_version="synthetic-wip-other-v1", explanation="Synthetic other WIP", lines=[
                LineInput(account="20", side="debit", amount="10.00", dimensions={"department": "SHOP", "order": "ORDER-43"}),
                LineInput(account="60", side="credit", amount="10.00", dimensions={}),
            ],
        ), "tester")
        preview = await prepare_output_transfer(session, pg_book[0], "2026-10", command, other, object())
        command = ProductionOutputTransferConfirmInput.model_validate({**command.model_dump(mode="json"),
                                                                         "basis_digest": preview["basis_digest"], "digest": preview["digest"]})
        await session.commit()
    async with pg_factory() as session:
        from modules.accounting.production_output_transfer import confirm_output_transfer

        await confirm_output_transfer(session, pg_book[0], "2026-10", command, "tester", production=other,
                                      warehouse_gateway=object())
        await service.post(session, pg_book[0], PostingInput(
            source="production:late-cost:43", source_version=1, operation="manual", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic-late-other-v1", explanation="Synthetic other late WIP", lines=[
                LineInput(account="20", side="debit", amount="10.00", dimensions={"department": "SHOP", "order": "ORDER-43"}),
                LineInput(account="60", side="credit", amount="10.00", dimensions={}),
            ],
        ), "tester")
        assert (await sales.prepare(session, pg_book[0], sale_document(policy_id)))["cost"]["issue_cost_byn"] == "50.00"


async def test_output_trace_maps_second_fifo_lot_to_aggregate_expense(pg_factory, pg_book):
    policy_id = await _confirm_output(pg_factory, pg_book, "fifo")

    class OtherProduction(SyntheticProduction):
        async def cost_orders(self, _session, _organization_id, _order_ids):
            return [{"order_id": 43, "product": "Other widget", "quantity": "1.00"}]

        async def output_reconciliation(self, _session, _organization_id, _order_id, _warehouse):
            return {"planned_quantity": "1.00", "confirmed_quantity": "1.00", "accepted_quantity": "1.00",
                    "rejected_quantity": "0.00", "pending_quantity": "0.00", "sku_code": "SYN-WIDGET",
                    "unit": "шт", "lot": "LOT-2", "documents": [{"document_id": 102, "operation_date": "2026-10-10"}]}

    other = OtherProduction()
    command = ProductionOutputTransferConfirmInput.model_validate({
        "policy_id": policy_id, "order_id": 43, "analytical_order": "ORDER-43", "department": "SHOP",
        "warehouse": "Main", "posting_date": "2026-10-31", "output_document_ids": [102],
        "basis_digest": "0" * 64, "digest": "0" * 64,
    })
    async with pg_factory() as session:
        await service.post(session, pg_book[0], PostingInput(
            source="production:wip:43", source_version=1, operation="manual", document_date="2026-10-10",
            operation_date="2026-10-10", posting_date="2026-10-10", policy_id=policy_id,
            rule_version="synthetic-wip-other-v1", explanation="Synthetic other WIP", lines=[
                LineInput(account="20", side="debit", amount="50.00", dimensions={"department": "SHOP", "order": "ORDER-43"}),
                LineInput(account="60", side="credit", amount="50.00", dimensions={}),
            ],
        ), "tester")
        preview = await prepare_output_transfer(session, pg_book[0], "2026-10", command, other, object())
        command = ProductionOutputTransferConfirmInput.model_validate({**command.model_dump(mode="json"),
                                                                         "basis_digest": preview["basis_digest"], "digest": preview["digest"]})
        await session.commit()
    async with pg_factory() as session:
        from modules.accounting.production_output_transfer import confirm_output_transfer

        await confirm_output_transfer(session, pg_book[0], "2026-10", command, "tester", production=other,
                                      warehouse_gateway=object())
        await session.commit()
    async with pg_factory() as session:
        document = sales.SaleDocument.model_validate({**sale_document(policy_id).model_dump(mode="json"),
            "lot": "", "quantity": "3"})
        prepared = await sales.prepare(session, pg_book[0], document)
        assert prepared["cost"]["issue_cost_byn"] == "150.00"
        sale = await sales.confirm(session, pg_book[0], document,
            prepared["cost"]["basis_digest"], prepared["digest"], "tester")
        await session.commit()
        receipt = await session.scalar(select(ProductionOutputTransferReceipt).where(
            ProductionOutputTransferReceipt.organization_id == pg_book[0],
            ProductionOutputTransferReceipt.order_id == 43))
        traced = await trace_output_layer(session, pg_book[0], receipt, date(2026, 10, 31))
        assert traced["remaining_quantity"] == "0.000000"
        assert traced["remaining_value_byn"] == "0.00"
        assert len(traced["disposals"]) == 1
        disposal = traced["disposals"][0]
        assert disposal["entry_id"] == sale.id
        assert disposal["quantity"] == "1.000000"
        assert disposal["applied_cost_byn"] == "50.00"
        assert disposal["destination_account"] == "90.4"
        assert disposal["destination_dimensions"] == {}

@pytest.mark.parametrize("delta", [20, -20, 0])
async def test_output_revision_sql_checks_exact_destinations(pg_factory, pg_book, delta):
    """Exercise the real revision INSERT, including balanced forged alternatives."""
    import copy
    from uuid import uuid4

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from modules.accounting.models import Account, Entry, Line, ProductionOutputCostRevision

    policy_id = await _confirm_output(pg_factory, pg_book)
    async with pg_factory() as session:
        await _upgrade_output_cost_revision(session)
        doc = sale_document(policy_id)
        prepared = await sales.prepare(session, pg_book[0], doc)
        await sales.confirm(session, pg_book[0], doc, prepared["cost"]["basis_digest"], prepared["digest"], "tester")
        await service.post(session, pg_book[0], PostingInput(
            source="production:late-wip:matrix", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Late production cost", lines=[
                LineInput(account="20", side="debit" if delta > 0 else "credit", amount=str(abs(delta) or 20), dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60" if delta else "20", side="credit" if delta > 0 else "debit", amount=str(abs(delta) or 20),
                          dimensions={} if delta else {"department": "SHOP-2", "order": "ORDER-42"}),
            ]), "tester")
        await session.commit()
    async with pg_factory() as session:
        output = await session.scalar(select(ProductionOutputTransferReceipt).where(
            ProductionOutputTransferReceipt.organization_id == pg_book[0]))
        output_id = output.entry_id
        evidence = await session.scalar(text("SELECT accounting.output_cost_revision_evidence(:org,:entry,DATE '2026-10-31',NULL)"),
                                        {"org": pg_book[0], "entry": output_id})
        if delta:
            assert [(r["account"], r["side"], r["amount"]) for r in evidence["matrix"]] == [
                ("20", "credit" if delta > 0 else "debit", 20),
                ("43", "debit" if delta > 0 else "credit", 10),
                ("90.4", "debit" if delta > 0 else "credit", 10)]
        else:
            assert len(evidence["matrix"]) == 2
            assert {(r["dimensions"]["department"], r["side"], r["amount"]) for r in evidence["matrix"]} == {
                ("SHOP", "debit", 20), ("SHOP-2", "credit", 20)}


    async def insert_revision(change=None, sequence=1):
        async with pg_factory() as session:
            lines = copy.deepcopy(evidence["matrix"])
            if change == "account":
                lines[-1]["account"] = "60"
            elif change == "analytics":
                lines[1]["dimensions"]["lot" if delta else "department"] = "ANOTHER-LOT"
            posting = PostingInput(
                source=f"production:output-cost-revision:{pg_book[0]}:{output_id}:{sequence}",
                source_version=1, operation="production_output_cost_correction",
                document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
                policy_id=policy_id, rule_version="production-output-cost-revision-v1",
                explanation="Reviewed correction", correction_of=output_id,
                lines=[LineInput(**{**r, "amount": str(r["amount"])}) for r in lines])
            entry = Entry(**posting.model_dump(exclude={"lines"}), organization_id=pg_book[0],
                          digest=service.digest(posting), actor="tester")
            session.add(entry)
            await session.flush()
            for item in posting.lines:
                account = await session.scalar(select(Account).where(Account.organization_id == pg_book[0], Account.code == item.account))
                session.add(Line(**item.model_dump(exclude={"account"}), entry_id=entry.id, account_id=account.id,
                                 account_code=account.code, account_title=account.title, category=account.category, cash=account.cash))
            await session.flush()
            if change == "missing-receipt":
                await session.commit()
                return
            posting_json = posting.model_dump(mode="json")
            if change == "declared-quantity":
                posting_json["lines"][0]["quantity"] = "1.000000"
            session.add(ProductionOutputCostRevision(
                organization_id=pg_book[0], original_entry_id=output_id, sequence=sequence,
                previous_id=await session.scalar(select(ProductionOutputCostRevision.id).where(
                    ProductionOutputCostRevision.original_entry_id == output_id,
                    ProductionOutputCostRevision.sequence == sequence - 1)),
                entry_id=entry.id, month="2026-10", request_key=str(uuid4()),
                command={"original_entry_id": output_id, "posting_date": "2026-10-31"},
                preview={"ledger_evidence": evidence}, posting=posting_json, actor="tester"))
            if change == "late-lines":
                await session.flush()  # receipt guard already passed
                account = await session.scalar(select(Account).where(Account.organization_id == pg_book[0], Account.code == "60"))
                for side in ("debit", "credit"):
                    session.add(Line(entry_id=entry.id, account_id=account.id, account_code=account.code,
                        account_title=account.title, category=account.category, cash=account.cash,
                        side=side, amount=Decimal("1"), dimensions={}, currency="BYN"))
            await session.commit()

    with pytest.raises(DBAPIError, match="complete revision receipt"):
        await insert_revision("missing-receipt")
    for forged in ("account", "analytics", "late-lines", "declared-quantity"):
        with pytest.raises(DBAPIError, match="matrix differs"):
            await insert_revision(forged)
    await insert_revision()
    # Recompute from current ledger plus verified prior attribution; do not
    # charge the previous +20/-20 a second time.
    async with pg_factory() as session:
        unchanged = await session.scalar(text("SELECT accounting.output_cost_revision_evidence(:org,:entry,DATE '2026-10-31',NULL)"),
                                         {"org": pg_book[0], "entry": output_id})
        assert unchanged["matrix"] == []
        await service.post(session, pg_book[0], PostingInput(
            source="production:late-wip:second", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Second late cost", lines=[
                LineInput(account="20", side="debit", amount="20", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="20"),
            ]), "tester")
        await session.commit()
        evidence = await session.scalar(text("SELECT accounting.output_cost_revision_evidence(:org,:entry,DATE '2026-10-31',NULL)"),
                                        {"org": pg_book[0], "entry": output_id})
        assert [(r["account"], r["side"], r["amount"]) for r in evidence["matrix"]] == [
            ("20", "credit", 20), ("43", "debit", 10), ("90.4", "debit", 10)]
    await insert_revision(sequence=2)

async def test_output_revision_empty_matrix_records_no_fabricated_entry(pg_factory, pg_book):
    from uuid import uuid4

    from sqlalchemy import func, text
    from sqlalchemy.exc import DBAPIError

    from modules.accounting.models import Entry, ProductionOutputCostRevision

    await _confirm_output(pg_factory, pg_book)
    async with pg_factory() as session:
        await _upgrade_output_cost_revision(session)
        output = await session.scalar(select(ProductionOutputTransferReceipt).where(
            ProductionOutputTransferReceipt.organization_id == pg_book[0]))
        output_id = output.entry_id
        evidence = await session.scalar(text("SELECT accounting.output_cost_revision_evidence(:org,:entry,DATE '2026-10-31',NULL)"),
                                        {"org": pg_book[0], "entry": output_id})
        assert evidence["matrix"] == []
        before = await session.scalar(select(func.count()).select_from(Entry))
        await session.commit()
    # A zero-cost source acknowledgement must still bind every source row.
    async with pg_factory() as session:
        session.add(ProductionOutputCostRevision(
            organization_id=pg_book[0], original_entry_id=output_id, sequence=1,
            entry_id=None, month="2026-10", request_key=str(uuid4()),
            command={"original_entry_id": output_id, "posting_date": "2026-10-31"},
            preview={"ledger_evidence": {**evidence, "source_lines": []}}, posting=None, actor="tester"))
        with pytest.raises(DBAPIError, match="preview differs"):
            await session.commit()
    async with pg_factory() as session:
        revision = ProductionOutputCostRevision(
            organization_id=pg_book[0], original_entry_id=output_id, sequence=1,
            entry_id=None, month="2026-10", request_key=str(uuid4()),
            command={"original_entry_id": output_id, "posting_date": "2026-10-31"},
            preview={"ledger_evidence": evidence}, posting=None, actor="tester")
        session.add(revision)
        await session.commit()
        assert revision.registration_token > output_id
        assert await session.scalar(select(func.count()).select_from(Entry)) == before
