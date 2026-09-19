"""Full-statement source ingestion, separate from receivable matching.

The caller must authorize the chief accountant for the explicit organization
and own the transaction. No commit, allocation or ledger posting happens here.
"""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from core.services.bank_statement import BankStatementLine
from modules.accounting import service
from modules.accounting.bank_import import _digest
from modules.accounting.models import Period, SourceBinding
from modules.finance.models import BankTransaction


class StatementImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    line: BankStatementLine
    evidence: str = Field(min_length=1, max_length=1000)


def source_values(line: BankStatementLine) -> dict:
    if line.currency != "BYN":
        raise service.AccountingError("Full-statement ingestion currently requires BYN; FX policy is not configured")
    amount = Decimal(line.amount)
    if amount > Decimal("999999999999.99") or amount != amount.quantize(Decimal("0.01")):
        raise service.AccountingError("Bank amount exceeds storage precision; rounding is not allowed")
    # Preserve exact source text; reject overflow rather than silently truncating.
    for value, limit in ((line.account_code, 64), (line.counterparty_identifier, 32),
                         (line.counterparty_name, 255), (line.purpose, 512)):
        if value is not None and len(value) > limit:
            raise service.AccountingError("Bank source text exceeds storage capacity")
    return {
        "ext_id": "statement:" + _digest(line.source_identity),
        "direction": line.direction,
        "source_provider": line.provider,
        "source_external_id": line.external_id,
        "source_kind": line.source_kind,
        "source_reference": line.source_reference,
        "occurred_on": date.fromisoformat(line.operation_date),
        "amount": amount,
        "currency": line.currency,
        "payer_unp": line.counterparty_identifier,
        "payer_name": line.counterparty_name,
        "purpose": line.purpose,
        "account_code": line.account_code,
    }


async def ingest(session, org_id: int, line: BankStatementLine, *, evidence: str, actor: str):
    """Store an explicitly attributed source, or replay the same financial facts.

    First provenance is retained when the same transaction appears in a later
    file/API response. A caller must roll back uniqueness conflicts from a
    concurrent different-organization import; no partial package is committed.
    """
    if not evidence or not evidence.strip() or len(evidence) > 1000:
        raise service.AccountingError("Statement account ownership requires explicit evidence")
    if not actor or not actor.strip() or len(actor) > 200:
        raise service.AccountingError("Statement ownership requires an identified actor")
    values = source_values(line)
    await service.lock_organization(session, org_id)
    row = await session.scalar(select(BankTransaction).where(
        BankTransaction.ext_id == values["ext_id"],
    ).with_for_update().execution_options(populate_existing=True))
    if row is not None:
        binding = await session.scalar(select(SourceBinding).where(
            SourceBinding.source_type == "finance_bank_transaction",
            SourceBinding.source_id == row.id,
        ))
        if binding is None or binding.organization_id != org_id or binding.ownership != "own":
            raise service.AccountingError("Statement source is not bound to this organization")
        if any(getattr(row, key) != value for key, value in values.items()
               if key not in {"source_reference", "source_kind"}):
            raise service.AccountingError("Repeated bank identity has different financial facts")
        return row
    if await session.scalar(select(Period.id).where(
        Period.organization_id == org_id, Period.closed.is_(True),
        Period.month >= line.operation_date[:7],
    ).limit(1)) is not None:
        raise service.AccountingError("Bank source affects a closed period; review reopening before import")
    row = BankTransaction(**values, match_status="unmatched")
    session.add(row)
    await session.flush()
    session.add(SourceBinding(
        organization_id=org_id, source_type="finance_bank_transaction", source_id=row.id,
        ownership="own", evidence=evidence, actor=actor,
    ))
    await session.flush()
    service.audit(session, org_id, actor, "bank_statement_source_imported", {
        "source_transaction_id": row.id, "direction": line.direction,
        "provider": line.provider, "evidence": evidence,
    })
    return row
