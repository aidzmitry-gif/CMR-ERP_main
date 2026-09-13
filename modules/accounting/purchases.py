"""BYN receipt of owned inventory; input VAT is recorded, never deducted here."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import Field, model_validator

from modules.accounting import service
from modules.accounting.schemas import Code, Input, LineInput, Money, PostingInput, Quantity


class PurchaseItem(Input):
    order_id: int | None = Field(default=None, gt=0, strict=True)
    account: Code
    sku: str = Field(min_length=1, max_length=200)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    lot: str = Field(min_length=1, max_length=200)
    quantity: Quantity
    net_amount: Money
    vat_rate: Money = Field(le=100)
    vat_amount: Money
    vat_basis: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def amounts(self):
        if self.net_amount <= 0:
            raise ValueError("Purchase net amount must be positive")
        expected = (self.net_amount * self.vat_rate / Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        if self.vat_amount != expected:
            raise ValueError("VAT amount must match the explicit line rate and net amount")
        return self


class PurchaseDocument(Input):
    source: str = Field(min_length=1, max_length=160)
    source_version: int = Field(ge=1)
    document_date: date
    operation_date: date
    posting_date: date
    policy_id: int = Field(gt=0)
    invoice_reference: str = Field(min_length=1, max_length=200)
    counterparty: str = Field(min_length=1, max_length=200)
    contract: str = Field(min_length=1, max_length=200)
    warehouse: str = Field(min_length=1, max_length=200)
    settlement_account: Code
    vat_account: Code | None
    explanation: str = Field(min_length=1, max_length=700)
    items: list[PurchaseItem] = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def vat_account_matches_lines(self):
        if any(item.vat_amount for item in self.items):
            if self.vat_account is None:
                raise ValueError("Nonzero input VAT requires its account")
        elif self.vat_account is not None:
            raise ValueError("Zero VAT requires an explicit null VAT account")
        return self

    def posting(self):
        dimensions = {"counterparty": self.counterparty, "contract": self.contract,
                      "settlement_document": self.invoice_reference}
        lines = []
        gross = Decimal(0)
        for item in self.items:
            detail = {**dimensions, "warehouse": self.warehouse, "sku": item.sku,
                      "lot": item.lot, "vat_rate": str(item.vat_rate),
                      "vat_basis": item.vat_basis}
            if item.order_id is not None:
                detail["order"] = str(item.order_id)
            lines.append(LineInput(account=item.account, side="debit", amount=item.net_amount,
                                   quantity=item.quantity, dimensions=detail))
            if item.vat_amount:
                lines.append(LineInput(account=self.vat_account, side="debit",
                                       amount=item.vat_amount, dimensions=detail))
            gross += item.net_amount + item.vat_amount
        lines.append(LineInput(account=self.settlement_account, side="credit",
                               amount=gross, dimensions=dimensions))
        return PostingInput(source=self.source, source_version=self.source_version,
                            operation="inventory_purchase", document_date=self.document_date,
                            operation_date=self.operation_date, posting_date=self.posting_date,
                            policy_id=self.policy_id, rule_version="purchase-byn-v1",
                            explanation=self.explanation, lines=lines)


async def preview_purchase(session, org_id, document: PurchaseDocument):
    posting = document.posting()
    accounts, policy = await service.preview_posting(session, org_id, posting)
    # This bounded rule accepts only inventory/input VAT/supplier settlement roles.
    # Account names are versioned and configurable; synthetic roots define this rule.
    for item in document.items:
        account = accounts[item.account]
        if item.account.split(".")[0] not in {"10", "41"} or account.category != "asset" or account.cash:
            raise service.AccountingError("Purchase requires owned materials or goods accounts 10/41")
    supplier = accounts[document.settlement_account]
    if document.settlement_account.split(".")[0] != "60" or supplier.category != "liability" or supplier.cash:
        raise service.AccountingError("Purchase requires supplier settlement account 60")
    if document.vat_account is not None and document.vat_account.split(".")[0] != "18":
        raise service.AccountingError("Purchase VAT requires input VAT account 18, not a deduction")
    if any(item.vat_amount for item in document.items):
        vat = accounts[document.vat_account]
        if vat.category != "asset" or vat.cash:
            raise service.AccountingError("Input VAT must be an asset account")
    return posting, accounts, policy
