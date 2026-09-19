# ruff: noqa: F811 -- imported fixtures are used by pytest parameter lookup.
"""PostgreSQL evidence for policy-bound finished-goods disposal."""
from datetime import date
from decimal import Decimal

import pytest

from modules.accounting import inventory_cost, inventory_issues, sales, service
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

pytestmark = pytest.mark.integration


async def _confirm_output(factory, book):
    policy_id = await _seed_production_book(factory, book)
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


async def test_unrelated_stale_output_does_not_block_selected_finished_goods(pg_factory, pg_book):
    policy_id = await _confirm_output(pg_factory, pg_book)

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
