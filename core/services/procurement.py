"""Procurement-owned primary sources for authorized accounting readers."""
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Protocol

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def exact_foreign_value(value):
    if isinstance(value, (float, bool)) or value is None:
        raise ValueError("Foreign purchase values require exact decimal strings")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid foreign purchase decimal") from exc
    if not result.is_finite():
        raise ValueError("Foreign purchase value must be finite")
    return result


class ReceiptForeignAmounts(BaseModel):
    """Original invoice amounts; the existing receipt amounts remain valued BYN."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    net_amount: Annotated[Decimal, BeforeValidator(exact_foreign_value),
                          Field(gt=0, max_digits=20, decimal_places=2)]
    vat_amount: Annotated[Decimal, BeforeValidator(exact_foreign_value),
                          Field(ge=0, max_digits=20, decimal_places=2)]


class ReceiptForeignExchange(BaseModel):
    """Explicit approved valuation facts, never a quote lookup or a default rate."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    rate: Annotated[Decimal, BeforeValidator(exact_foreign_value),
                    Field(gt=0, max_digits=24, decimal_places=6)]
    rate_scale: int = Field(gt=0, le=2147483647, strict=True)
    rate_date: date
    rate_source: str = Field(min_length=1, max_length=200)
    valuation_basis: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def original_currency(self):
        if self.currency == "BYN":
            raise ValueError("Foreign purchase currency must differ from BYN")
        return self


class ReceiptAutomaticOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, strict=True)
    posting_date: date


class ReceiptAccountingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1, strict=True)
    posting_date: date
    policy_id: int = Field(gt=0, strict=True)
    settlement_account: str = Field(min_length=1, max_length=20)
    vat_account: str | None = Field(max_length=20)
    inventory_accounts: list[str] = Field(min_length=1, max_length=300)


class ReceiptAccountingConfirmation(ReceiptAccountingOptions):
    digest: str = Field(min_length=64, max_length=64)


class ProcurementSourceGateway(Protocol):
    async def landed_financial_source(self, session: Any, organization_id: int,
                                      purchase_order_id: int, event_id: int) -> dict:
        """Lock the owned PO and verify the exact immutable calculation/event receipt.

        Caller holds the organization lock. This is cost, not cash or a posting.
        Historical receipts without the calculation cannot establish a new owner.
        """
        ...

    async def additional_expense_source(self, session: Any, organization_id: int, expense_id: int,
                                        expected_version: int) -> dict:
        """Read exact current expense revision and verify its stored receipt snapshots.

        Caller authorizes book access and holds its organization lock.
        """
        ...

    async def posted_receipt_basis(self, session: Any, organization_id: int, receipt_id: int,
                                   expected_version: int) -> dict:
        """Reconstruct purchase input using the immutable posting options and source.

        Accounting must compare this basis to the actual ledger package.
        """
        ...

    async def warehouse_receipt_source(self, session: Any, organization_id: int, receipt_id: int,
                                       expected_version: int) -> dict:
        """Lock and read exact primary revision with version-scoped line identities.

        Caller authorizes warehouse access and holds the organization lock.
        Missing units or unrepresentable physical quantities fail before creation.
        This returns source facts, not a warehouse SKU/unit mapping or stock receipt.
        """
        ...

    async def confirm_receipt(self, session: Any, organization_id: int, receipt_id: int,
                              command: ReceiptAccountingConfirmation, user: Any,
                              accounting: Any, event_bus: Any) -> dict:
        """Use the canonical posting command, retaining owner receipt and ledger atomically.

        Accounting verifies actor authority; caller owns commit/rollback.
        """
        ...

    async def prepare_receipt(self, session: Any, organization_id: int, receipt_id: int,
                              options: ReceiptAccountingOptions) -> dict:
        """Lock owned source, verify version and return facts plus chosen accounts.

        Caller authorizes accounting access and owns the transaction/org lock.
        Does not calculate ledger movements or alter source facts.
        """
        ...

    async def receipt_source(self, session: Any, organization_id: int, receipt_id: int) -> dict | None:
        """Read the posted revision, or current draft if unposted.

        Caller verifies book membership. No writes or transaction ownership.
        Missing owned source returns None; inconsistent history raises ValueError.
        """
        ...
