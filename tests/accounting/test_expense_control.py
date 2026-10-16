"""Expense catalog, draft history and approval behavior on synthetic SQLite."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from modules.accounting import expenses
from modules.accounting.expense_models import (
    ExpenseArticle,
    ExpenseBudget,
    ExpenseBudgetApproval,
    ExpenseCommandReceipt,
    ExpenseGroup,
)
from modules.accounting.expense_schemas import BudgetApprovalCommand, BudgetCommand, CatalogCommand
from modules.accounting.models import Account, Entry, Line, Organization, Policy


def catalog_command(action="template", revision=0, **changes):
    return CatalogCommand(
        request_key=uuid4(),
        expected_revision=revision,
        evidence="Synthetic explicit choice",
        action=action,
        **changes,
    )


def budget_command(article, revision=0, catalog_revision=1, **changes):
    return BudgetCommand.model_validate(
        {
            "request_key": str(uuid4()),
            "expected_revision": revision,
            "expected_catalog_revision": catalog_revision,
            "year": 2026,
            "currency": "BYN",
            "basis": "cash",
            "evidence": "Synthetic draft only",
            "lines": [{"article_id": article, "months": ["0.00", "12.50"] + [None] * 10}],
            **changes,
        }
    )


async def setup_catalog(db, book):
    first = await expenses.execute(db, book[0], "tester", "catalog", catalog_command())
    await db.commit()
    return first


async def test_actuals_use_only_explicit_article_dimensions_and_keep_unknown_separate(db, book):
    first = await setup_catalog(db, book)
    article_id = first["result"]["articles"][0]["id"]
    policy = await db.get(Policy, book[1])
    account = await db.scalar(select(Account).where(Account.organization_id == book[0], Account.code == "90.4"))
    entry = Entry(
        organization_id=book[0], source="expense:synthetic", source_version=1, operation="manual",
        document_date=date(2026, 10, 5), operation_date=date(2026, 10, 5), posting_date=date(2026, 10, 5),
        policy_id=policy.id, rule_version="test", explanation="Synthetic expense", opening=False,
        correction_of=None, digest="a" * 64, actor="tester",
    )
    db.add(entry)
    await db.flush()
    db.add_all([
        Line(entry_id=entry.id, account_id=account.id, account_code=account.code, account_title=account.title,
             category="expense", cash=False, side="debit", amount=Decimal("12.50"),
             dimensions={"expense_article_id": str(article_id)}, currency="BYN"),
        Line(entry_id=entry.id, account_id=account.id, account_code=account.code, account_title=account.title,
             category="expense", cash=False, side="debit", amount=Decimal("3.00"),
             dimensions={}, currency="BYN"),
    ])
    await db.flush()
    result = await expenses.actuals(db, book[0], 2026, 10, "accrual")
    assert result["amount"] == "12.50"
    assert result["coverage"] == "partial"
    assert result["matched_lines"] == 1
    assert result["unmatched_lines"] == 1
    assert result["rows"][0]["article_id"] == article_id
    cash = await expenses.actuals(db, book[0], 2026, 10, "cash")
    assert cash["amount"] is None
    assert cash["coverage"] == "unknown"


async def test_actuals_preserve_credit_refund_and_complete_explicit_coverage(db, book):
    first = await setup_catalog(db, book)
    article_id = first["result"]["articles"][0]["id"]
    policy = await db.get(Policy, book[1])
    account = await db.scalar(select(Account).where(Account.organization_id == book[0], Account.code == "90.4"))
    entry = Entry(
        organization_id=book[0], source="expense:refund", source_version=1, operation="correction",
        document_date=date(2026, 11, 5), operation_date=date(2026, 11, 5), posting_date=date(2026, 11, 5),
        policy_id=policy.id, rule_version="test", explanation="Synthetic refund", opening=False,
        correction_of=None, digest="b" * 64, actor="tester",
    )
    db.add(entry)
    await db.flush()
    db.add(Line(
        entry_id=entry.id, account_id=account.id, account_code=account.code, account_title=account.title,
        category="expense", cash=False, side="credit", amount=Decimal("4.50"),
        dimensions={"expense_article_id": str(article_id)}, currency="BYN",
    ))
    await db.flush()
    result = await expenses.actuals(db, book[0], 2026, 11, "accrual")
    assert result["amount"] == "-4.50"
    assert result["coverage"] == "complete"
    assert result["matched_lines"] == 1
    assert result["unmatched_lines"] == 0
    assert result["rows"][0]["amount"] == "-4.50"


async def test_cash_actuals_require_explicit_cash_flag_and_article(db, book):
    first = await setup_catalog(db, book)
    article_id = first["result"]["articles"][0]["id"]
    policy = await db.get(Policy, book[1])
    account = await db.scalar(select(Account).where(Account.organization_id == book[0], Account.code == "90.4"))
    entry = Entry(
        organization_id=book[0], source="expense:cash-synthetic", source_version=1, operation="manual",
        document_date=date(2026, 10, 5), operation_date=date(2026, 10, 5), posting_date=date(2026, 10, 5),
        policy_id=policy.id, rule_version="test", explanation="Synthetic cash expense", opening=False,
        correction_of=None, digest="c" * 64, actor="tester",
    )
    db.add(entry)
    await db.flush()
    db.add_all([
        Line(entry_id=entry.id, account_id=account.id, account_code=account.code, account_title=account.title,
             category="expense", cash=True, side="debit", amount=Decimal("8.40"),
             dimensions={"expense_article_id": str(article_id)}, currency="BYN"),
        Line(entry_id=entry.id, account_id=account.id, account_code=account.code, account_title=account.title,
             category="expense", cash=True, side="debit", amount=Decimal("2.00"),
             dimensions={}, currency="BYN"),
        Line(entry_id=entry.id, account_id=account.id, account_code=account.code, account_title=account.title,
             category="expense", cash=False, side="debit", amount=Decimal("99.00"),
             dimensions={"expense_article_id": str(article_id)}, currency="BYN"),
    ])
    await db.flush()
    result = await expenses.actuals(db, book[0], 2026, 10, "cash")
    assert result["amount"] == "8.40"
    assert result["coverage"] == "partial"
    assert result["matched_lines"] == 1
    assert result["unmatched_lines"] == 1
    assert result["rows"][0]["amount"] == "8.40"


async def test_template_is_explicit_scoped_and_exact_replay_after_later_changes(db, book):
    assert (await expenses.catalog(db, book[0])) == {"revision": 0, "groups": [], "articles": []}
    command = catalog_command()
    first = await expenses.execute(db, book[0], "tester", "catalog", command)
    await db.commit()
    assert len(first["result"]["groups"]) == 6
    assert len(first["result"]["articles"]) == 15
    assert "counterparty" not in {a["code"] for a in first["result"]["articles"]}
    await expenses.execute(
        db,
        book[0],
        "tester",
        "catalog",
        catalog_command("create_group", 1, code="extra", title="Extra"),
    )
    await db.commit()
    assert await expenses.execute(db, book[0], "tester", "catalog", command) == first
    with pytest.raises(expenses.Conflict, match="UUID"):
        await expenses.execute(
            db, book[0], "tester", "catalog", command.model_copy(update={"evidence": "changed"})
        )
    with pytest.raises(expenses.Conflict, match="UUID"):
        await expenses.execute(db, book[0], "other", "catalog", command)
    other = Organization(name="Other synthetic", unp="888888888")
    db.add(other)
    await db.flush()
    assert (await expenses.catalog(db, other.id))["groups"] == []


async def test_versions_preserve_unknown_zero_and_original_catalog_snapshot(db, book):
    first = await setup_catalog(db, book)
    article = first["result"]["articles"][0]["id"]
    cmd = budget_command(article)
    receipt = await expenses.execute(db, book[0], "tester", "budget", cmd)
    await db.commit()
    second = budget_command(
        article, revision=1, lines=[{"article_id": article, "months": ["42.30"] + [None] * 11}]
    )
    await expenses.execute(db, book[0], "tester", "budget", second)
    await db.commit()
    versions = await expenses.budgets(db, book[0], 2026, "BYN", "cash")
    assert [v["revision"] for v in versions] == [2, 1]
    assert versions[1]["lines"][0]["months"] == ["0.00", "12.50"] + [None] * 10
    assert versions[1] == receipt["result"]
    assert await expenses.execute(db, book[0], "tester", "budget", cmd) == receipt
    with pytest.raises(expenses.Conflict, match="версия"):
        await expenses.execute(db, book[0], "tester", "budget", budget_command(article))
    assert await expenses.budgets(db, book[0], 2026, "BYN", "accrual") == []


async def test_approval_is_separate_immutable_fact_and_replays_exact_receipt(db, book):
    first = await setup_catalog(db, book)
    article = first["result"]["articles"][0]["id"]
    draft = await expenses.execute(db, book[0], "tester", "budget", budget_command(article))
    await db.commit()
    command = BudgetApprovalCommand(
        request_key=uuid4(), budget_id=draft["result"]["id"],
        expected_revision=draft["result"]["revision"], evidence="Главный бухгалтер проверил план",
    )
    receipt = await expenses.approve(db, book[0], "tester", command)
    await db.commit()
    assert receipt["kind"] == "budget_approval"
    assert receipt["result"]["budget"]["state"] == "draft"
    assert await expenses.approve(db, book[0], "tester", command) == receipt
    approved = await expenses.approved_budget(db, book[0], 2026, "BYN", "cash")
    assert approved["budget_id"] == draft["result"]["id"]
    assert approved["budget_revision"] == 1
    assert (await db.scalars(select(ExpenseBudgetApproval))).all()[0].approval_digest == receipt["result"]["approval_digest"]
    with pytest.raises(expenses.Conflict, match="уже утверждена"):
        await expenses.approve(
            db,
            book[0],
            "tester",
            BudgetApprovalCommand(
                request_key=uuid4(), budget_id=command.budget_id,
                expected_revision=command.expected_revision, evidence="Повторная попытка",
            ),
        )


async def test_archive_keeps_used_article_and_budget_history(db, book):
    first = await setup_catalog(db, book)
    article = first["result"]["articles"][0]
    cmd = budget_command(article["id"])
    await expenses.execute(db, book[0], "tester", "budget", cmd)
    await db.commit()
    with pytest.raises(expenses.Conflict, match="Сначала архивируйте"):
        await expenses.execute(
            db,
            book[0],
            "tester",
            "catalog",
            catalog_command("archive_group", 1, target_id=article["group_id"]),
        )
    await expenses.execute(
        db,
        book[0],
        "tester",
        "catalog",
        catalog_command("archive_article", 1, target_id=article["id"]),
    )
    await db.commit()
    assert await db.get(ExpenseArticle, article["id"]) is not None
    assert not (await expenses.catalog(db, book[0]))["articles"][0]["active"]
    with pytest.raises(expenses.Conflict, match="Архивная"):
        await expenses.execute(
            db,
            book[0],
            "tester",
            "budget",
            budget_command(
                article["id"],
                revision=1,
                catalog_revision=2,
                lines=[{"article_id": article["id"], "months": [None] * 12}],
            ),
        )
    await expenses.execute(
        db,
        book[0],
        "tester",
        "budget",
        budget_command(article["id"], revision=1, catalog_revision=2),
    )
    await db.commit()
    assert len(await expenses.budgets(db, book[0], 2026, "BYN", "cash")) == 2


async def test_foreign_group_article_and_stale_catalog_are_rejected(db, book):
    first = await setup_catalog(db, book)
    org2 = Organization(name="Other", unp="111111111")
    db.add(org2)
    await db.flush()
    with pytest.raises(expenses.Conflict, match="Группа"):
        await expenses.execute(
            db,
            org2.id,
            "tester",
            "catalog",
            catalog_command(
                "create_article",
                group_id=first["result"]["groups"][0]["id"],
                code="wrong",
                title="Wrong",
            ),
        )
    with pytest.raises(expenses.Conflict, match="Статья"):
        await expenses.execute(
            db,
            org2.id,
            "tester",
            "budget",
            budget_command(first["result"]["articles"][0]["id"], catalog_revision=0),
        )
    with pytest.raises(expenses.Conflict, match="Справочник"):
        await expenses.execute(
            db,
            book[0],
            "tester",
            "budget",
            budget_command(first["result"]["articles"][0]["id"], catalog_revision=0),
        )
    assert len((await db.scalars(select(ExpenseBudget))).all()) == 0


@pytest.mark.parametrize(
    "amount", [0, 1.1, True, "-1.00", "NaN", "Infinity", "1e2", "1.001", "01.00", " 2 "]
)
def test_money_requires_exact_nonnegative_decimal_string(amount):
    with pytest.raises(ValidationError):
        budget_command(1, lines=[{"article_id": 1, "months": [amount] + [None] * 11}])


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": None},
        {"currency": "USD"},
        {"basis": None},
        {"basis": "fact"},
        {"year": True},
        {"expected_revision": True},
        {"approved": True},
        {"evidence": " "},
        {"lines": []},
    ],
)
def test_configuration_and_commands_are_explicit(changes):
    with pytest.raises(ValidationError):
        budget_command(1, **changes)


async def test_receipt_integrity_rejects_corruption(db, book):
    cmd = catalog_command()
    await expenses.execute(db, book[0], "tester", "catalog", cmd)
    await db.commit()
    row = await db.scalar(select(ExpenseCommandReceipt))
    await db.execute(
        update(ExpenseCommandReceipt)
        .where(ExpenseCommandReceipt.id == row.id)
        .values(receipt={**row.receipt, "result_digest": "0" * 64})
    )
    with pytest.raises(expenses.Conflict, match="целостности"):
        await expenses.execute(db, book[0], "tester", "catalog", cmd)


def test_model_composite_scope_constraints_are_declared():
    # Structural proposal evidence, not execution of independent PostgreSQL guards.
    assert any(
        {col.name for col in c.columns} == {"organization_id", "group_id"}
        for c in ExpenseArticle.__table__.foreign_key_constraints
    )
    assert any(
        {col.name for col in c.columns} == {"organization_id", "id"}
        for c in ExpenseGroup.__table__.constraints
        if hasattr(c, "columns")
    )


async def test_sqlite_composite_fk_and_draft_only_check_execute(db, book):
    first = await setup_catalog(db, book)
    # Synthetic in-memory database; explicitly activate SQLite FK checks.
    await db.execute(text("PRAGMA foreign_keys=ON"))
    assert await db.scalar(text("PRAGMA foreign_keys")) == 1
    other = Organization(name="Other synthetic", unp="777777777")
    db.add(other)
    await db.commit()
    other_id = other.id
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                ExpenseArticle(
                    organization_id=other_id,
                    group_id=first["result"]["groups"][0]["id"],
                    code="bad_scope",
                    title="Invalid",
                )
            )
            await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                ExpenseBudget(
                    organization_id=book[0],
                    year=2026,
                    currency="BYN",
                    basis="cash",
                    revision=1,
                    state="approved",
                    catalog_revision=1,
                    actor="tester",
                    evidence="Must fail",
                )
            )
            await db.flush()


async def test_application_history_update_delete_is_rejected(db, book):
    first = await setup_catalog(db, book)
    result = await expenses.execute(
        db, book[0], "tester", "budget", budget_command(first["result"]["articles"][0]["id"])
    )
    await db.commit()
    budget_id = result["result"]["id"]
    row = await db.get(ExpenseBudget, budget_id)
    row.evidence = "Overwrite"
    with pytest.raises(ValueError, match="append-only"):
        await db.flush()
    await db.rollback()
    row = await db.get(ExpenseBudget, budget_id)
    await db.delete(row)
    with pytest.raises(ValueError, match="append-only"):
        await db.flush()
    await db.rollback()
