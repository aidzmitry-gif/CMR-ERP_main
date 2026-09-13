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
