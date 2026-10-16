# ruff: noqa: F811 -- imported fixtures are used by pytest parameter lookup.
"""Weighted-average output corrections retain pooled source contributions."""
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from modules.accounting import sales, service
from modules.accounting.models import ProductionOutputTransferReceipt
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
from modules.accounting.schemas import LineInput, PostingInput
from tests.accounting.test_finished_goods_inventory_postgres import sale_document
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_production_output_transfer_postgres import (
    SyntheticProduction,
    _seed_production_book,
    _seed_wip,
    _upgrade_group_guard,
)

pytestmark = pytest.mark.integration


async def _confirm(session, org_id, policy_id, order_id, lot, quantity="1.00"):
    class Output(SyntheticProduction):
        async def cost_orders(self, _session, _organization_id, _order_ids):
            return [{"order_id": order_id, "product": "Mixed pool", "quantity": quantity}]

        async def output_reconciliation(self, _session, _organization_id, _order_id, _warehouse):
            return {"planned_quantity": quantity, "confirmed_quantity": quantity, "accepted_quantity": quantity,
                    "rejected_quantity": "0.00", "pending_quantity": "0.00", "sku_code": "SYN-WIDGET",
                    "unit": "шт", "lot": lot, "documents": [{"document_id": order_id + 100, "operation_date": "2026-10-10"}]}

    production = Output()
    command = ProductionOutputTransferConfirmInput.model_validate({
        "policy_id": policy_id, "order_id": order_id, "analytical_order": f"ORDER-{order_id}",
        "department": "SHOP", "warehouse": "Main", "posting_date": "2026-10-31",
        "output_document_ids": [order_id + 100], "basis_digest": "0" * 64, "digest": "0" * 64,
    })
    preview = await prepare_output_transfer(session, org_id, "2026-10", command, production, object())
    command = command.model_copy(update={"basis_digest": preview["basis_digest"], "digest": preview["digest"]})
    return await confirm_output_transfer(session, org_id, "2026-10", command, "tester",
                                         production=production, warehouse_gateway=object())


