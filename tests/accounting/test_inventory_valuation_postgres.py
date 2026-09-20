"""PostgreSQL proof that policy-selected multi-layer valuation survives posting."""
# ruff: noqa: F811 -- shared integration fixtures are imported by name
from datetime import date

import pytest
from sqlalchemy import func, select

from modules.accounting import inventory_issues, models, service
from modules.accounting.schemas import InventoryIssueDocument
from tests.accounting.test_inventory_cost import move
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401


@pytest.mark.integration
async def test_fifo_issue_preview_and_confirm_preserve_layers_in_postgres(pg_factory, pg_book, posting):
    async with pg_factory() as session:
        # `pg_book` copies the seeded policy with an explicit id and policy
        # history is immutable, so append a later version with a safe explicit
        # id rather than mutating the fixture row or relying on its sequence.
        next_policy_id = (await session.scalar(select(func.max(models.Policy.id))) or 0) + 1
        policy = models.Policy(
            id=next_policy_id, organization_id=pg_book[0], effective_from=date(2026, 2, 1),
            reference="Synthetic FIFO", inventory_method="fifo", allocation_basis="direct_cost",
            depreciation_method="straight_line", normative_reference="Synthetic",
            normative_verified=False, approved_by="tester",
        )
        session.add(policy)
        await session.flush()
        # The shared fixture copies accounts with explicit ids while leaving
        # the PostgreSQL sequence at its initial value.  Seed the quantitative
        # account with an explicit disposable id so the helper does not make a
        # sequence-backed insert that collides with id 1.
        session.add(models.Account(
            id=1000, organization_id=pg_book[0], code="41.2", title="Quantitative goods",
            category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
            currency_tracking=True, quantity_tracking=True, cash=False, normative_ref="synthetic",
        ))
        await session.commit()
        book = (pg_book[0], policy.id)
        await move(session, book, posting, "old-receipt", "3", "10.00", day="2026-09-01", lot="old")
        await move(session, book, posting, "new-receipt", "2", "20.00", day="2026-09-02", lot="new")
        document = InventoryIssueDocument(
            source="fifo-pg-issue", source_version=1, document_date="2026-09-03", operation_date="2026-09-03",
            posting_date="2026-09-03", policy_id=policy.id, account="41.2", warehouse="W", sku="SKU", lot="",
            quantity="4", expense_account="90.4", expense_dimensions={}, explanation="Synthetic FIFO issue",
        )
        cost, posting_input = await inventory_issues.prepare(session, pg_book[0], document)
        assert cost["method"] == "fifo" and cost["issue_cost_byn"] == "20.00"
        assert [line.dimensions["lot"] for line in posting_input.lines if line.side == "credit"] == ["old", "new"]
        entry = await inventory_issues.confirm(session, pg_book[0], document, cost["basis_digest"], service.digest(posting_input), "tester")
        await session.commit()
        lines = (await session.scalars(select(models.Line).where(models.Line.entry_id == entry.id).order_by(models.Line.id))).all()
        assert len(lines) == 3
        assert [line.dimensions.get("lot") for line in lines if line.side == "credit"] == ["old", "new"]

@pytest.mark.integration
@pytest.mark.parametrize("first_lot", ["", "new"])
async def test_weighted_average_remaining_value_matches_posted_credits(pg_factory, pg_book, posting, first_lot):
    """50 + 100 -> two committed 75 issues, including explicitly selected lot."""
    async with pg_factory() as session:
        next_policy_id = (await session.scalar(select(func.max(models.Policy.id))) or 0) + 1
        policy = models.Policy(id=next_policy_id, organization_id=pg_book[0], effective_from=date(2026, 2, 1),
            reference="Synthetic average", inventory_method="weighted_average", allocation_basis="direct_cost",
            depreciation_method="straight_line", normative_reference="Synthetic", normative_verified=False, approved_by="tester")
        session.add(policy)
        session.add(models.Account(id=1000, organization_id=pg_book[0], code="41.2", title="Quantitative goods",
            category="asset", valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=True,
            quantity_tracking=True, cash=False, normative_ref="synthetic"))
        await session.commit()
        book = (pg_book[0], policy.id)
        await move(session, book, posting, "old-receipt", "1", "50.00", day="2026-09-01", lot="old")
        await move(session, book, posting, "new-receipt", "1", "100.00", day="2026-09-02", lot="new")
        document = InventoryIssueDocument(source="average-first", source_version=1,
            document_date="2026-09-03", operation_date="2026-09-03", posting_date="2026-09-03",
            policy_id=policy.id, account="41.2", warehouse="W", sku="SKU", lot=first_lot,
            quantity="1", expense_account="90.4", expense_dimensions={}, explanation="First average issue")
        prepared, package = await inventory_issues.prepare(session, pg_book[0], document)
        assert prepared["issue_cost_byn"] == "75.00"
        first = await inventory_issues.confirm(session, pg_book[0], document,
            prepared["basis_digest"], service.digest(package), "tester")
        await session.commit()
        first_id = first.id
    async with pg_factory() as session:
        second_doc = document.model_copy(update={"source": "average-second", "lot": "old" if first_lot else ""})
        after, after_package = await inventory_issues.prepare(session, pg_book[0], second_doc)
        assert after["book_quantity"] == "1.000000"
        assert after["book_value_byn"] == after["issue_cost_byn"] == "75.00"
        await inventory_issues.confirm(session, pg_book[0], second_doc, after["basis_digest"], service.digest(after_package), "tester")
        await session.commit()
    async with pg_factory() as session:
        replay = await inventory_issues.confirm(session, pg_book[0], document,
            prepared["basis_digest"], service.digest(package), "tester")
        assert replay.id == first_id
        lines = (await session.scalars(select(models.Line).join(models.Entry, models.Entry.id == models.Line.entry_id).where(
            models.Entry.organization_id == pg_book[0], models.Line.account_code == "41.2"))).all()
        assert sum(line.amount if line.side == "debit" else -line.amount for line in lines) == 0
        assert sum(line.quantity if line.side == "debit" else -line.quantity for line in lines) == 0
        from modules.accounting.inventory_cost import available_lots
        from modules.accounting.schemas import InventoryLotQuery

        empty = await available_lots(session, pg_book[0], InventoryLotQuery(
            policy_id=policy.id, posting_date="2026-09-03", account="41.2", warehouse="W", sku="SKU"))
        assert all(row["book_quantity"] == "0.000000" and row["book_value_byn"] == "0.00"
                   and not row["selectable"] for row in empty["lots"])
