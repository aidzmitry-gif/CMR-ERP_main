"""Accounting-owned schema. Posted history is append-only."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class Organization(Base):
    __tablename__ = "organization"
    __table_args__ = {"schema": "accounting"}
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    unp: Mapped[str] = mapped_column(String(9), unique=True)
    generation: Mapped[int] = mapped_column(default=0)


class AccessGrant(Base):
    __tablename__ = "access_grant"
    __table_args__ = (UniqueConstraint("organization_id", "subject"), {"schema": "accounting"})
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    subject: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))


class SellerProfile(Base):
    __tablename__ = "seller_profile"
    __table_args__ = (
        UniqueConstraint("organization_id", "revision", name="uq_seller_profile_org_revision"),
        UniqueConstraint("organization_id", "source_key", name="uq_seller_profile_org_source_key"),
        CheckConstraint("revision > 0", name="seller_profile_revision"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    revision: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    source_key: Mapped[str] = mapped_column(String(160))
    request_digest: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[str] = mapped_column(String(2000))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", "valid_from"),
        ForeignKeyConstraint(
            ["organization_id", "catalog_adoption_id"],
            ["accounting.catalog_adoption.organization_id", "accounting.catalog_adoption.id"],
            name="fk_account_catalog_adoption_organization",
        ),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    code: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))
    valid_from: Mapped[date] = mapped_column(Date)
    required_dimensions: Mapped[list] = mapped_column(JSON)
    currency_tracking: Mapped[bool] = mapped_column(Boolean)
    quantity_tracking: Mapped[bool] = mapped_column(Boolean)
    cash: Mapped[bool] = mapped_column(Boolean)
    normative_ref: Mapped[str] = mapped_column(String(200))
    # Legacy accounts deliberately remain unlinked.  New versions receive the
    # effective immutable catalogue-adoption receipt at creation time.
    catalog_adoption_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class CatalogAdoption(Base):
    """Immutable organization acknowledgement of one server-known chart edition."""
    __tablename__ = "catalog_adoption"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_catalog_adoption_request"),
        UniqueConstraint("organization_id", "effective_from", name="uq_catalog_adoption_effective"),
        UniqueConstraint("organization_id", "id", name="uq_catalog_adoption_organization_id"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    evidence: Mapped[str] = mapped_column(String(2000))
    catalog_version: Mapped[str] = mapped_column(String(200))
    catalog_source: Mapped[str] = mapped_column(String(2000))
    catalog_review_state: Mapped[dict] = mapped_column(JSON)
    current_normative_verified: Mapped[bool] = mapped_column(Boolean)
    request_key: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Policy(Base):
    __tablename__ = "policy"
    __table_args__ = (
        UniqueConstraint("organization_id", "effective_from"), {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    effective_from: Mapped[date] = mapped_column(Date)
    reference: Mapped[str] = mapped_column(String(200))
    inventory_method: Mapped[str] = mapped_column(String(32))
    allocation_basis: Mapped[str] = mapped_column(String(32))
    depreciation_method: Mapped[str] = mapped_column(String(32))
    normative_reference: Mapped[str] = mapped_column(String(200))
    normative_verified: Mapped[bool] = mapped_column(Boolean)
    financial_closing: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Currency revaluation is configured explicitly per organisation.  It is
    # intentionally separate from the closing transfer settings so a book can
    # review FX exposure before the first configured month close exists.
    currency_revaluation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    late_cost_allocation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    production_costing: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Optional by design.  An absent TN/TTN scenario blocks that workflow;
    # no document kind, form, number or external operator is inferred.
    shipment_documents: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    approved_by: Mapped[str] = mapped_column(String(200))


class Period(Base):
    __tablename__ = "period"
    __table_args__ = (UniqueConstraint("organization_id", "month"), {"schema": "accounting"})
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    month: Mapped[str] = mapped_column(String(7))
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    closed_generation: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class Entry(Base):
    __tablename__ = "entry"
    __table_args__ = (
        UniqueConstraint("organization_id", "source", "source_version", "operation"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    source: Mapped[str] = mapped_column(String(160))
    source_version: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(60))
    document_date: Mapped[date] = mapped_column(Date)
    operation_date: Mapped[date] = mapped_column(Date)
    posting_date: Mapped[date] = mapped_column(Date, index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("accounting.policy.id"))
    rule_version: Mapped[str] = mapped_column(String(100))
    explanation: Mapped[str] = mapped_column(String(1000))
    opening: Mapped[bool] = mapped_column(Boolean)
    correction_of: Mapped[int | None] = mapped_column(ForeignKey("accounting.entry.id"))
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Line(Base):
    __tablename__ = "line"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_nonnegative"),
        CheckConstraint("side IN ('debit','credit')", name="side_valid"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("accounting.entry.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounting.account.id"))
    # Snapshot makes report labels and analytical requirements historical.
    account_code: Mapped[str] = mapped_column(String(32))
    account_title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))
    cash: Mapped[bool] = mapped_column(Boolean)
    side: Mapped[str] = mapped_column(String(6))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    dimensions: Mapped[dict] = mapped_column(JSON)
    currency: Mapped[str] = mapped_column(String(3))
    original_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    rate_scale: Mapped[int | None] = mapped_column(Integer)
    rate_date: Mapped[date | None] = mapped_column(Date)
    rate_source: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    cash_activity: Mapped[str | None] = mapped_column(String(20))


class Inbox(Base):
    __tablename__ = "inbox"
    __table_args__ = (
        UniqueConstraint("organization_id", "event_key"), {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    event_key: Mapped[str] = mapped_column(String(160))
    month: Mapped[str] = mapped_column(String(7))
    payload: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(1000))
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("accounting.entry.id"))


class SourceBinding(Base):
    """Explicit ownership decision, never inferred from a default organization."""
    __tablename__ = "source_binding"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id"),
        CheckConstraint("source_id > 0", name="source_binding_positive_id"),
        CheckConstraint(
            "source_type IN ('wms_receipt', 'logistics_import', 'finance_bank_transaction')",
            name="source_binding_type",
        ),
        CheckConstraint("ownership IN ('own', 'customer')", name="source_binding_ownership"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[int] = mapped_column(Integer)
    ownership: Mapped[str] = mapped_column(String(16))
    evidence: Mapped[str] = mapped_column(String(1000))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BankAccountMapping(Base):
    """Versioned accounting configuration; SourceBinding remains source ownership."""
    __tablename__ = "bank_account_mapping"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "external_account", "currency", "version",
                         name="uq_bank_account_mapping_version"),
        UniqueConstraint("organization_id", "provider", "external_account", "currency", "valid_from",
                         name="uq_bank_account_mapping_valid_from"),
        CheckConstraint("version > 0", name="bank_account_mapping_positive_version"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="bank_account_mapping_valid_range"),
        # SQLite is used by the scoped API suite; Pydantic and the PostgreSQL
        # migration enforce the full ISO-code format.
        CheckConstraint("length(currency) = 3", name="bank_account_mapping_currency"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    provider: Mapped[str] = mapped_column(String(100))
    external_account: Mapped[str] = mapped_column(String(128))
    currency: Mapped[str] = mapped_column(String(3))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    ledger_account_id: Mapped[int] = mapped_column(ForeignKey("accounting.account.id"))
    dimensions: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[str] = mapped_column(String(1000))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StatutoryRequirement(Base):
    """Explicit external statutory form/rate configuration; never a payroll calculator."""
    __tablename__ = "statutory_requirement"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_statutory_requirement_request"),
        UniqueConstraint("organization_id", "kind", "code", "effective_from", "revision",
                         name="uq_statutory_requirement_revision"),
        CheckConstraint("kind IN ('form', 'rate')", name="statutory_requirement_kind"),
        CheckConstraint("revision > 0", name="statutory_requirement_positive_revision"),
        CheckConstraint("rate_value IS NULL OR rate_value >= 0", name="statutory_requirement_rate_nonnegative"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    code: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(500))
    effective_from: Mapped[date] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer)
    source_reference: Mapped[str] = mapped_column(String(1000))
    evidence: Mapped[str] = mapped_column(String(2000))
    form_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    electronic_format_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rate_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    rate_unit: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rate_basis: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_key: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PayrollEmploymentBinding(Base):
    """Explicit, append-only employer and contract link for a global HR employee."""

    __tablename__ = "payroll_employment_binding"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_payroll_employment_request"),
        UniqueConstraint("organization_id", "employee_id", "contract_ref", "effective_from", "revision",
                         name="uq_payroll_employment_revision"),
        CheckConstraint("revision > 0", name="payroll_employment_positive_revision"),
        CheckConstraint("state IN ('active', 'ended')", name="payroll_employment_state"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employee.id"))
    contract_ref: Mapped[str] = mapped_column(String(160))
    effective_from: Mapped[date] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(8))
    source_document: Mapped[str] = mapped_column(String(160))
    evidence: Mapped[str] = mapped_column(String(2000))
    request_key: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PayrollRuleSet(Base):
    """Append-only employer configuration for payroll workpaper arithmetic."""

    __tablename__ = "payroll_rule_set"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_payroll_rule_set_request"),
        UniqueConstraint("organization_id", "effective_from", "revision",
                         name="uq_payroll_rule_set_revision"),
        CheckConstraint("revision > 0", name="payroll_rule_set_positive_revision"),
        CheckConstraint("gross_method = 'monthly_salary_by_hours'",
                        name="payroll_rule_set_gross_method"),
        CheckConstraint("rounding = 'half_up_cent'", name="payroll_rule_set_rounding"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    policy_id: Mapped[int] = mapped_column(ForeignKey("accounting.policy.id"))
    effective_from: Mapped[date] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer)
    gross_method: Mapped[str] = mapped_column(String(40))
    rounding: Mapped[str] = mapped_column(String(20))
    rate_rules: Mapped[list] = mapped_column(JSON)
    source_reference: Mapped[str] = mapped_column(String(200))
    source_digest: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[str] = mapped_column(String(2000))
    request_key: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PayrollEvidenceFile(Base):
    """Immutable file identity; confidential bytes live in private local storage."""

    __tablename__ = "payroll_evidence_file"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_payroll_evidence_request"),
        CheckConstraint("kind IN ('employment_contract', 'timesheet', 'payroll_policy', 'base_adjustment', 'payroll_zero_activity')",
                        name="payroll_evidence_kind"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 10485760", name="payroll_evidence_size"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    employment_binding_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting.payroll_employment_binding.id"), nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(24))
    month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    reference: Mapped[str] = mapped_column(String(160))
    filename: Mapped[str] = mapped_column(String(160))
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_filename: Mapped[str] = mapped_column(String(80))
    evidence: Mapped[str] = mapped_column(String(2000))
    request_key: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PayrollWorkpaperReview(Base):
    """Append-only chief review of source-backed arithmetic, never a payroll posting."""

    __tablename__ = "payroll_workpaper_review"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_payroll_workpaper_review_request"),
        UniqueConstraint("organization_id", "employment_binding_id", "month", "work_from",
                         "work_to", "revision", name="uq_payroll_workpaper_review_revision"),
        CheckConstraint("revision > 0", name="payroll_workpaper_review_positive_revision"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    employment_binding_id: Mapped[int] = mapped_column(
        ForeignKey("accounting.payroll_employment_binding.id"),
    )
    month: Mapped[str] = mapped_column(String(7))
    work_from: Mapped[date] = mapped_column(Date)
    work_to: Mapped[date] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer)
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting.payroll_workpaper_review.id"), nullable=True,
    )
    request_key: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    basis_digest: Mapped[str] = mapped_column(String(64))
    snapshot_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    reviewer_evidence: Mapped[str] = mapped_column(String(2000))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceControl(Base):
    """Current completeness state; source revisions and audit preserve its history."""
    __tablename__ = "source_control"
    __table_args__ = (UniqueConstraint("organization_id", "source"), {"schema": "accounting"})
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    source: Mapped[str] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(Integer)
    month: Mapped[str] = mapped_column(String(7))
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("accounting.entry.id"))


class Audit(Base):
    __tablename__ = "audit"
    __table_args__ = {"schema": "accounting"}
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OpeningImportReceipt(Base):
    """Immutable evidence that one opening-balance package was accepted."""
    __tablename__ = "opening_import_receipt"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_opening_import_request"),
        UniqueConstraint("organization_id", "command_digest", name="uq_opening_import_command"),
        CheckConstraint("entry_count > 0", name="opening_import_entry_count_positive"),
        CheckConstraint("line_count >= entry_count", name="opening_import_line_count_valid"),
        CheckConstraint("debit_total >= 0 AND credit_total >= 0", name="opening_import_totals_nonnegative"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    batch: Mapped[str] = mapped_column(String(120))
    protocol_version: Mapped[str] = mapped_column(String(40))
    source_system: Mapped[str] = mapped_column(String(80))
    source_digest: Mapped[str] = mapped_column(String(64))
    cutover_date: Mapped[date] = mapped_column(Date)
    entry_count: Mapped[int] = mapped_column(Integer)
    line_count: Mapped[int] = mapped_column(Integer)
    debit_total: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    credit_total: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    command_digest: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[str] = mapped_column(String(2000))
    entry_ids: Mapped[list] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReconciliationReceipt(Base):
    """Immutable accountant acceptance of one eligible OSV comparison."""

    __tablename__ = "reconciliation_receipt"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_reconciliation_request"),
        UniqueConstraint("organization_id", "command_digest", name="uq_reconciliation_command"),
        UniqueConstraint("organization_id", "left_digest", "right_digest",
                         name="uq_reconciliation_source_pair"),
        CheckConstraint("difference_count = 0", name="reconciliation_no_differences"),
        CheckConstraint("left_pending_documents = 0 AND right_pending_documents = 0",
                        name="reconciliation_no_pending_documents"),
        CheckConstraint("left_status = 'closed_periods' AND right_status = 'closed_periods'",
                        name="reconciliation_reports_closed"),
        CheckConstraint("left_rows >= 0 AND right_rows >= 0", name="reconciliation_row_counts_valid"),
        {"schema": "accounting"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    left_digest: Mapped[str] = mapped_column(String(64))
    right_digest: Mapped[str] = mapped_column(String(64))
    left_status: Mapped[str] = mapped_column(String(20))
    right_status: Mapped[str] = mapped_column(String(20))
    left_pending_documents: Mapped[int] = mapped_column(Integer)
    right_pending_documents: Mapped[int] = mapped_column(Integer)
    left_rows: Mapped[int] = mapped_column(Integer)
    right_rows: Mapped[int] = mapped_column(Integer)
    difference_count: Mapped[int] = mapped_column(Integer)
    command_digest: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[str] = mapped_column(String(2000))
    snapshot: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReconciliationIssue(Base):
    """Immutable queue record for an OSV comparison that cannot be accepted.

    Resolving an item never makes this historical pair acceptable.  A fresh
    normalized comparison must still be run and accepted by an accountant.
    """

    __tablename__ = "reconciliation_issue"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_reconciliation_issue_request"),
        UniqueConstraint("organization_id", "command_digest", name="uq_reconciliation_issue_command"),
        UniqueConstraint("organization_id", "left_digest", "right_digest",
                         name="uq_reconciliation_issue_source_pair"),
        UniqueConstraint("organization_id", "id", name="uq_reconciliation_issue_organization_id"),
        CheckConstraint("difference_count >= 0", name="reconciliation_issue_difference_count"),
        CheckConstraint("left_pending_documents >= 0 AND right_pending_documents >= 0",
                        name="reconciliation_issue_pending_documents"),
        CheckConstraint("left_rows >= 0 AND right_rows >= 0", name="reconciliation_issue_row_counts"),
        {"schema": "accounting"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    left_digest: Mapped[str] = mapped_column(String(64))
    right_digest: Mapped[str] = mapped_column(String(64))
    left_status: Mapped[str] = mapped_column(String(20))
    right_status: Mapped[str] = mapped_column(String(20))
    left_pending_documents: Mapped[int] = mapped_column(Integer)
    right_pending_documents: Mapped[int] = mapped_column(Integer)
    left_rows: Mapped[int] = mapped_column(Integer)
    right_rows: Mapped[int] = mapped_column(Integer)
    difference_count: Mapped[int] = mapped_column(Integer)
    eligibility_blockers: Mapped[list] = mapped_column(JSON)
    responsible: Mapped[str] = mapped_column(String(200))
    evidence: Mapped[str] = mapped_column(String(2000))
    command_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReconciliationIssueItem(Base):
    """One unmatched normalized OSV row belonging to an immutable queue case."""

    __tablename__ = "reconciliation_issue_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "issue_id"],
            ["accounting.reconciliation_issue.organization_id", "accounting.reconciliation_issue.id"],
            name="fk_reconciliation_issue_item_organization",
        ),
        UniqueConstraint("organization_id", "issue_id", "item_key",
                         name="uq_reconciliation_issue_item_key"),
        UniqueConstraint("organization_id", "issue_id", "id",
                         name="uq_reconciliation_issue_item_organization_id"),
        CheckConstraint("presence IN ('both', 'left_only', 'right_only')",
                        name="reconciliation_issue_item_presence"),
        {"schema": "accounting"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    issue_id: Mapped[int] = mapped_column(Integer, index=True)
    item_key: Mapped[str] = mapped_column(String(64))
    account: Mapped[str] = mapped_column(String(32))
    dimensions: Mapped[dict] = mapped_column(JSON)
    currency: Mapped[str] = mapped_column(String(3))
    off_balance: Mapped[bool] = mapped_column(Boolean)
    presence: Mapped[str] = mapped_column(String(12))
    fields: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FinancialCloseReceipt(Base):
    """Immutable financial transfer package; HTTP confirmation awaits its SQL guards."""
    __tablename__ = "financial_close_receipt"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key"),
        UniqueConstraint("monthly_entry_id"), UniqueConstraint("annual_entry_id"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    month: Mapped[str] = mapped_column(String(7), index=True)
    command: Mapped[dict] = mapped_column(JSON)
    command_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    monthly_entry_id: Mapped[int | None] = mapped_column(ForeignKey("accounting.entry.id"))
    annual_entry_id: Mapped[int | None] = mapped_column(ForeignKey("accounting.entry.id"))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FinancialReopenReceipt(Base):
    """One replayable command for a cascading reopening, including empty months."""
    __tablename__ = "financial_reopen_receipt"
    __table_args__ = (UniqueConstraint("organization_id", "request_key"), {"schema": "accounting"})
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    from_month: Mapped[str] = mapped_column(String(7))
    command: Mapped[dict] = mapped_column(JSON)
    command_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FinancialReopenItem(Base):
    __tablename__ = "financial_reopen_item"
    __table_args__ = (
        UniqueConstraint("close_receipt_id"), UniqueConstraint("monthly_entry_id"),
        UniqueConstraint("annual_entry_id"), {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    reopen_receipt_id: Mapped[int] = mapped_column(ForeignKey("accounting.financial_reopen_receipt.id"))
    close_receipt_id: Mapped[int] = mapped_column(ForeignKey("accounting.financial_close_receipt.id"))
    monthly_entry_id: Mapped[int | None] = mapped_column(ForeignKey("accounting.entry.id"))
    annual_entry_id: Mapped[int | None] = mapped_column(ForeignKey("accounting.entry.id"))


class FxRevaluationReceipt(Base):
    """Immutable reviewed currency revaluation package.

    The package records the exact rate evidence, source balances and the
    resulting ledger entry.  A later review of an already reopened month uses
    the next source version and explicitly corrects the previous entry; it
    never mutates the original receipt.
    """
    __tablename__ = "fx_revaluation_receipt"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_fx_revaluation_request"),
        UniqueConstraint("organization_id", "month", "source_version",
                         name="uq_fx_revaluation_source_version"),
        UniqueConstraint("entry_id", name="uq_fx_revaluation_entry"),
        CheckConstraint("source_version > 0", name="fx_revaluation_source_version_positive"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    month: Mapped[str] = mapped_column(String(7), index=True)
    source_version: Mapped[int] = mapped_column(Integer)
    command: Mapped[dict] = mapped_column(JSON)
    command_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("accounting.entry.id"), nullable=True)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShipmentAccountingReceipt(Base):
    """Whole physical act and every balanced page saved in one transaction."""
    __tablename__ = "shipment_accounting_receipt"
    __table_args__ = (
        UniqueConstraint("organization_id", "source"),
        UniqueConstraint("anchor_entry_id"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    source: Mapped[str] = mapped_column(String(160))
    act_digest: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(JSON)
    basis_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    anchor_entry_id: Mapped[int] = mapped_column(ForeignKey("accounting.entry.id"))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShipmentPreparationDraft(Base):
    """Versioned user input only; never a posting or verified calculation."""
    __tablename__ = "shipment_preparation_draft"
    __table_args__ = (
        UniqueConstraint("organization_id", "source", "revision", name="uq_shipment_draft_source_revision"),
        UniqueConstraint("organization_id", "request_key", name="uq_shipment_draft_request"),
        CheckConstraint("revision > 0", name="shipment_draft_positive_revision"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"))
    source: Mapped[str] = mapped_column(String(160))
    revision: Mapped[int]
    request_key: Mapped[str] = mapped_column(String(36))
    command_digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryIssueReceipt(Base):
    """Original issue command and cost evidence, atomically bound to its entry."""
    __tablename__ = "inventory_issue_receipt"
    __table_args__ = {"schema": "accounting"}
    entry_id: Mapped[int] = mapped_column(ForeignKey("accounting.entry.id"), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    command: Mapped[dict] = mapped_column(JSON)
    cost: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ZeroValueInventoryDisposalReceipt(Base):
    """Immutable physical disposal when a selected layer carries exactly zero BYN.

    This model is intentionally not reachable until its dedicated migration and
    valuation integration land.  ``entry_id`` is null only for an inventory
    issue; a sale keeps its revenue/VAT entry and binds this receipt to it.
    """
    __tablename__ = "inventory_zero_value_disposal_receipt"
    __table_args__ = (
        UniqueConstraint("organization_id", "source", "source_version", "operation",
                         name="uq_inventory_zero_value_disposal_identity"),
        UniqueConstraint("registration_token", name="uq_inventory_zero_value_disposal_registration"),
        CheckConstraint("source_version > 0", name="inventory_zero_value_disposal_source_version_positive"),
        CheckConstraint("registration_token > 0", name="inventory_zero_value_disposal_registration_positive"),
        CheckConstraint("operation IN ('inventory_issue', 'inventory_sale')",
                        name="inventory_zero_value_disposal_operation"),
        {"schema": "accounting"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    source: Mapped[str] = mapped_column(String(160))
    source_version: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(60))
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("accounting.entry.id"), nullable=True, unique=True)
    registration_token: Mapped[int] = mapped_column(Integer, server_default=FetchedValue())
    posting_date: Mapped[date] = mapped_column(Date, index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("accounting.policy.id"))
    command: Mapped[dict] = mapped_column(JSON)
    basis_digest: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventorySaleReceipt(Base):
    """Original sale terms and costing evidence saved with the ledger package."""
    __tablename__ = "inventory_sale_receipt"
    __table_args__ = {"schema": "accounting"}
    entry_id: Mapped[int] = mapped_column(ForeignKey("accounting.entry.id"), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    command: Mapped[dict] = mapped_column(JSON)
    cost: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductionOutputTransferReceipt(Base):
    """Immutable source, cost basis and ledger package for WIP-to-output transfer."""
    __tablename__ = 'production_output_transfer_receipt'
    __table_args__ = (
        UniqueConstraint('organization_id', 'order_id', name='uq_production_output_transfer_order'),
        {'schema': 'accounting'},
    )
    entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.entry.id'), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), index=True)
    order_id: Mapped[int]
    month: Mapped[str] = mapped_column(String(7))
    command: Mapped[dict] = mapped_column(JSON)
    basis: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    basis_digest: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductionOutputCostRevision(Base):
    """Immutable, ordered cost correction evidence for one output transfer."""
    __tablename__ = 'production_output_cost_revision'
    __table_args__ = (
        UniqueConstraint('organization_id', 'request_key', name='uq_output_cost_revision_request'),
        UniqueConstraint('original_entry_id', 'sequence', name='uq_output_cost_revision_sequence'),
        UniqueConstraint('registration_token', name='uq_output_cost_revision_registration'),
        {'schema': 'accounting'},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'))
    original_entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.production_output_transfer_receipt.entry_id'))
    sequence: Mapped[int]
    previous_id: Mapped[int | None] = mapped_column(ForeignKey('accounting.production_output_cost_revision.id'), nullable=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey('accounting.entry.id'), nullable=True, unique=True)
    registration_token: Mapped[int] = mapped_column(Integer, server_default=FetchedValue())
    month: Mapped[str] = mapped_column(String(7))
    request_key: Mapped[str] = mapped_column(String(36))
    command: Mapped[dict] = mapped_column(JSON)
    preview: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductionLaborReceipt(Base):
    """Immutable verified payroll import and its production-cost ledger package."""
    __tablename__ = 'production_labor_receipt'
    __table_args__ = (
        UniqueConstraint('organization_id', 'request_key', name='uq_production_labor_request'),
        UniqueConstraint('organization_id', 'source_document', 'source_version',
                         name='uq_production_labor_source'),
        {'schema': 'accounting'},
    )
    entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.entry.id'), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    source_document: Mapped[str] = mapped_column(String(160))
    source_version: Mapped[int] = mapped_column(Integer)
    source_digest: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(JSON)
    source: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PayrollAccrualReceipt(Base):
    """Immutable verified payroll-accrual import and its ledger package.

    This is an interim source-bound import.  It records gross accruals only;
    statutory payroll calculation, deductions, contributions and reporting are
    deliberately outside this receipt until their own reviewed workflow exists.
    """
    __tablename__ = 'payroll_accrual_receipt'
    __table_args__ = (
        UniqueConstraint('organization_id', 'request_key', name='uq_payroll_accrual_request'),
        UniqueConstraint('organization_id', 'source_document', 'source_version',
                         name='uq_payroll_accrual_source'),
        CheckConstraint('source_version > 0', name='payroll_accrual_source_version_positive'),
        {'schema': 'accounting'},
    )
    entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.entry.id'), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    source_document: Mapped[str] = mapped_column(String(160))
    source_version: Mapped[int] = mapped_column(Integer)
    source_digest: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(JSON)
    source: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PayrollStatutoryReceipt(Base):
    """Immutable source-bound import of reviewed deductions/contributions.

    The package carries amounts already calculated and verified by an external
    payroll source.  It does not infer Belarusian rates, create a tax return,
    or certify statutory reporting by itself.
    """
    __tablename__ = 'payroll_statutory_receipt'
    __table_args__ = (
        UniqueConstraint('organization_id', 'request_key', name='uq_payroll_statutory_request'),
        UniqueConstraint('organization_id', 'source_document', 'source_version',
                         name='uq_payroll_statutory_source'),
        CheckConstraint('source_version > 0', name='payroll_statutory_source_version_positive'),
        {'schema': 'accounting'},
    )
    entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.entry.id'), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    source_document: Mapped[str] = mapped_column(String(160))
    source_version: Mapped[int] = mapped_column(Integer)
    source_digest: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(JSON)
    source: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InputVatRegisterEntry(Base):
    """Immutable tax-register classification bound to one posted input-VAT line.

    The row records an accountant's reviewed source/evidence.  It never creates
    a deduction or a tax return entry by itself; statutory treatment remains an
    explicit, separately accepted step.
    """
    __tablename__ = 'input_vat_register_entry'
    __table_args__ = (
        UniqueConstraint('organization_id', 'request_key', name='uq_input_vat_register_request'),
        UniqueConstraint('organization_id', 'entry_id', 'line_id', name='uq_input_vat_register_line'),
        CheckConstraint('source_version > 0', name='input_vat_register_source_version_positive'),
        CheckConstraint(
            "deduction_status IN ('not_assessed','pending','eligible','not_eligible')",
            name='input_vat_register_deduction_status',
        ),
        CheckConstraint(
            "eschf_status IN ('not_provided','provided','not_required','pending')",
            name='input_vat_register_eschf_status',
        ),
        {'schema': 'accounting'},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.entry.id'), index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey('accounting.line.id'), index=True)
    source: Mapped[str] = mapped_column(String(160))
    source_version: Mapped[int] = mapped_column(Integer)
    entry_digest: Mapped[str] = mapped_column(String(64))
    posting_date: Mapped[date] = mapped_column(Date, index=True)
    tax_period: Mapped[str] = mapped_column(String(7), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3))
    side: Mapped[str] = mapped_column(String(6))
    invoice_reference: Mapped[str] = mapped_column(String(200))
    eschf_identifier: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deduction_status: Mapped[str] = mapped_column(String(20))
    eschf_status: Mapped[str] = mapped_column(String(20))
    right_basis: Mapped[str] = mapped_column(String(2000))
    evidence: Mapped[str] = mapped_column(String(2000))
    command: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutputVatRegisterEntry(Base):
    """Immutable evidence for one posted accrued-output-VAT line."""
    __tablename__ = 'output_vat_register_entry'
    __table_args__ = (
        UniqueConstraint('organization_id', 'request_key', name='uq_output_vat_register_request'),
        UniqueConstraint('organization_id', 'entry_id', 'line_id', name='uq_output_vat_register_line'),
        CheckConstraint('source_version > 0', name='output_vat_register_source_version_positive'),
        CheckConstraint(
            "tax_treatment IN ('not_assessed','pending','standard','zero_export','exempt','not_subject')",
            name='output_vat_register_tax_treatment',
        ),
        CheckConstraint(
            "eschf_status IN ('not_provided','provided','not_required','pending')",
            name='output_vat_register_eschf_status',
        ),
        {'schema': 'accounting'},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.entry.id'), index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey('accounting.line.id'), index=True)
    source: Mapped[str] = mapped_column(String(160))
    source_version: Mapped[int] = mapped_column(Integer)
    entry_digest: Mapped[str] = mapped_column(String(64))
    posting_date: Mapped[date] = mapped_column(Date, index=True)
    tax_period: Mapped[str] = mapped_column(String(7), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3))
    side: Mapped[str] = mapped_column(String(6))
    invoice_reference: Mapped[str] = mapped_column(String(200))
    eschf_identifier: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tax_treatment: Mapped[str] = mapped_column(String(20))
    eschf_status: Mapped[str] = mapped_column(String(20))
    treatment_basis: Mapped[str] = mapped_column(String(2000))
    export_evidence: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    evidence: Mapped[str] = mapped_column(String(2000))
    command: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ForeignTradeRegisterEntry(Base):
    """Immutable evidence for one posted import/export ledger line.

    This is a source-bound trade register, not a customs or VAT calculation
    engine.  The explicit trade mode, documents and rate evidence are kept
    with the exact posted line; no tax treatment or landed cost is inferred.
    """
    __tablename__ = 'foreign_trade_register_entry'
    __table_args__ = (
        UniqueConstraint('organization_id', 'request_key', name='uq_foreign_trade_register_request'),
        UniqueConstraint('organization_id', 'entry_id', 'line_id', name='uq_foreign_trade_register_line'),
        CheckConstraint('source_version > 0', name='foreign_trade_register_source_version_positive'),
        CheckConstraint(
            "trade_mode IN ('eaeu_import','third_country_import','export')",
            name='foreign_trade_register_trade_mode',
        ),
        CheckConstraint('amount > 0', name='foreign_trade_register_amount_positive'),
        CheckConstraint('customs_duty >= 0 AND import_vat >= 0',
                        name='foreign_trade_register_costs_nonnegative'),
        {'schema': 'accounting'},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.entry.id'), index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey('accounting.line.id'), index=True)
    source: Mapped[str] = mapped_column(String(160))
    source_version: Mapped[int] = mapped_column(Integer)
    entry_digest: Mapped[str] = mapped_column(String(64))
    posting_date: Mapped[date] = mapped_column(Date, index=True)
    tax_period: Mapped[str] = mapped_column(String(7), index=True)
    trade_mode: Mapped[str] = mapped_column(String(32), index=True)
    partner_country: Mapped[str] = mapped_column(String(64))
    contract_reference: Mapped[str] = mapped_column(String(200))
    invoice_reference: Mapped[str] = mapped_column(String(200))
    customs_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    eaeu_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    incoterms: Mapped[str | None] = mapped_column(String(16), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3))
    original_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    rate_scale: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rate_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customs_duty: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal('0'), server_default='0')
    import_vat: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal('0'), server_default='0')
    export_evidence: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    evidence: Mapped[str] = mapped_column(String(2000))
    command: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FixedAssetRegisterEntry(Base):
    """Immutable register row for one organization-owned fixed asset."""
    __tablename__ = 'fixed_asset_register_entry'
    __table_args__ = (
        UniqueConstraint('organization_id', 'request_key', name='uq_fixed_asset_register_request'),
        UniqueConstraint('organization_id', 'asset_key', name='uq_fixed_asset_register_asset_key'),
        UniqueConstraint('organization_id', 'source_entry_id', 'source_line_id',
                         name='uq_fixed_asset_register_source_line'),
        CheckConstraint('cost > 0', name='fixed_asset_register_cost_positive'),
        CheckConstraint('residual_value >= 0 AND residual_value <= cost',
                        name='fixed_asset_register_residual_bounds'),
        CheckConstraint('useful_life_months > 0', name='fixed_asset_register_life_positive'),
        CheckConstraint(
            "depreciation_method IN ('straight_line','declining_balance','production_units')",
            name='fixed_asset_register_method',
        ),
        {'schema': 'accounting'},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    asset_key: Mapped[str] = mapped_column(String(160), index=True)
    source_entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.entry.id'), index=True)
    source_line_id: Mapped[int] = mapped_column(ForeignKey('accounting.line.id'), index=True)
    source_digest: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    inventory_number: Mapped[str] = mapped_column(String(100))
    acquisition_date: Mapped[date] = mapped_column(Date)
    commissioning_date: Mapped[date] = mapped_column(Date)
    depreciation_start: Mapped[date] = mapped_column(Date)
    cost: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    residual_value: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    useful_life_months: Mapped[int] = mapped_column(Integer)
    depreciation_method: Mapped[str] = mapped_column(String(32))
    asset_account: Mapped[str] = mapped_column(String(32))
    accumulated_account: Mapped[str] = mapped_column(String(32))
    expense_account: Mapped[str] = mapped_column(String(32))
    dimensions: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[str] = mapped_column(String(2000))
    command: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FixedAssetDepreciationReceipt(Base):
    """Immutable monthly depreciation package bound to a fixed asset and entry."""
    __tablename__ = 'fixed_asset_depreciation_receipt'
    __table_args__ = (
        UniqueConstraint('organization_id', 'request_key', name='uq_fixed_asset_depreciation_request'),
        UniqueConstraint('organization_id', 'asset_id', 'month',
                         name='uq_fixed_asset_depreciation_asset_month'),
        {'schema': 'accounting'},
    )
    entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.entry.id'), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey('accounting.fixed_asset_register_entry.id'), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    command: Mapped[dict] = mapped_column(JSON)
    calculation: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RepairAccountingReceipt(Base):
    """Immutable reviewed repair source and ledger package.

    Customer-owned parts are retained in the command snapshot only and must
    never be represented as an owned inventory credit.
    """
    __tablename__ = 'repair_accounting_receipt'
    __table_args__ = (
        UniqueConstraint('organization_id', 'request_key', name='uq_repair_accounting_request'),
        UniqueConstraint('organization_id', 'service_request_id', 'source_version',
                         name='uq_repair_accounting_source'),
        CheckConstraint("coverage IN ('paid','warranty')", name='repair_accounting_coverage'),
        CheckConstraint("owner_type IN ('customer','organization')", name='repair_accounting_owner_type'),
        {'schema': 'accounting'},
    )
    entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.entry.id'), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), index=True)
    service_request_id: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    source_version: Mapped[int] = mapped_column(Integer)
    source_digest: Mapped[str] = mapped_column(String(64))
    serial_number: Mapped[str] = mapped_column(String(160))
    owner_type: Mapped[str] = mapped_column(String(16))
    owner_reference: Mapped[str] = mapped_column(String(200))
    coverage: Mapped[str] = mapped_column(String(16))
    command: Mapped[dict] = mapped_column(JSON)
    source: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    financial_result: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LateCostReceipt(Base):
    """Immutable source, calculation and candidate saved with a late-cost entry."""
    __tablename__ = "late_cost_receipt"
    __table_args__ = (
        UniqueConstraint("organization_id", "expense_id", name="uq_late_cost_source"),
        UniqueConstraint("organization_id", "request_key", name="uq_late_cost_request"),
        CheckConstraint("source_version > 0", name="late_cost_positive_version"),
        {"schema": "accounting"},
    )
    entry_id: Mapped[int] = mapped_column(ForeignKey("accounting.entry.id"), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    # Cross-module FK is installed by the complete PostgreSQL proposal.
    expense_id: Mapped[int]
    source_version: Mapped[int]
    request_key: Mapped[str] = mapped_column(String(36))
    command: Mapped[dict] = mapped_column(JSON)
    calculation: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SettlementOffsetReceipt(Base):
    """Immutable reviewed transfer of a bank-recorded advance to a target document."""
    __tablename__ = "settlement_offset_receipt"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_key", name="uq_settlement_offset_request"),
        UniqueConstraint("entry_id", name="uq_settlement_offset_entry"),
        CheckConstraint("amount > 0", name="settlement_offset_amount_positive"),
        CheckConstraint(
            "kind IN ('customer_advance','supplier_advance')",
            name="settlement_offset_kind_valid",
        ),
        {"schema": "accounting"},
    )
    entry_id: Mapped[int] = mapped_column(ForeignKey("accounting.entry.id"), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    bank_entry_id: Mapped[int] = mapped_column(ForeignKey("accounting.entry.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    target_document: Mapped[str] = mapped_column(String(160))
    source_account: Mapped[str] = mapped_column(String(32))
    target_account: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    document_date: Mapped[date] = mapped_column(Date)
    operation_date: Mapped[date] = mapped_column(Date)
    posting_date: Mapped[date] = mapped_column(Date, index=True)
    command: Mapped[dict] = mapped_column(JSON)
    command_digest: Mapped[str] = mapped_column(String(64))
    basis_digest: Mapped[str] = mapped_column(String(64))
    source_snapshot: Mapped[dict] = mapped_column(JSON)
    target_snapshot: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BankImportReceipt(Base):
    """Immutable binding of one finance bank transaction to one ledger entry."""
    __tablename__ = "bank_import_receipt"
    __table_args__ = (
        UniqueConstraint("organization_id", "source_transaction_id", name="uq_bank_import_source"),
        UniqueConstraint("organization_id", "request_key", name="uq_bank_import_request"),
        UniqueConstraint("entry_id", name="uq_bank_import_entry"),
        CheckConstraint("source_transaction_id > 0", name="bank_import_source_positive"),
        CheckConstraint("amount > 0", name="bank_import_amount_positive"),
        {"schema": "accounting"},
    )
    entry_id: Mapped[int] = mapped_column(ForeignKey("accounting.entry.id"), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("accounting.organization.id"), index=True)
    source_transaction_id: Mapped[int] = mapped_column(Integer, index=True)
    source_ext_id: Mapped[str] = mapped_column(String(128))
    source_digest: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(160))
    request_key: Mapped[str] = mapped_column(String(36))
    bank_account: Mapped[str] = mapped_column(String(32))
    settlement_account: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    document_date: Mapped[date] = mapped_column(Date)
    operation_date: Mapped[date] = mapped_column(Date)
    posting_date: Mapped[date] = mapped_column(Date, index=True)
    command: Mapped[dict] = mapped_column(JSON)
    command_digest: Mapped[str] = mapped_column(String(64))
    basis_digest: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductionOverheadReceipt(Base):
    __tablename__ = 'production_overhead_receipt'
    __table_args__ = (UniqueConstraint('organization_id', 'month', name='uq_production_overhead_month'),
                     UniqueConstraint('organization_id', 'request_key', name='uq_production_overhead_request'), {'schema': 'accounting'})
    entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.entry.id'), primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'))
    month: Mapped[str] = mapped_column(String(7))
    request_key: Mapped[str] = mapped_column(String(36))
    command: Mapped[dict] = mapped_column(JSON)
    review: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductionOverheadRevision(Base):
    __tablename__ = 'production_overhead_revision'
    __table_args__ = (UniqueConstraint('organization_id', 'request_key', name='uq_overhead_revision_request'),
        UniqueConstraint('original_entry_id', 'sequence', name='uq_overhead_revision_sequence'), {'schema': 'accounting'})
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'))
    original_entry_id: Mapped[int] = mapped_column(ForeignKey('accounting.production_overhead_receipt.entry_id'))
    sequence: Mapped[int]
    previous_id: Mapped[int | None] = mapped_column(ForeignKey('accounting.production_overhead_revision.id'), nullable=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey('accounting.entry.id'), nullable=True, unique=True)
    month: Mapped[str] = mapped_column(String(7))
    request_key: Mapped[str] = mapped_column(String(36))
    command: Mapped[dict] = mapped_column(JSON)
    preview: Mapped[dict] = mapped_column(JSON)
    posting: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductionOverheadWithdrawal(Base):
    __tablename__ = 'production_overhead_withdrawal'
    __table_args__ = {'schema': 'accounting'}
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    month: Mapped[str] = mapped_column(String(7))
    command: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductionOverheadCorrectionWithdrawal(Base):
    __tablename__ = 'production_overhead_correction_withdrawal'
    __table_args__ = {'schema': 'accounting'}
    organization_id: Mapped[int] = mapped_column(ForeignKey('accounting.organization.id'), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    month: Mapped[str] = mapped_column(String(7))
    command: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def immutable(mapper, connection, target):
    raise ValueError("Accounting history is immutable; append a new version or correction")


for _model in (Account, CatalogAdoption, Policy, Entry, Line, Audit, SourceBinding, SellerProfile,
               PayrollEmploymentBinding, PayrollRuleSet, PayrollEvidenceFile,
               PayrollWorkpaperReview,
               FinancialCloseReceipt, FinancialReopenReceipt, FinancialReopenItem,
               ShipmentAccountingReceipt, ShipmentPreparationDraft, InventoryIssueReceipt, InventorySaleReceipt,
               ProductionOutputTransferReceipt, ProductionLaborReceipt, PayrollAccrualReceipt,
               PayrollStatutoryReceipt,
               InputVatRegisterEntry, OutputVatRegisterEntry,
               FixedAssetRegisterEntry, FixedAssetDepreciationReceipt,
               RepairAccountingReceipt,
               FxRevaluationReceipt,
               LateCostReceipt, SettlementOffsetReceipt, BankImportReceipt, ProductionOverheadReceipt,
               ProductionOverheadWithdrawal,
               ProductionOverheadRevision, ProductionOutputCostRevision, ProductionOverheadCorrectionWithdrawal):
    event.listen(_model, "before_update", immutable)
    event.listen(_model, "before_delete", immutable)
