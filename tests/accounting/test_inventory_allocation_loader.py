# ruff: noqa: F811 -- shared integration fixtures are imported by name
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from modules.accounting import inventory_cost, inventory_issues, models, service
from modules.accounting.inventory_allocation_loader import (
    _replaced_credit_line_ids,
    load_authenticated_inventory_dispositions,
)
from modules.accounting.schemas import InventoryIssueDocument, InventoryIssuePreviewInput
from modules.accounting.zero_value_disposals import InventoryDispositionAllocation
from tests.accounting.test_inventory_cost import move
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401


@pytest.mark.parametrize("scope", ["", "B"])
def test_fifo_replays_complete_packet_before_requested_lot_filter(scope):
    from dataclasses import replace

    from modules.accounting.inventory_allocation_loader import (
        AuthenticatedInventoryDisposition,
        _snapshot,
        _snapshot_digest,
    )
    from tests.accounting.test_inventory_zero_value_layers import row

    day = date(2026, 10, 3)
    def dims(lot):
        return {"warehouse": "MAIN", "sku": "A", "lot": lot}
    rows = [row(1, 11, date(2026, 10, 1), quantity=1, amount=10, dimensions=dims("A")),
            row(2, 21, date(2026, 10, 2), quantity=2, amount=40, dimensions=dims("B"))]
    origins = [(2, 21, "B", "20.00")] if scope else [(1, 11, "A", "10.00"), (2, 21, "B", "20.00")]
    allocation = InventoryDispositionAllocation.model_validate({
        "allocation_version": 1, "valuation_method": "fifo", "quantity": str(len(origins)),
        "amount_byn": "20.00" if scope else "30.00", "layers": [
            {"source_entry_id": eid, "source_line_id": lid, "inventory_account": "43",
             "inventory_dimensions": dims(lot), "quantity": "1", "amount_byn": amount}
            for eid, lid, lot, amount in origins]})
    credits = tuple(31 + index for index in range(len(origins)))
    for line_id, (_, _, lot, amount) in zip(credits, origins, strict=True):
        rows.append(row(3, line_id, day, quantity=1, amount=amount, side="credit", dimensions=dims(lot), operation="inventory_issue"))
    snapshot = _snapshot(3, 3, 1, day, "source:3", 1, allocation, credits, scope)
    event = AuthenticatedInventoryDisposition(3, 3, 1, day, "source:3", 1, allocation, credits, _snapshot_digest(snapshot), scope)
    kwargs = dict(method="fifo", authenticated_dispositions=(event,), organization_id=1, inventory_account="43")
    remaining, _ = inventory_cost._valuation_layers(rows, dims("B"), day, **kwargs)
    assert [(layer["lot"], layer["quantity"], layer["amount"]) for layer in remaining] == [("B", Decimal(1), Decimal(20))]
    with pytest.raises(service.AccountingError, match="duplicated"):
        inventory_cost._valuation_layers(rows, dims("B"), day, **{**kwargs, "authenticated_dispositions": (event, event)})
    with pytest.raises(service.AccountingError, match="missing"):
        inventory_cost._valuation_layers(rows[:-1], dims("B"), day, **kwargs)
    with pytest.raises(service.AccountingError, match="snapshot changed"):
        inventory_cost._valuation_layers(rows, dims("B"), day, **{**kwargs, "authenticated_dispositions": (replace(event, selection_lot="changed"),)})
    prior, _ = inventory_cost._valuation_layers(rows, dims("B"), day, before_registration_token=3, **kwargs)
    assert [(layer["quantity"], layer["amount"]) for layer in prior] == [(Decimal(2), Decimal(40))]


def test_ordered_credit_replacement_allows_identical_shapes_from_distinct_origins():
    allocation = InventoryDispositionAllocation.model_validate({"allocation_version": 1, "valuation_method": "fifo",
        "quantity": "2", "amount_byn": "10.00", "layers": [
            {"source_entry_id": 1, "source_line_id": 11, "inventory_account": "41",
             "inventory_dimensions": {"warehouse": "W", "sku": "S", "lot": "L"}, "quantity": "1", "amount_byn": "5.00"},
            {"source_entry_id": 2, "source_line_id": 21, "inventory_account": "41",
             "inventory_dimensions": {"warehouse": "W", "sku": "S", "lot": "L"}, "quantity": "1", "amount_byn": "5.00"},
        ]})
    lines = [SimpleNamespace(id=31, side="credit", account_code="41", quantity=Decimal("1"), amount=Decimal("5"),
                             dimensions={"warehouse": "W", "sku": "S", "lot": "L"}, currency="BYN", category="asset", cash=False),
             SimpleNamespace(id=32, side="credit", account_code="41", quantity=Decimal("1"), amount=Decimal("5"),
                             dimensions={"warehouse": "W", "sku": "S", "lot": "L"}, currency="BYN", category="asset", cash=False)]
    assert _replaced_credit_line_ids(lines, "41", allocation) == (31, 32)


