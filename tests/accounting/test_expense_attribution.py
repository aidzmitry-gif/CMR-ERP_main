"""Append-only manual attribution of visible unclassified expense lines."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from modules.accounting import expenses
from modules.accounting.expense_models import ExpenseArticleAttribution
from modules.accounting.expense_schemas import (
    CatalogCommand,
    ExpenseAttributionCommand,
    ExpenseAttributionPreview,
)
from modules.accounting.models import Account, Entry, Line, Organization, Period, Policy


async def source_expense(db, book, *, dimensions=None, posting_date=date(2026, 10, 5)):
    current = await expenses.catalog(db, book[0])
    if current["articles"]:
        catalog = {"result": current}
    else:
        catalog = await expenses.execute(
            db,
            book[0],
            "tester",
            "catalog",
            CatalogCommand(
                request_key=uuid4(), expected_revision=0, evidence="Synthetic expense catalog",
                action="template",
            ),
        )
    policy = await db.get(Policy, book[1])
    account = await db.scalar(
        select(Account).where(Account.organization_id == book[0], Account.code == "90.4")
    )
    entry = Entry(
        organization_id=book[0], source=f"expense-attribution:{uuid4()}", source_version=1,
        operation="manual", document_date=posting_date, operation_date=posting_date,
        posting_date=posting_date, policy_id=policy.id, rule_version="test",
        explanation="Synthetic unmatched expense", opening=False, correction_of=None,
        digest="a" * 64, actor="tester",
    )
    db.add(entry)
    await db.flush()
    line = Line(
        entry_id=entry.id, account_id=account.id, account_code=account.code,
        account_title=account.title, category="expense", cash=False, side="debit",
        amount=Decimal("12.50"), dimensions=dimensions or {}, currency="BYN",
    )
    db.add(line)
    await db.flush()
    return catalog["result"]["articles"][0], entry, line


async def preview(db, org_id, line, article_id):
    return await expenses.preview_attribution(
        db,
        org_id,
        ExpenseAttributionPreview(
            source_line_id=line.id, article_id=article_id, effective_date=line_entry_date(line)
        ),
    )


def line_entry_date(line):
    # Fixtures use one October source date; confirmation itself verifies the real entry date.
    return date(2026, 10, 5)


def command(line, article_id, basis_digest, *, request_key=None):
    return ExpenseAttributionCommand(
        request_key=request_key or uuid4(), source_line_id=line.id, article_id=article_id,
        effective_date=line_entry_date(line), expected_basis_digest=basis_digest,
        evidence="Первичный документ проверен бухгалтером",
        explanation="Ручное разнесение видимой нераспознанной строки",
    )


async def test_attribution_overlays_actuals_and_preserves_posted_line(db, book):
    article, _entry, line = await source_expense(db, book)
    original_dimensions = deepcopy(line.dimensions)
    before = await expenses.actuals(db, book[0], 2026, 10, "accrual")
    assert before["matched_lines"] == 0 and before["unmatched_lines"] == 1

    basis = await preview(db, book[0], line, article["id"])
    assert await db.scalar(
        select(Period).where(Period.organization_id == book[0], Period.month == "2026-10")
    ) is None
    data = command(line, article["id"], basis["basis_digest"])
    receipt = await expenses.confirm_attribution(db, book[0], "tester", data)
    assert await expenses.confirm_attribution(db, book[0], "tester", data) == receipt

    row = await db.scalar(select(ExpenseArticleAttribution))
    assert row.source_line_id == line.id and row.supersedes_id is None
    assert row.receipt == receipt
    assert line.dimensions == original_dimensions
    after = await expenses.actuals(db, book[0], 2026, 10, "accrual")
    register = await expenses.unmatched_actuals(db, book[0], 2026, 10, "accrual")
    assert after["coverage"] == "complete" and after["amount"] == "12.50"
    assert after["rows"][0]["article_id"] == article["id"]
    assert register["items"] == []
    with pytest.raises(expenses.Conflict, match="UUID"):
        await expenses.confirm_attribution(db, book[0], "other", data)


async def test_attribution_successor_reclassifies_open_period_without_rewriting_history(db, book):
    article, _entry, line = await source_expense(db, book)
    first_preview = await preview(db, book[0], line, article["id"])
    first = await expenses.confirm_attribution(
        db, book[0], "tester", command(line, article["id"], first_preview["basis_digest"])
    )
    catalog = await expenses.catalog(db, book[0])
    extra = await expenses.execute(
        db,
        book[0],
        "tester",
        "catalog",
        CatalogCommand(
            request_key=uuid4(), expected_revision=catalog["revision"], evidence="Synthetic active article",
            action="create_article", code="synthetic_extra", title="Synthetic extra",
            group_id=catalog["groups"][0]["id"],
        ),
    )
    next_article = next(item for item in extra["result"]["articles"] if item["code"] == "synthetic_extra")
    second_preview = await preview(db, book[0], line, next_article["id"])
    second = await expenses.confirm_attribution(
        db, book[0], "tester", command(line, next_article["id"], second_preview["basis_digest"])
    )
    rows = (
        await db.scalars(
            select(ExpenseArticleAttribution)
            .where(ExpenseArticleAttribution.source_line_id == line.id)
            .order_by(ExpenseArticleAttribution.id)
        )
    ).all()
    assert len(rows) == 2 and rows[1].supersedes_id == rows[0].id
    assert rows[0].receipt == first and rows[1].receipt == second
    actuals = await expenses.actuals(db, book[0], 2026, 10, "accrual")
    assert [item["article_id"] for item in actuals["rows"]] == [next_article["id"]]


async def test_attribution_rejects_closed_direct_and_stale_basis_without_receipt(db, book):
    article, _entry, line = await source_expense(db, book)
    basis = await preview(db, book[0], line, article["id"])
    catalog = await expenses.catalog(db, book[0])
    await expenses.execute(
        db,
        book[0],
        "tester",
        "catalog",
        CatalogCommand(
            request_key=uuid4(), expected_revision=catalog["revision"], evidence="Synthetic catalog change",
            action="create_group", code="synthetic_group", title="Synthetic group",
        ),
    )
    with pytest.raises(expenses.Conflict, match="Основание"):
        await expenses.confirm_attribution(db, book[0], "tester", command(line, article["id"], basis["basis_digest"]))
    assert await db.scalar(select(ExpenseArticleAttribution)) is None

    direct_article, _direct_entry, direct_line = await source_expense(
        db, book, dimensions={"expense_article_id": str(article["id"])}
    )
    with pytest.raises(expenses.Conflict, match="явную статью"):
        await preview(db, book[0], direct_line, direct_article["id"])

    other = Organization(name="Other attribution book", unp="111111118")
    db.add(other)
    await db.flush()
    with pytest.raises(expenses.Conflict, match="не найдена"):
        await preview(db, other.id, line, article["id"])

    db.add(Period(organization_id=book[0], month="2026-10", closed=True, generation=0))
    await db.flush()
    with pytest.raises(expenses.Conflict, match="закрыт"):
        await preview(db, book[0], line, article["id"])
