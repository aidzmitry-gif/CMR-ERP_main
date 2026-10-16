"""Read-only bridge from an explicit foreign bank source to FX settlement quotes."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import Field
from sqlalchemy import select

from modules.accounting import bank_import, fx_cash_position, fx_settlement_preview, service
from modules.accounting.models import BankImportReceipt, SourceBinding
from modules.accounting.schemas import Code, FxRateInput, Input
from modules.finance.models import BankTransaction


class FxBankSettlementPreviewInput(Input):
    source_transaction_id: int = Field(gt=0, strict=True)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_id: int = Field(gt=0, strict=True)
    posting_date: date
    bank_account: Code
    bank_dimensions: dict[str, str] = Field(default_factory=dict)
    settlement_account: Code
    settlement_dimensions: dict[str, str] = Field(default_factory=dict)
    rate: FxRateInput


async def _source(session, org_id: int, data: FxBankSettlementPreviewInput) -> tuple[BankTransaction, dict, str]:
    binding = await session.scalar(select(SourceBinding).where(
        SourceBinding.organization_id == org_id,
        SourceBinding.source_type == "finance_bank_transaction",
        SourceBinding.source_id == data.source_transaction_id,
    ).with_for_update())
    if binding is None or binding.ownership != "own":
        raise service.AccountingError("Foreign bank source has no explicit own-organization binding")
    source = await session.scalar(select(BankTransaction).where(
        BankTransaction.id == data.source_transaction_id,
    ).with_for_update().execution_options(populate_existing=True))
    if source is None:
        raise service.AccountingError("Foreign bank source was not found")
    if any(not isinstance(value, str) or not value.strip() for value in (
        source.source_provider, source.source_external_id, source.source_kind, source.source_reference,
        source.account_code,
    )):
        raise service.AccountingError(
            "Foreign bank source lacks immutable statement provenance; current accounting import accepts BYN only"
        )
    if source.direction not in {"receipt", "payment"}:
        raise service.AccountingError("Foreign bank source has an unsupported direction")
    if source.match_status != "unmatched" or source.payment_id is not None or source.allocation_id is not None:
        raise service.AccountingError("Foreign bank source has already been consumed by finance matching")
    if await session.scalar(select(BankImportReceipt.entry_id).where(
        BankImportReceipt.organization_id == org_id,
        BankImportReceipt.source_transaction_id == source.id,
    ).limit(1)) is not None:
        raise service.AccountingError("Foreign bank source already has an accounting receipt")
    try:
        amount = Decimal(source.amount)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise service.AccountingError("Foreign bank source has an invalid amount") from exc
    if source.occurred_on is None or not amount.is_finite() or amount <= 0:
        raise service.AccountingError("Foreign bank source requires a positive amount and operation date")
    if source.currency == "BYN":
        raise service.AccountingError("Foreign bank settlement preview requires a non-BYN bank source")
    if source.occurred_on != data.posting_date or data.rate.rate_date != data.posting_date:
        raise service.AccountingError("Foreign bank source date and documented rate date must equal posting date")
    if source.currency != data.rate.currency:
        raise service.AccountingError("Documented rate currency does not match foreign bank source")
    snapshot = bank_import.source_snapshot(source)
    digest = bank_import._digest(snapshot)
    if digest != data.source_digest:
        raise service.AccountingError("Foreign bank source changed; refresh its immutable snapshot")
    return source, snapshot, digest


async def preview(session, org_id: int, data: FxBankSettlementPreviewInput) -> dict:
    """Quote the source-driven FX settlement without creating cash valuation or a posting."""
    await service.lock_organization(session, org_id)
    source, source_snapshot, source_digest = await _source(session, org_id, data)
    settlement = await fx_settlement_preview.preview(session, org_id, fx_settlement_preview.SettlementPreviewInput(
        policy_id=data.policy_id, posting_date=data.posting_date, account=data.settlement_account,
        dimensions=data.settlement_dimensions, amount=source.amount, rate=data.rate,
    ))
    balance = Decimal(settlement["original_balance"])
    accounts = await service.accounts_on(session, org_id, data.posting_date)
    settlement_account = accounts.get(data.settlement_account)
    if settlement_account is None:
        raise service.AccountingError("Settlement account is not effective for this organization")
    if source.direction == "receipt":
        if settlement_account.category != "asset" or balance <= 0:
            raise service.AccountingError("Receipt source can settle only a positive foreign receivable; advances are not supported")
    elif settlement_account.category != "liability" or balance >= 0:
        raise service.AccountingError("Payment source can settle only a negative foreign payable; advances are not supported")

    cash = await fx_cash_position.position(
        session, org_id, as_of=data.posting_date, account_code=data.bank_account,
        dimensions=data.bank_dimensions, currency=source.currency,
    )
    cash_before = Decimal(cash["original_balance"])
    cash_book_before = Decimal(cash["book_balance"])
    if source.direction == "payment" and (
        cash_before < 0 or cash_book_before < 0 or cash_before * cash_book_before < 0
        or (cash_before == 0 and cash_book_before != 0) or cash_before < source.amount
    ):
        raise service.AccountingError("Payment source exceeds the available positive foreign cash position")
    cash_after = cash_before + source.amount if source.direction == "receipt" else cash_before - source.amount
    bank_identity = {
        "transaction_id": source.id, "ext_id": source.ext_id, "direction": source.direction,
        "provider": source.source_provider, "external_id": source.source_external_id,
        "kind": source.source_kind, "reference": source.source_reference,
        "statement_account_code": source.account_code,
    }
    basis = {
        "organization_id": org_id, "source": source_snapshot, "source_digest": source_digest,
        "bank_identity": bank_identity, "input": data.model_dump(mode="json"),
        "settlement_basis_digest": settlement["basis_digest"], "settlement_basis": settlement["basis"],
        "cash_basis_digest": cash["basis_digest"], "cash_basis": cash["basis"],
        "cash_original_before": str(cash_before), "cash_original_after": str(cash_after),
    }
    return {
        "status": "preview_only", "posting_available": False, "cash_valuation_available": False,
        "basis_digest": bank_import._digest(basis), "basis": basis,
        "source": source_snapshot, "source_digest": source_digest,
        "settlement": settlement,
        "cash": {"currency": source.currency, "original_before": str(cash_before),
                 "original_after": str(cash_after), "book_before": cash["book_balance"],
                 "book_after": None},
        "unavailable": ["cash_valuation", "bank_posting", "foreign_source_import"],
    }
