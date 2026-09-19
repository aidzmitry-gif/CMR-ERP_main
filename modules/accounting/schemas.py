"""Strict, versioned inputs; all money crosses the boundary as decimal strings."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def exact(value):
    if isinstance(value, (float, bool)) or value is None:
        raise ValueError("Use an exact decimal string, never float/null")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid decimal") from exc
    if not result.is_finite():
        raise ValueError("Amount must be finite")
    return result


Money = Annotated[Decimal, BeforeValidator(exact), Field(ge=0, max_digits=20, decimal_places=2)]
Quantity = Annotated[Decimal, BeforeValidator(exact), Field(gt=0, max_digits=24, decimal_places=6)]
Code = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[0-9]+(?:\.[0-9]+)*$")]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrganizationInput(Input):
    name: str = Field(min_length=1, max_length=200)
    unp: str = Field(pattern=r"^\d{9}$")


class SellerProfileInput(Input):
    source_key: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=0, strict=True)
    effective_from: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    address: str = Field(min_length=1, max_length=1000)
    account: str = Field(min_length=1, max_length=100)
    bank: str = Field(min_length=1, max_length=500)
    bik: str = Field(min_length=1, max_length=100)
    director: str = Field(min_length=1, max_length=300)
    phone: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=200)
    evidence: str = Field(min_length=1, max_length=2000)
    confirmed: bool = Field(strict=True)


class SourceBindingInput(Input):
    source_type: Literal["wms_receipt", "logistics_import", "finance_bank_transaction"]
    source_id: int = Field(gt=0, strict=True)
    ownership: Literal["own", "customer"]
    evidence: str = Field(min_length=10, max_length=1000)


class BankAccountMappingInput(Input):
    provider: str = Field(min_length=1, max_length=100)
    external_account: str = Field(min_length=1, max_length=128)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    valid_from: date
    ledger_account_id: int = Field(gt=0, strict=True)
    dimensions: dict[str, str] = Field(default_factory=dict)
    evidence: str = Field(min_length=10, max_length=1000)

    @model_validator(mode="after")
    def validate_dimensions(self):
        if any(not key.strip() or not value.strip() or len(key) > 100 or len(value) > 200
               or "\x00" in key or "\x00" in value for key, value in self.dimensions.items()):
            raise ValueError("Bank account mapping analytics must be nonempty and bounded")
        return self


class BankAccountMappingCloseInput(Input):
    valid_to: date
    evidence: str = Field(min_length=10, max_length=1000)


class GrantInput(Input):
    subject: str = Field(min_length=1, max_length=200)
    role: Literal["reader", "accountant", "chief"]


class AccountInput(Input):
    code: Code
    title: str = Field(min_length=1, max_length=200)
    category: Literal["asset", "liability", "equity", "income", "expense", "off_balance"]
    valid_from: date
    required_dimensions: list[Literal[
        "counterparty", "contract", "settlement_document", "warehouse", "sku", "lot",
        "order", "employee", "asset", "department", "owner", "serial",
    ]] = Field(default_factory=list)
    currency_tracking: bool = False
    quantity_tracking: bool = False
    cash: bool = False
    normative_ref: str = Field(min_length=1, max_length=200)


class CurrencyRevaluationPolicyInput(Input):
    """Explicit account roles for a reviewed FX revaluation.

    No account or gain/loss direction is inferred from a chart-of-accounts
    number.  The organisation policy must name every role and its analytics.
    """
    monetary_accounts: list[Code] = Field(min_length=1, max_length=200)
    gain_account: Code
    loss_account: Code
    gain_dimensions: dict[str, str] = Field(default_factory=dict)
    loss_dimensions: dict[str, str] = Field(default_factory=dict)
    reference: str = Field(min_length=10, max_length=1000)
    settlement_allocation: Literal["proportional_carrying"] | None = None
    settlement_rate_date: Literal["posting_date"] | None = None

    @model_validator(mode="after")
    def validate_roles(self):
        roles = [*self.monetary_accounts, self.gain_account, self.loss_account]
        if len(roles) != len(set(roles)):
            raise ValueError("Currency revaluation account roles must be distinct")
        for dimensions in (self.gain_dimensions, self.loss_dimensions):
            if any(not isinstance(key, str) or not key.strip() or len(key) > 100
                   or not isinstance(value, str) or not value.strip() or len(value) > 200
                   or "\x00" in key or "\x00" in value
                   for key, value in dimensions.items()):
                raise ValueError("Currency revaluation analytics must be nonempty and bounded")
        return self


class FinancialClosingInput(Input):
    monthly_accounts: list[Code] = Field(min_length=1, max_length=200)
    result_account: Code
    retained_earnings_account: Code
    year_end_month: int = Field(ge=1, le=12, strict=True)
    result_dimensions: dict[str, str]
    retained_dimensions: dict[str, str]
    opening_balance_treatment: Literal["include", "exclude"]
    reference: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def distinct_accounts(self):
        codes = [*self.monthly_accounts, self.result_account, self.retained_earnings_account]
        if len(codes) != len(set(codes)):
            raise ValueError("Closing account roles must be distinct and cannot repeat")
        for dimensions in (self.result_dimensions, self.retained_dimensions):
            if any(not k.strip() or not v.strip() or len(k) > 100 or len(v) > 200
                   or "\x00" in k or "\x00" in v for k, v in dimensions.items()):
                raise ValueError("Closing analytical identifiers must be nonempty and bounded")
        return self


class LateCostPolicyInput(Input):
    basis: Literal["quantity", "received_value"]
    rounding: Literal["largest_remainder_cent"]


class LateCostConversionInput(Input):
    """Exact source-document conversion required for a foreign late cost.

    The rate is evidence supplied by the accountant.  No provider, reserve or
    current-date lookup is implicit in this contract.
    """

    currency: str = Field(pattern=r"^[A-Z]{3}$")
    rate: Annotated[Decimal, BeforeValidator(exact), Field(gt=0, max_digits=24, decimal_places=12)]
    rate_scale: int = Field(gt=0, le=2147483647, strict=True)
    rate_date: date
    rate_source: str = Field(min_length=10, max_length=200)


class ProductionCostPolicyInput(Input):
    overhead_accounts: list[Code] = Field(min_length=1, max_length=200)
    wip_account: Code
    # No statutory account is inferred.  Until this is filled the production
    # output screen can only show a provisional cost basis.
    finished_goods_account: Code | None = None
    pool_dimensions: list[Literal['department']]
    order_dimension: Literal['order']
    rounding: Literal['largest_remainder_cent']
    reference: str = Field(min_length=10, max_length=1000)

    @model_validator(mode='after')
    def unique_roles(self):
        codes = [*self.overhead_accounts, self.wip_account]
        if self.finished_goods_account is not None:
            codes.append(self.finished_goods_account)
        if len(codes) != len(set(codes)) or len(self.pool_dimensions) != len(set(self.pool_dimensions)):
            raise ValueError('Production cost accounts and pool dimensions must not repeat')
        return self


class LateCostPreviewInput(Input):
    expected_version: int = Field(gt=0, strict=True)
    policy_id: int = Field(gt=0, strict=True)
    posting_date: date
    capitalizable_amount_byn: Money = Field(gt=0)
    excluded_amount_byn: Money
    classification_evidence: str = Field(min_length=10, max_length=1000)
    conversion: LateCostConversionInput | None = None


class PolicyInput(Input):
    effective_from: date
    reference: str = Field(min_length=1, max_length=200)
    inventory_method: Literal["fifo", "weighted_average", "specific"]
    allocation_basis: Literal["direct_cost", "labor_hours", "output_quantity"]
    depreciation_method: Literal["straight_line", "declining_balance", "production_units"]
    normative_reference: str = Field(min_length=1, max_length=200)
    normative_verified: bool = False
    financial_closing: FinancialClosingInput | None = None
    currency_revaluation: CurrencyRevaluationPolicyInput | None = None
    late_cost_allocation: LateCostPolicyInput | None = None
    production_costing: ProductionCostPolicyInput | None = None


class LineInput(Input):
    account: Code
    side: Literal["debit", "credit"]
    amount: Money
    dimensions: dict[str, str] = Field(default_factory=dict)
    currency: str = Field(default="BYN", pattern=r"^[A-Z]{3}$")
    original_amount: Money | None = None
    rate: Quantity | None = None
    rate_scale: int | None = Field(default=None, gt=0, le=2147483647)
    rate_date: date | None = None
    rate_source: str | None = Field(default=None, max_length=200)
    quantity: Quantity | None = None
    cash_activity: Literal["operating", "investing", "financing", "internal"] | None = None

    @model_validator(mode="after")
    def fx_complete(self):
        if self.currency != "BYN":
            if any(x is None for x in (self.original_amount, self.rate, self.rate_scale,
                                      self.rate_date, self.rate_source)) or not self.rate_source:
                raise ValueError("Foreign currency needs amount, rate, scale, date and source")
            # Round final cents once, independently of ambient Decimal precision.
            # Inputs are nonnegative; quotient/remainder implements half-up exactly.
            cents = Fraction(self.original_amount) * Fraction(self.rate) * 100 / self.rate_scale
            whole, remainder = divmod(cents.numerator, cents.denominator)
            converted_cents = whole + (2 * remainder >= cents.denominator)
            if converted_cents != Fraction(self.amount) * 100:
                raise ValueError("BYN amount does not match the documented exchange rate")
        elif any(x is not None for x in (self.original_amount, self.rate, self.rate_scale,
                                        self.rate_date, self.rate_source)):
            raise ValueError("BYN lines must not carry foreign-exchange metadata")
        if any(not k or not v.strip() or len(v) > 200 for k, v in self.dimensions.items()):
            raise ValueError("Analytical identifiers must be nonempty and bounded")
        return self


class PostingInput(Input):
    source: str = Field(min_length=1, max_length=160)
    source_version: int = Field(ge=1)
    operation: str = Field(min_length=1, max_length=60)
    document_date: date
    operation_date: date
    posting_date: date
    policy_id: int = Field(gt=0)
    rule_version: str = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=1, max_length=1000)
    lines: list[LineInput] = Field(min_length=1, max_length=1000)
    opening: bool = False
    correction_of: int | None = Field(default=None, gt=0)


class CloseInput(Input):
    expected_generation: int = Field(ge=0)
    evidence: dict[str, str]


class ReopenInput(Input):
    reason: str = Field(min_length=10, max_length=1000)


class FinancialCloseInput(CloseInput):
    request_key: UUID
    expected_basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class FinancialReopenInput(ReopenInput):
    request_key: UUID


class FinancialReopenConfirmInput(FinancialReopenInput):
    expected_basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class FxRateInput(Input):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    rate: Annotated[Decimal, BeforeValidator(exact), Field(gt=0, max_digits=24, decimal_places=12)]
    rate_scale: int = Field(gt=0, le=2147483647, strict=True)
    rate_date: date
    rate_source: str = Field(min_length=10, max_length=200)


class FxRevaluationInput(Input):
    request_key: UUID
    policy_id: int = Field(gt=0, strict=True)
    posting_date: date
    expected_generation: int = Field(ge=0, strict=True)
    rates: list[FxRateInput] = Field(min_length=1, max_length=100)
    evidence: str = Field(min_length=10, max_length=2000)


class FxRevaluationConfirmInput(FxRevaluationInput):
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ImportInput(Input):
    batch: str = Field(min_length=1, max_length=120)
    request_key: UUID
    protocol_version: Literal["opening-balance-v1"]
    source_system: str = Field(min_length=1, max_length=80)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    cutover_date: date
    evidence: str = Field(min_length=10, max_length=2000)
    expected_entry_count: int = Field(gt=0, le=500, strict=True)
    expected_line_count: int = Field(gt=0, le=1000, strict=True)
    expected_debit_byn: Money
    expected_credit_byn: Money
    entries: list[PostingInput] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_control_totals(self):
        if self.expected_entry_count != len(self.entries):
            raise ValueError("Opening import entry count does not match the package")
        line_count = sum(len(entry.lines) for entry in self.entries)
        if self.expected_line_count != line_count:
            raise ValueError("Opening import line count does not match the package")
        dates = {entry.posting_date for entry in self.entries}
        if dates != {self.cutover_date} or self.cutover_date.day != 1:
            raise ValueError("Opening import entries must share a first-of-month cutover date")
        if any(not entry.opening or entry.correction_of is not None for entry in self.entries):
            raise ValueError("Opening import accepts opening entries only")
        debit = sum((line.amount for entry in self.entries for line in entry.lines if line.side == "debit"), Decimal("0"))
        credit = sum((line.amount for entry in self.entries for line in entry.lines if line.side == "credit"), Decimal("0"))
        if debit != self.expected_debit_byn or credit != self.expected_credit_byn:
            raise ValueError("Opening import control totals do not match the package")
        if debit != credit:
            raise ValueError("Opening import control totals must balance")
        return self


class ReconciliationInput(Input):
    # Preserve original file bytes (including BOM/newlines) for evidence hashes.
    left_base64: str = Field(min_length=1, max_length=2_800_000)
    right_base64: str = Field(min_length=1, max_length=2_800_000)


class ReconciliationConfirmInput(ReconciliationInput):
    """Accept an exact, eligible OSV pair as accountant evidence."""

    request_key: UUID
    evidence: str = Field(min_length=10, max_length=2000)


class InventoryLotQuery(Input):
    policy_id: int = Field(gt=0)
    posting_date: date
    account: Code
    warehouse: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=200)
    search: str = Field(default="", max_length=200)


class InventoryIssuePreviewInput(Input):
    policy_id: int = Field(gt=0)
    posting_date: date
    account: Code
    warehouse: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=200)
    # Specific costing requires a lot; FIFO/weighted average may value the
    # selected warehouse/SKU across all explicit lots.
    lot: str = Field(default="", max_length=200)
    quantity: Quantity


class InventoryIssueDocument(InventoryIssuePreviewInput):
    source: str = Field(min_length=1, max_length=160)
    source_version: int = Field(ge=1)
    document_date: date
    operation_date: date
    expense_account: Code
    expense_dimensions: dict[str, str] = Field(default_factory=dict)
    explanation: str = Field(min_length=1, max_length=1000)


class InventoryIssueConfirm(InventoryIssueDocument):
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
