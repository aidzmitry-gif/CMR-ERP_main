"""Historical receipt replay across a real PostgreSQL period lock."""
# ruff: noqa: F811 -- imported shared fixtures
import pytest
from sqlalchemy import func, select, text

from modules.accounting import inventory_issues, models, sales, service
from modules.accounting.schemas import CloseInput, InventoryIssueDocument
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_sales import setup_sale


@pytest.mark.parametrize("kind", ["sale", "issue"])
async def test_exact_inventory_replay_after_closed_month(pg_factory, pg_book, posting, kind):
    workflow = sales if kind == "sale" else inventory_issues
    async with pg_factory() as session:
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account','id'), (SELECT max(id) FROM accounting.account))"))
        # Leave stock available so the new-command rejection proves the period
        # guard specifically, rather than an earlier insufficient-stock check.
        raw = await setup_sale(session, pg_book, posting, quantity="1")
        document = (sales.SaleDocument.model_validate(raw) if kind == "sale" else
            InventoryIssueDocument.model_validate({key: value for key, value in raw.items() if key in InventoryIssueDocument.model_fields}))
        prepared = await workflow.prepare(session, pg_book[0], document)
        if kind == "sale":
            basis, digest = prepared["cost"]["basis_digest"], prepared["digest"]
        else:
            basis, digest = prepared[0]["basis_digest"], service.digest(prepared[1])
        entry = await workflow.confirm(session, pg_book[0], document, basis, digest, "tester")
        entry_id = entry.id
        await session.commit()
        period = await service.period_for(session, pg_book[0], "2026-09")
        # Shared book is explicitly synthetic and its policy is marked verified
        # only for exercising period guards; this is not regulatory acceptance.
        await service.close_period(session, pg_book[0], "2026-09", CloseInput(
            expected_generation=period.generation,
            evidence={step: "Synthetic checked period control" for step in service.CLOSE_STEPS}), "tester")
        await session.commit()
        count = await session.scalar(select(func.count()).select_from(models.Entry))
    async with pg_factory() as session:
        repeated = await workflow.confirm(session, pg_book[0], document, basis, digest, "tester")
        assert repeated.id == entry_id
        await session.commit()
        assert (await service.period_for(session, pg_book[0], "2026-09")).closed
        assert await session.scalar(select(func.count()).select_from(models.Entry)) == count
        receipt_type = models.InventorySaleReceipt if kind == "sale" else models.InventoryIssueReceipt
        assert await session.scalar(select(func.count()).select_from(receipt_type)) == 1
        with pytest.raises(service.AccountingError, match="already posted with different content"):
            await workflow.confirm(session, pg_book[0], document.model_copy(update={"explanation": "Changed"}), basis, digest, "tester")
        with pytest.raises(service.AccountingError, match="[Cc]losed"):
            await workflow.confirm(session, pg_book[0], document.model_copy(update={"source": "new-after-close"}), basis, digest, "tester")
        assert await session.scalar(select(func.count()).select_from(models.Entry)) == count
