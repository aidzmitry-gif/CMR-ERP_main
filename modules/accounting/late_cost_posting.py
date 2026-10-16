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
    return _candidate(calculated, accounts, material=False)


def _candidate(calculated, accounts: ExpenseAccounts, *, material):
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
        elif share["destination"] == "disposed" or material and share["destination"] == "production":
            production = share["destination"] == "production"
            destinations = share.get("production_origins" if production else "expense_destinations")
            if not isinstance(destinations, list) or not destinations:
                raise AccountingError("Cost allocation requires authenticated destinations")
            if production:
                identities = [(row.get("entry_id"), row.get("inventory_line")) for row in destinations]
                if (any(type(value) is not int or value <= 0 for pair in identities for value in pair)
                    or len(set(identities)) != len(identities)
                    or any(row.get("expense_account", "").split(".")[0] != "20"
                           or not row.get("expense_dimensions") for row in destinations)):
                    raise AccountingError("Production origins must identify reviewed WIP postings")
            if any(Fraction(row["amount_byn"]) < 0 for row in destinations):
                raise AccountingError("Cost destination amount cannot be negative")
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


def material_candidate(calculated, accounts: ExpenseAccounts):
    """Internal first leg of an atomic package, never standalone posting approval.

    Uses only origins already included in the authenticated calculation. The
    package coordinator must resolve output revisions before committing it.
    """
    return _candidate(calculated, accounts, material=True)


def pool_candidate(calculated, accounts: ExpenseAccounts):
    """Internal v3 candidate; requires the future atomic pool writer to post.

    Preserve signed cent redistribution between actual surviving origins. A
    positive total additional cost can contain individual destination credits.
    """
    from modules.accounting.closing_commands import checksum
    from modules.accounting.schemas import LateCostPreviewInput

    if (calculated.get("calculation_version") != 3 or calculated.get("posted") is not False
            or calculated.get("basis_digest") != checksum({k: v for k, v in calculated.items() if k != "basis_digest"})):
        raise AccountingError("Pool candidate requires an unchanged internal calculation")
    request = LateCostPreviewInput.model_validate(calculated["request"])
    if accounts.settlement_account.split(".")[0] != "60":
        raise AccountingError("Additional expense requires supplier settlement account 60")
    if (sum(Fraction(row.amount_byn) for row in accounts.excluded_costs) != Fraction(request.excluded_amount_byn)
            or any(row.account.split(".")[0] not in {"18", "44", "90", "91"} for row in accounts.excluded_costs)):
        raise AccountingError("Excluded expense requires complete explicit VAT or expense classification")
    lines = []
    for destination in calculated["destinations"]:
        if destination["account"].split(".")[0] not in {"10", "41", "20", "44", "90", "91"}:
            raise AccountingError("Pool destination is not a supported inventory, WIP or expense account")
        amount = Decimal(destination["delta_byn"])
        if amount:
            lines.append(LineInput(account=destination["account"], side="debit" if amount > 0 else "credit",
                amount=amount.copy_abs(), dimensions=destination["dimensions"]))
    if sum(Fraction(line.amount) * (1 if line.side == "debit" else -1) for line in lines) != Fraction(request.capitalizable_amount_byn):
        raise AccountingError("Pool posting does not cover the capitalizable document value")
    lines.extend(LineInput(account=row.account, side="debit", amount=row.amount_byn, dimensions=row.dimensions)
                 for row in accounts.excluded_costs)
    document = calculated["document"]
    lines.append(LineInput(account=accounts.settlement_account, side="credit", amount=calculated["source_amount_byn"],
        dimensions={"counterparty": document["supplier"], "contract": document["contract"],
                    "settlement_document": document["invoice_reference"]}))
    return PostingInput(source=f"procurement:additional-expense:{calculated['expense_id']}",
        source_version=calculated["source_version"], operation="inventory_late_cost",
        document_date=document["document_date"], operation_date=document["operation_date"],
        posting_date=request.posting_date, policy_id=request.policy_id, rule_version="late-cost-pool-v3",
        explanation=request.classification_evidence, lines=lines)
