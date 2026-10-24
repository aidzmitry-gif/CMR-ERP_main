"""Construct a balanced candidate from verified allocation, without posting it.

Value-only inventory lines require a dedicated authenticated cost-layer writer;
the ordinary posting service intentionally still rejects those candidates.
"""
from decimal import Decimal
from fractions import Fraction

from pydantic import Field

from modules.accounting.schemas import Code, Input, LineInput, Money, PostingInput
from modules.accounting.service import AccountingError


class ExcludedCost(Input):
    account: Code
    amount_byn: Money = Field(gt=0)
    dimensions: dict[str, str] = Field(default_factory=dict)


class ExpenseAccounts(Input):
    settlement_account: Code
    excluded_costs: list[ExcludedCost] = Field(default_factory=list, max_length=100)


def candidate(calculated, accounts: ExpenseAccounts):
    """Caller must obtain calculated from the internal authenticated preview."""
    history = calculated["history"]
    document = history["document"]
    conversion_verified = calculated.get("conversion_verified")
    if conversion_verified is None and document["currency"] == "BYN":
        # Preserve the authenticated shape of older internal previews; new
        # previews always carry this explicit flag.
        conversion_verified = True
    if (calculated.get("source_movements_verified") is not True
        or calculated.get("posted") is not False
        or conversion_verified is not True):
        raise AccountingError("A verified unposted allocation with explicit currency evidence is required")
    if accounts.settlement_account.split(".")[0] != "60":
        raise AccountingError("Additional expense requires supplier settlement account 60")
    excluded = Fraction(calculated["excluded_amount_byn"])
    if sum(Fraction(row.amount_byn) for row in accounts.excluded_costs) != excluded:
        raise AccountingError("Excluded amount must be covered exactly by explicit classifications")
    if any(row.account.split(".")[0] not in {"18", "44", "90", "91"} for row in accounts.excluded_costs):
        raise AccountingError("Classify excluded cost explicitly as input VAT or expense")
    links = {(link["receipt_id"], link["version"], link["line_number"]): link for link in history["receipt_sources"]}
    lines = []
    for share in calculated["shares"]:
        amount = Decimal(share["amount_byn"])
        if amount == 0:
            continue
        if share["destination"] == "remaining":
            link = links[(share["receipt_id"], share["version"], share["line_number"])]
            lines.append(LineInput(account=link["account"], side="debit", amount=amount,
                                   dimensions=link["inventory_dimensions"]))
        elif share["destination"] == "disposed":
            destinations = share["expense_destinations"]
            if sum(Fraction(row["amount_byn"]) for row in destinations) != Fraction(amount):
                raise AccountingError("Expense destinations do not cover the disposed share")
            for row in destinations:
                if Fraction(row["amount_byn"]) > 0:
                    lines.append(LineInput(account=row["expense_account"], side="debit",
                                           amount=row["amount_byn"], dimensions=row["expense_dimensions"]))
        else:
            raise AccountingError("Production cost requires its own verified cost-layer destination")
    settlement = {"counterparty": document["supplier"], "contract": document["contract"],
                  "settlement_document": document["invoice_reference"]}
    for row in accounts.excluded_costs:
        lines.append(LineInput(account=row.account, side="debit", amount=row.amount_byn, dimensions=row.dimensions))
    source_amount_byn = Decimal(calculated.get("source_amount_byn", document["amount"]))
    if sum(Fraction(line.amount) for line in lines) != Fraction(source_amount_byn):
        raise AccountingError("Candidate must cover the complete source liability")
    lines.append(LineInput(account=accounts.settlement_account, side="credit",
                           amount=source_amount_byn, dimensions=settlement))
    return PostingInput(source=f"procurement:additional-expense:{calculated['expense_id']}",
                        source_version=calculated["source_version"], operation="inventory_late_cost",
                        document_date=document["document_date"], operation_date=document["operation_date"],
                        posting_date=calculated["posting_date"], policy_id=calculated["policy_id"],
                        rule_version="late-cost-fx-v1" if document["currency"] != "BYN" else "late-cost-byn-v1",
                        explanation=calculated["classification_evidence"], lines=lines)
