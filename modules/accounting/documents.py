"""Explicit source documents for pilot rules; account choices belong to the book.

No legacy finance record is automatically treated as an accounting source.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from modules.accounting.schemas import Code, Input, LineInput, Money, PostingInput


class BankDocument(Input):
    source: str = Field(min_length=1, max_length=160)
    source_version: int = Field(ge=1)
    statement_reference: str = Field(min_length=1, max_length=160)
    document_date: date
    operation_date: date
    posting_date: date
    policy_id: int = Field(gt=0)
    direction: Literal["receipt", "payment"]
    bank_account: Code
    settlement_account: Code
    amount: Money
    bank_dimensions: dict[str, str] = Field(default_factory=dict)
    settlement_dimensions: dict[str, str] = Field(default_factory=dict)
    cash_activity: Literal["operating", "investing", "financing"]
    explanation: str = Field(min_length=1, max_length=700)

    @model_validator(mode="after")
    def distinct_accounts(self):
        if self.bank_account == self.settlement_account:
            raise ValueError("Bank and settlement accounts must be different")
        if self.amount <= 0:
            raise ValueError("Bank document amount must be positive")
        if self.bank_dimensions.get("bank_statement", self.statement_reference) != self.statement_reference:
            raise ValueError("Conflicting bank statement reference")
        return self

    def posting(self) -> PostingInput:
        receipt = self.direction == "receipt"
        return PostingInput(
            source=self.source, source_version=self.source_version,
            operation="bank_settlement", document_date=self.document_date,
            operation_date=self.operation_date, posting_date=self.posting_date,
            policy_id=self.policy_id, rule_version="bank-byn-v1",
            explanation=f"{self.explanation}; выписка: {self.statement_reference}",
            lines=[
                LineInput(account=self.bank_account, side="debit" if receipt else "credit",
                          amount=self.amount, dimensions={**self.bank_dimensions, "bank_statement": self.statement_reference},
                          cash_activity=self.cash_activity),
                LineInput(account=self.settlement_account, side="credit" if receipt else "debit",
                          amount=self.amount, dimensions=self.settlement_dimensions),
            ],
        )


async def preview_bank(session, org_id, document: BankDocument):
    from modules.accounting import service

    posting = document.posting()
    accounts, policy = await service.preview_posting(session, org_id, posting)
    if not accounts[document.bank_account].cash:
        raise service.AccountingError("Select an actual cash account for the bank side")
    if accounts[document.settlement_account].cash:
        raise service.AccountingError("Internal bank transfers require a separate rule")
    if accounts[document.settlement_account].category not in {"asset", "liability"}:
        raise service.AccountingError("This bank rule settles assets/liabilities; other operations need their own rule")
    return posting, accounts, policy
