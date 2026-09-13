"""Explicit scope, configuration and exact money; never Sheet import bodies."""

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, model_validator

from modules.accounting.schemas import Input


def decimal_string(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?", value
    ):
        raise ValueError("Use a nonnegative exact decimal string with at most two decimal places")
    whole, _, fraction = value.partition(".")
    return whole + "." + fraction.ljust(2, "0")


Amount = Annotated[str, BeforeValidator(decimal_string)]
Id = Annotated[int, Field(gt=0, strict=True)]
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class Command(Input):
    request_key: UUID
    expected_revision: int = Field(ge=0, strict=True)
    evidence: str = Field(min_length=1, max_length=1000)


class CatalogCommand(Command):
    action: Literal[
        "template", "create_group", "create_article", "archive_group", "archive_article"
    ]
    code: Code | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    group_id: Id | None = None
    target_id: Id | None = None

    @model_validator(mode="after")
    def fields_for_action(self):
        expected = {
            "template": set(),
            "create_group": {"code", "title"},
            "create_article": {"code", "title", "group_id"},
            "archive_group": {"target_id"},
            "archive_article": {"target_id"},
        }[self.action]
        actual = {
            k for k in ("code", "title", "group_id", "target_id") if getattr(self, k) is not None
        }
        if actual != expected:
            raise ValueError("Fields do not match catalog action")
        return self


class BudgetLine(Input):
    article_id: Id
    months: list[Amount | None] = Field(min_length=12, max_length=12)


class BudgetCommand(Command):
    year: int = Field(ge=2000, le=2100, strict=True)
    currency: Literal["BYN"]
    basis: Literal["cash", "accrual"]
    expected_catalog_revision: int = Field(ge=0, strict=True)
    lines: list[BudgetLine] = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def distinct_articles(self):
        if len({v.article_id for v in self.lines}) != len(self.lines):
            raise ValueError("Duplicate article")
        self.lines.sort(key=lambda row: row.article_id)
        return self


class BudgetApprovalCommand(Input):
    """Approve one immutable budget version after a fresh readback."""

    request_key: UUID
    budget_id: Id
    expected_revision: int = Field(gt=0, strict=True)
    evidence: str = Field(min_length=1, max_length=1000)