@pytest.mark.parametrize("selected_lot", ["", "LOT-A"])
async def test_weighted_average_mixed_lot_output_revision_preserves_pool_contribution(pg_factory, pg_book, selected_lot):
    """A 50/B 100 pool sale at 75; A late +20 adds 10 expense and 10 to B."""
    policy_id = await _seed_production_book(pg_factory, pg_book, "weighted_average")
    await _seed_wip(pg_factory, pg_book, policy_id, [("SHOP", "ORDER-42", "50.00")])
    async with pg_factory() as session:
        await _upgrade_group_guard(session)
        first = await _confirm(session, pg_book[0], policy_id, 42, "LOT-A")
        await service.post(session, pg_book[0], PostingInput(
            source="production:wip:43", source_version=1, operation="manual", document_date="2026-10-10",
            operation_date="2026-10-10", posting_date="2026-10-10", policy_id=policy_id,
            rule_version="synthetic", explanation="Second weighted-average output", lines=[
                LineInput(account="20", side="debit", amount="100", dimensions={"department": "SHOP", "order": "ORDER-43"}),
                LineInput(account="60", side="credit", amount="100"),
            ]), "tester")
        await _confirm(session, pg_book[0], policy_id, 43, "LOT-B")
        sale = sales.SaleDocument.model_validate({**sale_document(policy_id).model_dump(mode="json"), "lot": selected_lot})
        prepared = await sales.prepare(session, pg_book[0], sale)
        assert prepared["cost"]["issue_cost_byn"] == "75.00"
        sold = await sales.confirm(session, pg_book[0], sale, prepared["cost"]["basis_digest"], prepared["digest"], "tester")
        await service.post(session, pg_book[0], PostingInput(
            source="production:late-wip:42", source_version=1, operation="manual", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic", explanation="Late WIP for A", lines=[
                LineInput(account="20", side="debit", amount="20", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="20"),
            ]), "tester")
        await session.commit()
    async with pg_factory() as session:
        replay = await sales.confirm(session, pg_book[0], sale, prepared["cost"]["basis_digest"], prepared["digest"], "tester")
        assert replay.id == sold.id
        receipt = await session.get(ProductionOutputTransferReceipt, first.id)
        command = ProductionOutputCostPreviewInput(
            original_entry_id=receipt.entry_id, posting_date=date(2026, 10, 31), request_evidence="Mixed-pool correction")
        preview = await preview_output_cost_correction(session, pg_book[0], "2026-10", command)
        assert sorted((r["account"],r["side"],str(r["amount"]),r["dimensions"].get("lot"))
                      for r in preview["posting_document"]["lines"]) == [
            ("20", "credit", "20.00", None), ("43", "debit", "10.00", "LOT-B"),
            ("90.4", "debit", "10.00", None)]
        await confirm_output_cost_correction(session, pg_book[0], "2026-10",
            ProductionOutputCostConfirmInput(**command.model_dump(), request_key=uuid4(),
                basis_digest=preview["basis_digest"]), "tester")
        await session.commit()
    async with pg_factory() as session:
        second = sales.SaleDocument.model_validate({**sale.model_dump(mode="json"), "source":"sale:fg:2", "lot":"LOT-B",
            "buyer_dimensions":{**sale.buyer_dimensions,"settlement_document":"sale:fg:2"}})
        prepared_second = await sales.prepare(session, pg_book[0], second)
        assert prepared_second["cost"]["issue_cost_byn"] == "85.00"
        assert (await sales.confirm(session, pg_book[0], sale, prepared["cost"]["basis_digest"],
                                    prepared["digest"], "tester")).id == sold.id
        sold_second = await sales.confirm(session, pg_book[0], second, prepared_second["cost"]["basis_digest"],
                                          prepared_second["digest"], "tester")
        await service.post(session, pg_book[0], PostingInput(
            source="production:late-wip:42:second", source_version=1, operation="manual", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic", explanation="Second late WIP after both sales", lines=[
                LineInput(account="20", side="debit", amount="20", dimensions={"department":"SHOP","order":"ORDER-42"}),
                LineInput(account="60", side="credit", amount="20"),
            ]), "tester")
        await session.commit()
    async with pg_factory() as session:
        next_preview = await preview_output_cost_correction(session, pg_book[0], "2026-10", command)
        assert sorted((row["destination"]["entry_id"],row["delta_cents"])
                      for row in next_preview["destinations"] if row["destination"]) == [
            (sold.id,1000),(sold_second.id,1000)]
        assert not any(row["account"]=="43" for row in next_preview["posting_document"]["lines"])
        await confirm_output_cost_correction(session, pg_book[0], "2026-10",
            ProductionOutputCostConfirmInput(**command.model_dump(),request_key=uuid4(),
                basis_digest=next_preview["basis_digest"]),"tester")
        await session.commit()
    async with pg_factory() as session:
        for doc, saved_preview, entry in [(sale,prepared,sold),(second,prepared_second,sold_second)]:
            assert (await sales.confirm(session,pg_book[0],doc,saved_preview["cost"]["basis_digest"],
                saved_preview["digest"],"tester")).id==entry.id
        no_change = await preview_output_cost_correction(session, pg_book[0], "2026-10", command)
        assert no_change["posting_document"] is None
        assert Decimal(no_change["desired_total_byn"]) == Decimal("90")


