"""Reviewed transfers of an explicitly recorded advance to a settlement document.

An advance is not inferred from an invoice status or from a legacy finance row.
The accountant must identify the posted bank entry, the target document and the
two account roles.  The package is immutable and is saved together with its
ledger entry so a retry cannot create a second transfer.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import func, select

from modules.accounting import service
from modules.accounting.closing_commands import checksum
from modules.accounting.models import SettlementOffsetReceipt
from modules.accounting.schemas import Code, Input, LineInput, Money, PostingInput


class SettlementOffsetInput(Input):
    request_key: UUID
    bank_entry_id: int = Field(gt=0, strict=True)
    kind: Literal["customer_advance", "supplier_advance"]
    target_document: str = Field(min_length=1, max_length=160)
    target_account: Code
    target_dimensions: dict[str, str] = Field(default_factory=dict)
    amount: Money = Field(gt=0)
    document_date: date
    operation_date: date
    posting_date: date
    policy_id: int = Field(gt=0, strict=True)
    evidence: str = Field(min_length=10, max_length=2000)
    explanation: str = Field(min_length=1, max_length=700)

    @model_validator(mode="after")
    def target_identity(self):
        if self.target_dimensions.get("settlement_document") != self.target_document:
            raise ValueError("Target analytics must identify the exact settlement document")
        if any(not key.strip() or not value.strip() or len(key) > 100 or len(value) > 200
               or "\x00" in key or "\x00" in value
               for key, value in self.target_dimensions.items()):
            raise ValueError("Target analytics must be nonempty and bounded")
        return self


class SettlementOffsetConfirmInput(SettlementOffsetInput):
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def _posting(data: SettlementOffsetInput, fact: dict) -> PostingInput:
    if data.kind == "customer_advance":
        source_side, target_side = "debit", "credit"
    else:
        source_side, target_side = "credit", "debit"
    source_dimensions = dict(fact["settlement_dimensions"])
    source_dimensions.setdefault("settlement_document", f"bank-entry:{fact['entry_id']}")
    return PostingInput(
        source=f"accounting:settlement-offset:{data.request_key}",
        source_version=1,
        operation="settlement_offset",
        document_date=data.document_date,
        operation_date=data.operation_date,
        posting_date=data.posting_date,
        policy_id=data.policy_id,
        rule_version="settlement-offset-v1",
        explanation=f"{data.explanation}; основание: {data.target_document}",
        lines=[
            LineInput(account=fact["settlement_account"], side=source_side,
                      amount=data.amount, dimensions=source_dimensions),
            LineInput(account=data.target_account, side=target_side,
                      amount=data.amount, dimensions=dict(data.target_dimensions)),
        ],
    )


def _command_payload(data: SettlementOffsetInput) -> dict:
    return data.model_dump(mode="json", exclude={"basis_digest", "digest"})


async def _used(session, organization_id: int, bank_entry_id: int) -> Decimal:
    offsets = await session.scalar(select(func.coalesce(func.sum(SettlementOffsetReceipt.amount), 0)).where(
        SettlementOffsetReceipt.organization_id == organization_id,
        SettlementOffsetReceipt.bank_entry_id == bank_entry_id,
    ))
    # The same bank evidence must not be consumed once as an invoice payment
    # and again as an advance.  Sales owns the register, but the source entry
    # is a shared accounting identity and is always present in the full schema.
    from modules.sales.invoice_settlements import InvoiceSettlement

    invoice_allocations = await session.scalar(select(func.coalesce(func.sum(InvoiceSettlement.amount), 0)).where(
        InvoiceSettlement.organization_id == organization_id,
        InvoiceSettlement.bank_entry_id == bank_entry_id,
    ))
    return Decimal(offsets or 0) + Decimal(invoice_allocations or 0)


async def _basis(session, organization_id: int, user, data: SettlementOffsetInput, gateway):
    fact = await gateway.bank_settlement(session, organization_id, user, data.bank_entry_id)
    expected_direction = "receipt" if data.kind == "customer_advance" else "refund"
    if fact["direction"] != expected_direction:
        raise service.AccountingError(
            "Customer advances require a bank receipt; supplier advances require a bank payment"
        )
    used = await _used(session, organization_id, data.bank_entry_id)
    available = Decimal(fact["amount"]) - used
    if data.amount > available:
        raise service.AccountingError(
            f"The bank evidence has only {available:.2f} BYN available for this offset"
        )
    basis = {
        "bank": fact,
        "kind": data.kind,
        "target_document": data.target_document,
        "target_account": data.target_account,
        "target_dimensions": dict(data.target_dimensions),
        "amount": format(data.amount, "f"),
        "used_byn": format(used, "f"),
        "available_byn": format(available, "f"),
    }
    return fact, basis


async def prepare(session, organization_id: int, user, data: SettlementOffsetInput, gateway):
    command_digest = checksum(_command_payload(data))
    saved = await session.scalar(select(SettlementOffsetReceipt).where(
        SettlementOffsetReceipt.organization_id == organization_id,
        SettlementOffsetReceipt.request_key == str(data.request_key),
    ))
    if saved is not None:
        if saved.command_digest != command_digest:
            raise service.AccountingError("Settlement request key was reused with different facts")
        return {**saved.snapshot, "status": "posted", "entry_id": saved.entry_id,
                "digest": saved.digest, "basis_digest": saved.basis_digest,
                "command_digest": saved.command_digest}

    fact, basis = await _basis(session, organization_id, user, data, gateway)
    posting = _posting(data, fact)
    accounts, policy = await service.validate_posting(
        session, organization_id, posting, settlement_offset=True,
    )
    source = accounts.get(fact["settlement_account"])
    target = accounts.get(data.target_account)
    if source is None or target is None:
        raise service.AccountingError("Both settlement accounts must be effective on the posting date")
    if source.code == target.code:
        raise service.AccountingError("Advance offset source and target accounts must be different")
    if data.kind == "customer_advance":
        if fact["settlement_category"] != "liability" or source.category != "liability" or target.category != "asset":
            raise service.AccountingError("Customer advance offset requires liability source and asset target accounts")
    elif fact["settlement_category"] != "asset" or source.category != "asset" or target.category != "liability":
        raise service.AccountingError("Supplier advance offset requires asset source and liability target accounts")
    # Where the bank evidence has a party or contract, the target must name
    # the same one.  Missing source analytics remain a visible evidence gap;
    # they are never filled with a guessed party or contract.
    for key in ("counterparty", "contract"):
        if key in fact["settlement_dimensions"] and data.target_dimensions.get(key) != fact["settlement_dimensions"][key]:
            raise service.AccountingError(f"Target {key} does not match the bank evidence")
    basis_digest = checksum(basis)
    snapshot = {
        "command": _command_payload(data),
        "basis": basis,
        "posting": posting.model_dump(mode="json"),
        "source_account_title": source.title,
        "target_account_title": target.title,
        "normative_verified": policy.normative_verified,
    }
    return {**snapshot, "status": "preview", "basis_digest": basis_digest,
            "digest": service.digest(posting), "command_digest": command_digest,
            "entry_id": None}


async def confirm(session, organization_id: int, user, data: SettlementOffsetConfirmInput,
                  gateway, actor: str, event_bus=None):
    await service.lock_organization(session, organization_id)
    prepared = await prepare(session, organization_id, user, data, gateway)
    if prepared["status"] == "posted":
        return await session.get(SettlementOffsetReceipt, prepared["entry_id"])
    if prepared["basis_digest"] != data.basis_digest or prepared["digest"] != data.digest:
        raise service.AccountingError("Settlement preview is stale; calculate it again")
    posting = PostingInput.model_validate(prepared["posting"])
    entry = await service.post(session, organization_id, posting, actor, event_bus,
                               settlement_offset=True)
    receipt = SettlementOffsetReceipt(
        entry_id=entry.id,
        organization_id=organization_id,
        request_key=str(data.request_key),
        bank_entry_id=data.bank_entry_id,
        kind=data.kind,
        target_document=data.target_document,
        source_account=posting.lines[0].account,
        target_account=data.target_account,
        amount=data.amount,
        document_date=data.document_date,
        operation_date=data.operation_date,
        posting_date=data.posting_date,
        command=_command_payload(data),
        command_digest=prepared["command_digest"],
        basis_digest=data.basis_digest,
        source_snapshot=prepared["basis"]["bank"],
        target_snapshot={"document": data.target_document, "dimensions": dict(data.target_dimensions)},
        snapshot={key: prepared[key] for key in ("command", "basis", "posting", "source_account_title",
                                                  "target_account_title", "normative_verified")},
        posting=prepared["posting"],
        digest=data.digest,
        actor=actor,
    )
    session.add(receipt)
    await session.flush()
    return receipt


async def list_offsets(session, organization_id: int):
    return (await session.scalars(select(SettlementOffsetReceipt).where(
        SettlementOffsetReceipt.organization_id == organization_id,
    ).order_by(SettlementOffsetReceipt.posting_date, SettlementOffsetReceipt.entry_id))).all()
