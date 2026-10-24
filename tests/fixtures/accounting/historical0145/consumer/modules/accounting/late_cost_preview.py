"""Read-only allocation using effective explicit policy and verified book history."""
from decimal import Decimal
from fractions import Fraction

from sqlalchemy import select

from core.domain.reference import Currency
from modules.accounting import service
from modules.accounting.closing_commands import checksum
from modules.accounting.late_cost_allocation import (
    AllocationInput,
    AllocationLot,
    preview_allocation,
)
from modules.accounting.late_cost_disposals import disposal_shares
from modules.accounting.late_cost_sources import expense_history
from modules.accounting.models import Policy
from modules.accounting.schemas import LateCostPolicyInput, LateCostPreviewInput


def _converted(original: Decimal, rate: Decimal, rate_scale: int) -> Decimal:
    """Convert an exact source amount to BYN and round half-up to kopecks."""
    value = Fraction(original) * Fraction(rate) * 100 / rate_scale
    whole, remainder = divmod(value.numerator, value.denominator)
    cents = whole + int(2 * remainder >= value.denominator)
    return Decimal(cents) / Decimal("100")


def _byn_amount(value: Decimal) -> str:
    """Stable two-decimal representation for persisted accounting evidence."""
    return format(value, ".2f")


async def validate_currency(session, source_currency: str, data: LateCostPreviewInput) -> None:
    """Reject an unknown or inactive foreign currency before costing."""
    if source_currency == "BYN":
        return
    conversion = data.conversion
    if conversion is None:
        return  # calculate() emits the stable missing-evidence error.
    active = await session.scalar(select(Currency.code).where(
        Currency.code == source_currency, Currency.is_active.is_(True)))
    if active is None:
        raise service.AccountingError(f"Unknown or inactive FX currency: {source_currency}")


async def preview(session, organization_id, expense_id, data: LateCostPreviewInput, procurement):
    await service.lock_organization(session, organization_id)
    policy = await session.scalar(select(Policy).where(Policy.organization_id == organization_id,
        Policy.effective_from <= data.posting_date).order_by(Policy.effective_from.desc()).limit(1))
    if (policy is None or policy.id != data.policy_id
        or policy.inventory_method not in {"specific", "fifo", "weighted_average"}):
        raise service.AccountingError("Select an applicable supported inventory valuation policy")
    history = await expense_history(session, organization_id, expense_id, data.expected_version, data.posting_date, procurement)
    await validate_currency(session, history["document"]["currency"], data)
    return calculate(organization_id, expense_id, data, policy, history)


def calculate(organization_id, expense_id, data, policy, history):
    """Reused by live preview and receipt verification after source authentication."""
    if policy.late_cost_allocation is None:
        raise service.AccountingError("Late-cost allocation method is not configured in this policy")
    inventory_method = getattr(policy, "inventory_method", "specific")
    if inventory_method not in {"specific", "fifo", "weighted_average"}:
        raise service.AccountingError("The selected inventory valuation method is not supported")
    rule = LateCostPolicyInput.model_validate(policy.late_cost_allocation)
    document = history["document"]
    source_currency = document["currency"]
    if source_currency == "BYN":
        if data.conversion is not None:
            raise service.AccountingError("BYN expense must not contain an FX conversion")
        source_amount_byn = Decimal(document["amount"])
        conversion = None
    else:
        conversion = data.conversion
        if conversion is None:
            raise service.AccountingError("Foreign expense requires a documented accounting conversion rule")
        if conversion.currency != source_currency:
            raise service.AccountingError("FX conversion currency must match the source document")
        if conversion.rate_date > data.posting_date:
            raise service.AccountingError("FX rate date cannot be after the late-cost posting date")
        source_amount_byn = _converted(Decimal(document["amount"]), conversion.rate, conversion.rate_scale)
    if Fraction(data.capitalizable_amount_byn) + Fraction(data.excluded_amount_byn) != Fraction(source_amount_byn):
        raise service.AccountingError("Capitalizable and excluded amounts must cover the source amount exactly")
    lots = [{key: lot[key] for key in AllocationLot.model_fields} for lot in history["lots"]]
    calculated = preview_allocation(AllocationInput(**rule.model_dump(), amount_byn=data.capitalizable_amount_byn, lots=lots))
    traces = {(lot["receipt_id"], lot["version"], lot["line_number"]): lot for lot in history["lots"]}
    for share in calculated["shares"]:
        if share["destination"] == "disposed":
            trace = traces[(share["receipt_id"], share["version"], share["line_number"])]
            share["expense_destinations"] = disposal_shares(share["amount_byn"], share["quantity"], trace["disposals"])
    basis = {"organization_id": organization_id, "expense_id": expense_id, "history": history["basis_digest"],
             "request": data.model_dump(mode="json"), "policy_id": policy.id, "rule": rule.model_dump(),
             "inventory_method": inventory_method,
             "source_amount_byn": _byn_amount(source_amount_byn),
             "conversion": conversion.model_dump(mode="json") if conversion is not None else None}
    return {**calculated, "organization_id": organization_id, "expense_id": expense_id,
            "source_version": data.expected_version, "posting_date": data.posting_date.isoformat(),
            "policy_id": policy.id, "inventory_method": inventory_method,
            "normative_verified": policy.normative_verified,
            "source_amount": document["amount"], "excluded_amount_byn": str(data.excluded_amount_byn),
            "source_amount_byn": _byn_amount(source_amount_byn),
            "conversion": conversion.model_dump(mode="json") if conversion is not None else None,
            "classification_evidence": data.classification_evidence, "history": history,
            "basis_digest": checksum(basis), "status": "preview", "source_movements_verified": True,
            "conversion_verified": source_currency == "BYN" or conversion is not None,
            "confirmation_available": False}
