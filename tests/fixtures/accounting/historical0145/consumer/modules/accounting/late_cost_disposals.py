"""Expand an authenticated disposed share into its original expense destinations."""
from fractions import Fraction

from modules.accounting.service import AccountingError


def disposal_shares(amount_byn, quantity, disposals):
    """Pure arithmetic; caller authenticates the complete source history.

    Quantity is the basis within the already allocated disposed share. Stable
    entry/line ordering breaks equal remainders and preserves source provenance.
    This does not authorize a ledger write or select a correction period.
    """
    cents, total = Fraction(amount_byn) * 100, Fraction(quantity)
    if cents < 0 or cents.denominator != 1 or total < 0:
        raise AccountingError("Invalid disposed amount or quantity")
    identities = [(row["entry_id"], row["inventory_line"]) for row in disposals]
    if (len(set(identities)) != len(identities)
        or any(type(value) is not int or value <= 0 for identity in identities for value in identity)):
        raise AccountingError("Duplicate or invalid disposal identity")
    rows = sorted(disposals, key=lambda row: (row["entry_id"], row["inventory_line"]))
    weights = [Fraction(row["quantity"]) for row in rows]
    if any(weight <= 0 for weight in weights) or sum(weights) != total:
        raise AccountingError("Disposal history does not cover its allocated quantity")
    if total == 0:
        if cents != 0:
            raise AccountingError("Cannot allocate expense without disposed quantity")
        return []
    quotas = [cents * weight / total for weight in weights]
    allocated = [quota.numerator // quota.denominator for quota in quotas]
    residual = cents.numerator - sum(allocated)
    for index in sorted(range(len(rows)), key=lambda i: -(quotas[i] - allocated[i]))[:residual]:
        allocated[index] += 1
    return [{**row, "amount_byn": f"{value // 100}.{value % 100:02d}"}
            for row, value in zip(rows, allocated, strict=True)]
