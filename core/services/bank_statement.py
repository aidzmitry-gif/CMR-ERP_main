"""Validated source facts for full statements; no authorization or ledger valuation.

Adapters must supply explicit direction, identity and provenance. Currency codes
are preserved as source facts: ingestion/posting must resolve them against the
organization's supported currencies and policy before accepting any movement.
The legacy incoming-only BankGateway contract is intentionally unchanged.
"""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BankStatementLine(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: str = Field(min_length=1, max_length=100)
    account_code: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=200)
    direction: Literal["receipt", "payment"]
    operation_date: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    amount: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+(?:\.[0-9]+)?$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    counterparty_name: str | None = Field(default=None, max_length=500)
    counterparty_identifier: str | None = Field(default=None, max_length=100)
    purpose: str = Field(max_length=4000)
    source_kind: Literal["file", "api"]
    source_reference: str = Field(min_length=1, max_length=500)

    @field_validator("provider", "account_code", "external_id", "source_reference")
    @classmethod
    def exact_identity(cls, value: str) -> str:
        if value != value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("Source identity must not contain surrounding whitespace or control characters")
        return value

    @field_validator("operation_date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, value: str) -> str:
        if Decimal(value) <= 0:
            raise ValueError("Statement amount must be positive; direction is a separate field")
        return value

    @property
    def source_identity(self) -> tuple[str, str, str]:
        """Identity is scoped by provider and account, never by amount or file name."""
        return self.provider, self.account_code, self.external_id
