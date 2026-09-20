"""PostgreSQL guards for immutable expense-article attribution receipts."""

import runpy
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import expenses
from modules.accounting.expense_schemas import (
    CatalogCommand,
    ExpenseAttributionCommand,
    ExpenseAttributionPreview,
)
from modules.accounting.models import Account, Entry, Line
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401


pytestmark = pytest.mark.integration


async def apply_attribution_migration(session):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    connection = await session.connection()
    migration = runpy.run_path(str(Path("migrations/versions/0156_expense_article_attribution.py")))

    def upgrade(sync_connection):
        with Operations.context(MigrationContext.configure(sync_connection)):
            migration["upgrade"]()

    await connection.run_sync(upgrade)


async def test_postgres_attribution_guard_accepts_only_immutable_receipt(pg_factory, pg_book):  # noqa: F811
    async with pg_factory() as session:
        await apply_attribution_migration(session)
        catalog = await expenses.execute(
            session,
            pg_book[0],
            "tester",
            "catalog",
            CatalogCommand(
                request_key=uuid4(), expected_revision=0, evidence="Synthetic PG catalog", action="template"
            ),
        )
        account = await session.scalar(
            select(Account).where(Account.organization_id == pg_book[0], Account.code == "90.4")
        )
        counter_account = await session.scalar(
            select(Account).where(Account.organization_id == pg_book[0], Account.code == "60")
        )
        entry = Entry(
            organization_id=pg_book[0], source="expense-attribution-pg", source_version=1,
            operation="manual", document_date=date(2026, 10, 5), operation_date=date(2026, 10, 5),
            posting_date=date(2026, 10, 5), policy_id=pg_book[1], rule_version="test",
            explanation="Synthetic PG attribution source", opening=False, correction_of=None,
            digest="c" * 64, actor="tester",
        )
        session.add(entry)
        await session.flush()
        line = Line(
            entry_id=entry.id, account_id=account.id, account_code=account.code,
            account_title=account.title, category="expense", cash=False, side="debit",
            amount=Decimal("6.00"), dimensions={}, currency="BYN",
        )
        session.add_all([line, Line(
            entry_id=entry.id, account_id=counter_account.id, account_code=counter_account.code,
            account_title=counter_account.title, category="liability", cash=False, side="credit",
            amount=Decimal("6.00"), dimensions={}, currency="BYN",
        )])
        await session.flush()
        article_id = catalog["result"]["articles"][0]["id"]
        preview = await expenses.preview_attribution(
            session,
            pg_book[0],
            ExpenseAttributionPreview(
                source_line_id=line.id, article_id=article_id, effective_date=date(2026, 10, 5)
            ),
        )
        receipt = await expenses.confirm_attribution(
            session,
            pg_book[0],
            "tester",
            ExpenseAttributionCommand(
                request_key=uuid4(), source_line_id=line.id, article_id=article_id,
                effective_date=date(2026, 10, 5), expected_basis_digest=preview["basis_digest"],
                evidence="Synthetic PG primary evidence", explanation="Synthetic PG manual attribution",
            ),
        )
        assert receipt["result"]["source_line_id"] == line.id
        await session.commit()
    for sql in (
        "UPDATE accounting.expense_article_attribution SET evidence=evidence",
        "DELETE FROM accounting.expense_article_attribution",
        "TRUNCATE accounting.expense_article_attribution",
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                async with session.begin_nested():
                    await session.execute(text(sql))


def test_attribution_migration_is_forward_and_declares_database_guards():
    migration = Path("migrations/versions/0156_expense_article_attribution.py").read_text(encoding="utf-8")
    assert 'down_revision = "0155"' in migration
    assert "guard_expense_article_attribution" in migration
    assert "immutable_expense_article_attribution" in migration
    assert "source period is closed" in migration
