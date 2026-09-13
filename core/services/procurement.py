"""Procurement-owned primary sources for authorized accounting readers."""
from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


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