@pytest.mark.integration
async def test_saved_mixed_weighted_receipt_loader_replays_zero_portion_once(pg_factory, pg_book, posting):
    """Synthetic immutable mixed-cent receipt -> loader -> next weighted issue replay."""
    async with pg_factory() as session:
        policy_id = (await session.scalar(select(func.max(models.Policy.id))) or 0) + 1
        account_id = (await session.scalar(select(func.max(models.Account.id))) or 0) + 1
        policy = models.Policy(id=policy_id, organization_id=pg_book[0], effective_from=date(2026, 2, 1),
            reference="Synthetic weighted-average", inventory_method="weighted_average", allocation_basis="direct_cost",
            depreciation_method="straight_line", normative_reference="Synthetic", normative_verified=False,
            approved_by="tester")
        session.add_all([policy, models.Account(id=account_id, organization_id=pg_book[0], code="41.2",
            title="Quantitative goods", category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
            currency_tracking=True, quantity_tracking=True, cash=False, normative_ref="synthetic")])
        await session.commit()
        book = (pg_book[0], policy_id)
        await move(session, book, posting, "allocation-old", "1", "0.01", day="2026-09-01", lot="old")
        await move(session, book, posting, "allocation-new", "2", "0.01", day="2026-09-02", lot="new")
        document = InventoryIssueDocument(source="allocation-weighted-cent", source_version=1,
            document_date="2026-09-03", operation_date="2026-09-03", posting_date="2026-09-03", policy_id=policy_id,
            account="41.2", warehouse="W", sku="SKU", lot="", quantity="2", expense_account="90.4",
            expense_dimensions={}, explanation="Synthetic explicit allocation")
        rows = (await session.execute(select(models.Entry, models.Line).join(models.Line, models.Line.entry_id == models.Entry.id).where(
            models.Entry.organization_id == pg_book[0], models.Line.account_code == "41.2").order_by(
            models.Entry.posting_date, models.Entry.id, models.Line.id))).all()
        preview = InventoryIssuePreviewInput(**document.model_dump(include=set(InventoryIssuePreviewInput.model_fields)))
        cost = inventory_cost.issue_result(policy, rows, pg_book[0], preview,
                                           include_source_identity=True)
        cost["source_allocation_version"] = 1
        assert [layer["amount_byn"] for layer in cost["inventory_layers"]] == ["0.01", "0.00"]
        package = inventory_issues.posting_for(document, cost)
        package = package.model_copy(update={"lines": [line for line in package.lines if line.amount > 0]})
        entry = await service.post(session, pg_book[0], package, "tester", inventory_issue=True)
        session.add(models.InventoryIssueReceipt(entry_id=entry.id, organization_id=pg_book[0],
            command=document.model_dump(mode="json"), cost=json.loads(json.dumps(cost, default=str)), posting=package.model_dump(mode="json"),
            digest=service.digest(package), actor="tester"))
        await session.commit()

        events = await load_authenticated_inventory_dispositions(session, pg_book[0])
        assert len(events) == 1 and events[0].entry_id == entry.id
        next_document = document.model_copy(update={
            "source": "allocation-next-weighted", "posting_date": date(2026, 9, 4),
            "document_date": date(2026, 9, 4), "operation_date": date(2026, 9, 4), "quantity": Decimal("1"),
        })
        next_request = InventoryIssuePreviewInput(**next_document.model_dump(include=set(InventoryIssuePreviewInput.model_fields)))
        replay_policy, rows, verified, finished_goods = await inventory_cost._inventory_rows(session, pg_book[0], next_request)
        replayed = inventory_cost.issue_result(replay_policy, rows, pg_book[0], next_request,
            verified_output_lines=verified, finished_goods=finished_goods, authenticated_dispositions=events)
        assert replayed["issue_cost_byn"] == "0.01"
