"""Expense catalog, immutable budget history and approval receipts.

The schema remains an unallocated proposal. Budget versions are never mutated;
an approval is an immutable, separately guarded fact tied to one exact version.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class ExpenseCatalog(Base):
    __tablename__ = "expense_catalog"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="expense_catalog_revision"),
        {"schema": "accounting"},
    )
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("accounting.organization.id"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(default=0)


class ExpenseGroup(Base):
    __tablename__ = "expense_group"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_expense_group_org_code"),
        UniqueConstraint("organization_id", "id", name="uq_expense_group_org_id"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExpenseArticle(Base):
    __tablename__ = "expense_article"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "group_id"],
            ["accounting.expense_group.organization_id", "accounting.expense_group.id"],
        ),
        UniqueConstraint("organization_id", "code", name="uq_expense_article_org_code"),
        UniqueConstraint("organization_id", "id", name="uq_expense_article_org_id"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    group_id: Mapped[int]
    code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExpenseBudget(Base):
    __tablename__ = "expense_budget"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "year",
            "currency",
            "basis",
            "revision",
            name="uq_expense_budget_org_version",
        ),
        UniqueConstraint("organization_id", "id", name="uq_expense_budget_org_id"),
        CheckConstraint(
            "revision > 0 AND year BETWEEN 2000 AND 2100", name="expense_budget_revision_year"
        ),
        CheckConstraint(
            "currency = 'BYN' AND basis IN ('cash','accrual') AND state = 'draft'",
            name="expense_budget_draft_only",
        ),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    year: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3))
    basis: Mapped[str] = mapped_column(String(10))
    revision: Mapped[int]
    state: Mapped[str] = mapped_column(String(10), default="draft")
    catalog_revision: Mapped[int]
    actor: Mapped[str] = mapped_column(String(200))
    evidence: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExpenseBudgetLine(Base):
    __tablename__ = "expense_budget_line"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "budget_id"],
            ["accounting.expense_budget.organization_id", "accounting.expense_budget.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "article_id"],
            ["accounting.expense_article.organization_id", "accounting.expense_article.id"],
        ),
        UniqueConstraint("budget_id", "article_id"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int]
    budget_id: Mapped[int]
    article_id: Mapped[int]
    # Explicit 12 cells, null = unknown; immutable descriptive snapshot.
    months: Mapped[list] = mapped_column(JSON)
    article_snapshot: Mapped[dict] = mapped_column(JSON)


class ExpenseCommandReceipt(Base):
    __tablename__ = "expense_command_receipt"
    __table_args__ = (UniqueConstraint("organization_id", "request_key"), {"schema": "accounting"})
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    request_key: Mapped[str] = mapped_column(String(36))
    actor: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    command_hash: Mapped[str] = mapped_column(String(64))
    receipt: Mapped[dict] = mapped_column(JSON)


class ExpenseArticleAttribution(Base):
    """Immutable analytical correction for one already-posted expense line.

    The source ledger line deliberately remains untouched.  Reclassification is
    represented by a successor receipt, so reports can use the newest receipt
    while the full decision chain stays auditable.
    """

    __tablename__ = "expense_article_attribution"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "article_id"],
            ["accounting.expense_article.organization_id", "accounting.expense_article.id"],
        ),
        UniqueConstraint("organization_id", "request_key", name="uq_expense_article_attribution_request"),
        UniqueConstraint("supersedes_id", name="uq_expense_article_attribution_successor"),
        UniqueConstraint("organization_id", "id", name="uq_expense_article_attribution_org_id"),
        CheckConstraint(
            "source_entry_id > 0 AND source_line_id > 0 AND article_id > 0",
            name="expense_article_attribution_positive_refs",
        ),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    source_entry_id: Mapped[int] = mapped_column(ForeignKey("accounting.entry.id"))
    source_line_id: Mapped[int] = mapped_column(ForeignKey("accounting.line.id"))
    article_id: Mapped[int]
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting.expense_article_attribution.id")
    )
    request_key: Mapped[str] = mapped_column(String(36))
    actor: Mapped[str] = mapped_column(String(200))
    command_hash: Mapped[str] = mapped_column(String(64))
    basis_digest: Mapped[str] = mapped_column(String(64))
    effective_date: Mapped[date] = mapped_column()
    evidence: Mapped[str] = mapped_column(String(1000))
    explanation: Mapped[str] = mapped_column(String(1000))
    source_snapshot: Mapped[dict] = mapped_column(JSON)
    article_snapshot: Mapped[dict] = mapped_column(JSON)
    receipt: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExpenseBudgetApproval(Base):
    """Immutable approval of one exact budget version.

    The draft itself deliberately remains ``state='draft'``.  This avoids
    rewriting history while still giving reports a durable, independently
    verifiable approved plan.
    """

    __tablename__ = "expense_budget_approval"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "budget_id"],
            ["accounting.expense_budget.organization_id", "accounting.expense_budget.id"],
        ),
        UniqueConstraint("organization_id", "budget_id", name="uq_expense_budget_approval_budget"),
        UniqueConstraint("organization_id", "id", name="uq_expense_budget_approval_org_id"),
        CheckConstraint("budget_revision > 0", name="expense_budget_approval_revision"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    budget_id: Mapped[int]
    budget_revision: Mapped[int]
    actor: Mapped[str] = mapped_column(String(200))
    evidence: Mapped[str] = mapped_column(String(1000))
    request_key: Mapped[str] = mapped_column(String(36))
    budget_snapshot: Mapped[dict] = mapped_column(JSON)
    approval_digest: Mapped[str] = mapped_column(String(64))
    approved_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


def prevent_history_mutation(mapper, connection, target):
    raise ValueError("Expense draft versions and command receipts are append-only")


# ORM protection complements expense_guards.sql in the unallocated schema proposal.
for history_model in (
    ExpenseBudget,
    ExpenseBudgetLine,
    ExpenseCommandReceipt,
    ExpenseArticleAttribution,
    ExpenseBudgetApproval,
):
    event.listen(history_model, "before_update", prevent_history_mutation)
    event.listen(history_model, "before_delete", prevent_history_mutation)