@pytest.mark.parametrize("negative, future_cost", [(False,"190.00"),(True,"176.66")])
async def test_weighted_average_late_a_uses_largest_remainder_across_two_sales_and_c(pg_factory, pg_book, negative, future_cost):
    """A late +20 must allocate 10.00/3.33/6.67, not independently rounded source totals."""
    policy_id = await _seed_production_book(pg_factory, pg_book, "weighted_average")
    await _seed_wip(pg_factory, pg_book, policy_id, [("SHOP", "ORDER-42", "50.00")])
    async with pg_factory() as session:
        await _upgrade_group_guard(session)
        a = await _confirm(session, pg_book[0], policy_id, 42, "LOT-A")
        await service.post(session, pg_book[0], PostingInput(source="production:wip:43", source_version=1,
            operation="manual", document_date="2026-10-10", operation_date="2026-10-10", posting_date="2026-10-10",
            policy_id=policy_id, rule_version="synthetic", explanation="B cost", lines=[
                LineInput(account="20", side="debit", amount="100", dimensions={"department":"SHOP","order":"ORDER-43"}),
                LineInput(account="60", side="credit", amount="100")]), "tester")
        await _confirm(session, pg_book[0], policy_id, 43, "LOT-B")
        sale_a = sales.SaleDocument.model_validate({**sale_document(policy_id).model_dump(mode="json"), "lot":""})
        p1 = await sales.prepare(session, pg_book[0], sale_a)
        assert p1["cost"]["issue_cost_byn"] == "75.00"
        e1 = await sales.confirm(session, pg_book[0], sale_a, p1["cost"]["basis_digest"], p1["digest"], "tester")
        await service.post(session, pg_book[0], PostingInput(source="production:wip:44", source_version=1,
            operation="manual", document_date="2026-10-10", operation_date="2026-10-10", posting_date="2026-10-10",
            policy_id=policy_id, rule_version="synthetic", explanation="C cost", lines=[
                LineInput(account="20", side="debit", amount="200", dimensions={"department":"SHOP","order":"ORDER-44"}),
                LineInput(account="60", side="credit", amount="200")]), "tester")
        await _confirm(session, pg_book[0], policy_id, 44, "LOT-C", "2.00")
        sale_b = sales.SaleDocument.model_validate({**sale_document(policy_id).model_dump(mode="json"), "source":"sale:fg:b",
            "lot":"", "buyer_dimensions":{**sale_document(policy_id).buyer_dimensions,"settlement_document":"sale:fg:b"}})
        p2 = await sales.prepare(session, pg_book[0], sale_b)
        assert p2["cost"]["issue_cost_byn"] == "91.67"
        e2 = await sales.confirm(session, pg_book[0], sale_b, p2["cost"]["basis_digest"], p2["digest"], "tester")
        await service.post(session, pg_book[0], PostingInput(source="production:late-wip:a", source_version=1,
            operation="manual", document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="A late 20", lines=[
                LineInput(account="20", side="credit" if negative else "debit", amount="20", dimensions={"department":"SHOP","order":"ORDER-42"}),
                LineInput(account="60", side="debit" if negative else "credit", amount="20")]), "tester")
        await session.commit()
    async with pg_factory() as session:
        command = ProductionOutputCostPreviewInput(original_entry_id=a.id, posting_date=date(2026,10,31), request_evidence="A late")
        preview = await preview_output_cost_correction(session, pg_book[0], "2026-10", command)
        sign = -1 if negative else 1
        assert {row["destination"]["entry_id"]:row["delta_cents"]
                for row in preview["destinations"] if row["destination"]} == {e1.id:sign*1000,e2.id:sign*333}
        assert [row["delta_cents"] for row in preview["destinations"] if row["kind"]=="remaining"] == [sign*667]
        await confirm_output_cost_correction(session, pg_book[0], "2026-10", ProductionOutputCostConfirmInput(
            **command.model_dump(), request_key=uuid4(), basis_digest=preview["basis_digest"]), "tester")
        await session.commit()
    async with pg_factory() as session:
        sale_c = sales.SaleDocument.model_validate({**sale_document(policy_id).model_dump(mode="json"), "source":"sale:fg:c",
            "lot":"", "quantity":"2", "buyer_dimensions":{**sale_document(policy_id).buyer_dimensions,"settlement_document":"sale:fg:c"}})
        p3 = await sales.prepare(session, pg_book[0], sale_c)
        assert p3["cost"]["issue_cost_byn"] == future_cost
        assert (await sales.confirm(session, pg_book[0], sale_a, p1["cost"]["basis_digest"], p1["digest"], "tester")).id == e1.id
        assert (await sales.confirm(session, pg_book[0], sale_b, p2["cost"]["basis_digest"], p2["digest"], "tester")).id == e2.id
