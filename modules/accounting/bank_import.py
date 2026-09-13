"""Explicit bridge from an imported finance bank row to the accounting ledger.

The finance module owns bank polling and keeps the raw transaction.  Accounting
does not auto-post that row: a user supplies the book accounts, policy and
cash-flow activity, reviews the exact source snapshot, then confirms one
immutable ``bank_settlement`` package.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator
from sqlalchemy import select

from modules.accounting import service
from modules.accounting.documents import BankDocument, preview_bank
from modules.accounting.models import BankImportReceipt, Entry, SourceBinding
from modules.accounting.schemas import Code, Input, PostingInput
from modules.finance.models import BankTransaction


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _uuid(value: str) -> str:
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("Use a canonical request UUID") from exc
    return value


class BankImportInput(Input):
    request_key: str = Field(min_length=36, max_length=36)
    source_transaction_id: int = Field(gt=0, strict=True)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_id: int = Field(gt=0, strict=True)
    bank_account: Code
    settlement_account: Code
    bank_dimensions: dict[str, str] = Field(default_factory=dict)
    settlement_dimensions: dict[str, str] = Field(default_factory=dict)
    posting_date: date
    cash_activity: Literal["operating", "investing", "financing"]
    explanation: str = Field(min_length=1, max_length=700)

    @field_validator("request_key")
    @classmethod
    def canonical_request_key(cls, value):
        return _uuid(value)


class BankImportConfirmInput(BankImportInput):
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def source_snapshot(row: BankTransaction, *, allow_invalid=False) -> dict:
    try:
        if row.amount is None or isinstance(row.amount, bool):
            raise ValueError
        amount = Decimal(row.amount)
        if not amount.is_finite():
            raise ValueError
    except (InvalidOperation, TypeError, ValueError) as exc:
        if not allow_invalid:
            raise service.AccountingError("Imported bank transaction has an invalid monetary amount") from exc
        amount = None
    return {
        "transaction_id": row.id,
        "ext_id": row.ext_id,
        "occurred_on": row.occurred_on.isoformat() if row.occurred_on else None,
        "amount": format(amount, ".2f") if amount is not None else None,
        "currency": row.currency,
        "payer_unp": row.payer_unp,
        "payer_name": row.payer_name,
        "purpose": row.purpose,
        "account_code": row.account_code,
        "match_status": row.match_status,
    }


async def _source(session, org_id: int, source_transaction_id: int) -> tuple[BankTransaction, dict, str]:
    binding = await session.scalar(select(SourceBinding).where(
        SourceBinding.organization_id == org_id,
        SourceBinding.source_type == "finance_bank_transaction",
        SourceBinding.source_id == source_transaction_id,
    ))
    if binding is None or binding.ownership != "own":
        raise service.AccountingError(
            "Imported bank transaction has no explicit legal-entity binding; map it before posting"
        )
    row = await session.scalar(select(BankTransaction).where(
        BankTransaction.id == source_transaction_id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise service.AccountingError("Imported bank transaction was not found")
    snapshot = source_snapshot(row)
    if row.occurred_on is None or Decimal(row.amount) <= 0:
        raise service.AccountingError("Imported bank transaction has no positive dated amount")
    if row.currency != "BYN":
        raise service.AccountingError("Only BYN imported bank transactions are supported by this rule")
    return row, snapshot, _digest(snapshot)


def _command_body(data: BankImportInput) -> dict:
    # Confirmation carries two review digests.  They are evidence of the
    # preview, not part of the business command; excluding them keeps the
    # command and basis digests stable between preview and confirm.
    return data.model_dump(mode="json", exclude={"basis_digest", "digest"})


def _posting(data: BankImportInput, snapshot: dict) -> BankDocument:
    return BankDocument(
        source=f"finance:bank-transaction:{snapshot['transaction_id']}",
        source_version=1,
        statement_reference=snapshot["ext_id"],
        document_date=date.fromisoformat(snapshot["occurred_on"]),
        operation_date=date.fromisoformat(snapshot["occurred_on"]),
        posting_date=data.posting_date,
        policy_id=data.policy_id,
        direction="receipt",
        bank_account=data.bank_account,
        settlement_account=data.settlement_account,
        amount=snapshot["amount"],
        # The statement identity belongs to the imported source.  Preserve
        # optional caller dimensions, but never let a request replace the
        # source-bound reference used by the ledger and its SQL guard.
        bank_dimensions={
            **data.bank_dimensions,
            "bank_transaction_id": str(snapshot["transaction_id"]),
            "bank_statement": snapshot["ext_id"],
        },
        settlement_dimensions=data.settlement_dimensions,
        cash_activity=data.cash_activity,
        explanation=data.explanation,
    )


async def prepare(session, org_id: int, data: BankImportInput) -> dict:
    await service.lock_organization(session, org_id)
    _row, source, actual_digest = await _source(session, org_id, data.source_transaction_id)
    if actual_digest != data.source_digest:
        raise service.AccountingError("Imported bank source changed; refresh the source snapshot")
    existing = await session.scalar(select(BankImportReceipt).where(
        BankImportReceipt.organization_id == org_id,
        BankImportReceipt.source_transaction_id == data.source_transaction_id,
    ).with_for_update())
    command_digest = _digest(_command_body(data))
    if existing is not None:
        if existing.request_key != data.request_key or existing.command_digest != command_digest:
            raise service.AccountingError("Imported bank source is already bound to another accounting command")
        entry = await session.get(Entry, existing.entry_id)
        if entry is None or entry.digest != existing.digest:
            raise service.AccountingError("Imported bank receipt has no matching ledger entry")
        return {**existing.snapshot, "receipt_id": existing.entry_id, "posted": True,
                "confirmation_available": False}
    posting = _posting(data, source)
    posted, accounts, policy = await preview_bank(session, org_id, posting)
    basis = {"source": source, "source_digest": actual_digest,
             "command": _command_body(data), "posting": posted.model_dump(mode="json")}
    return {
        "organization_id": org_id,
        "source": posting.source,
        "source_transaction_id": data.source_transaction_id,
        "source_snapshot": source,
        "source_digest": actual_digest,
        "command_digest": command_digest,
        "basis_digest": _digest(basis),
        "posting": posted.model_dump(mode="json"),
        "digest": service.digest(posted),
        "normative_verified": policy.normative_verified,
        "confirmation_available": policy.normative_verified,
        "lines": [{**line.model_dump(mode="json"), "title": accounts[line.account].title}
                  for line in posted.lines],
        "posted": False,
        "statutory_certified": False,
    }


async def confirm(session, org_id: int, data: BankImportConfirmInput, actor, event_bus=None):
    await service.lock_organization(session, org_id)
    existing = await session.scalar(select(BankImportReceipt).where(
        BankImportReceipt.organization_id == org_id,
        BankImportReceipt.source_transaction_id == data.source_transaction_id,
    ).with_for_update())
    if existing is not None:
        command_digest = _digest(_command_body(data))
        if existing.request_key != data.request_key or existing.command_digest != command_digest:
            raise service.AccountingError("Imported bank source is already bound to another accounting command")
        if data.basis_digest != existing.basis_digest or data.digest != existing.digest:
            raise service.AccountingError("Imported bank confirmation digest differs from the saved package")
        entry = await session.get(Entry, existing.entry_id)
        if entry is None or entry.digest != existing.digest:
            raise service.AccountingError("Imported bank receipt has no matching ledger entry")
        return existing
    # A lost-response retry must be idempotent even if the finance matcher has
    # since updated mutable queue metadata (for example match_status).  Only a
    # new package needs the current source snapshot below.
    plan = await prepare(session, org_id, data)
    existing = await session.scalar(select(BankImportReceipt).where(
        BankImportReceipt.organization_id == org_id,
        BankImportReceipt.source_transaction_id == data.source_transaction_id,
    ).with_for_update())
    if existing is not None:
        if existing.request_key != data.request_key or existing.command_digest != plan["command_digest"]:
            raise service.AccountingError("Imported bank source is already bound to another accounting command")
        if data.basis_digest != existing.basis_digest or data.digest != existing.digest:
            raise service.AccountingError("Imported bank confirmation digest differs from the saved package")
        entry = await session.get(Entry, existing.entry_id)
        if entry is None or entry.digest != existing.digest:
            raise service.AccountingError("Imported bank receipt has no matching ledger entry")
        return existing
    if plan["basis_digest"] != data.basis_digest or plan["digest"] != data.digest:
        raise service.AccountingError("Imported bank calculation changed; preview it again")
    # The preview exposes the canonical ledger posting, not the source
    # document.  Revalidate that immutable package directly so the digest
    # confirmed by the user is exactly the one that will be persisted.
    posting = PostingInput.model_validate(plan["posting"])
    entry = await service.post(session, org_id, posting, actor, event_bus)
    snapshot = {**plan, "posting": posting.model_dump(mode="json"), "posted": True,
                "receipt_id": entry.id}
    row = BankImportReceipt(
        entry_id=entry.id,
        organization_id=org_id,
        source_transaction_id=data.source_transaction_id,
        source_ext_id=plan["source_snapshot"]["ext_id"],
        source_digest=plan["source_digest"],
        source=plan["source"],
        request_key=data.request_key,
        bank_account=data.bank_account,
        settlement_account=data.settlement_account,
        amount=Decimal(plan["source_snapshot"]["amount"]),
        document_date=posting.document_date,
        operation_date=posting.operation_date,
        posting_date=posting.posting_date,
        command=_command_body(data),
        command_digest=plan["command_digest"],
        basis_digest=plan["basis_digest"],
        snapshot=snapshot,
        posting=posting.model_dump(mode="json"),
        digest=plan["digest"],
        actor=actor,
    )
    session.add(row)
    await session.flush()
    return row


async def list_imports(session, org_id: int):
    return (await session.scalars(select(BankImportReceipt).where(
        BankImportReceipt.organization_id == org_id,
    ).order_by(BankImportReceipt.id.desc()))).all()


async def list_candidates(session, org_id: int, *, include_unbound=False):
    """Return source-bound queue facts needed by the accountant workspace.

    Finance owns the raw bank rows and has no legal-entity default.  The
    candidate response therefore exposes the source snapshot and its digest,
    while making the explicit binding decision visible to the UI.  No row is
    posted by this read operation.
    """
    rows = (await session.scalars(select(BankTransaction).order_by(BankTransaction.id.desc()))).all()
    bindings = (await session.scalars(select(SourceBinding).where(
        SourceBinding.source_type == "finance_bank_transaction",
    ))).all()
    receipts = (await session.scalars(select(BankImportReceipt).where(
        BankImportReceipt.organization_id == org_id,
    ))).all()
    binding_by_source = {row.source_id: row for row in bindings}
    receipt_by_source = {row.source_transaction_id: row for row in receipts}
    result = []
    for row in rows:
        binding = binding_by_source.get(row.id)
        if binding is None and not include_unbound:
            continue
        if binding is not None and binding.organization_id != org_id:
            continue
        snapshot = source_snapshot(row, allow_invalid=True)
        receipt = receipt_by_source.get(row.id)
        result.append({
            "source_snapshot": snapshot,
            "source_digest": _digest(snapshot) if snapshot["amount"] is not None else None,
            "source_error": "invalid_monetary_amount" if snapshot["amount"] is None else None,
            "binding_status": (
                "own" if binding is not None and binding.organization_id == org_id and binding.ownership == "own"
                else "other" if binding is not None
                else "unbound"
            ),
            "imported": receipt is not None,
            "entry_id": receipt.entry_id if receipt is not None else None,
        })
    return result
