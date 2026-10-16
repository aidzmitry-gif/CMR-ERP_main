"""Authenticate finished-goods layers created by reviewed production output."""
from datetime import date

from sqlalchemy import select

from modules.accounting.closing_commands import actual_posting
from modules.accounting.models import Entry, Line, ProductionOutputTransferReceipt
from modules.accounting.production_output_transfer import output_transfer_source_state
from modules.accounting.schemas import PostingInput, ProductionCostPolicyInput
from modules.accounting.service import AccountingError, digest


def is_finished_goods_account(policy, account: str) -> bool:
    if policy.production_costing is None:
        return False
    settings = ProductionCostPolicyInput.model_validate(policy.production_costing)
    return settings.finished_goods_account == account


async def verified_output_lines(session, organization_id: int, policy, account: str, through: date,
                                target: dict[str, str], *, before_entry_id: int | None = None):
    """Return exact debit line identities admitted as finished-goods layers.

    A finished-goods account is not a generic inventory allowlist: each debit
    must be the actual package of an immutable output-transfer receipt.  Source
    staleness is evaluated only through the caller's cutoff, preserving an old
    receipt's historical replay while preventing a new disposal on stale cost.
    """
    if not is_finished_goods_account(policy, account):
        raise AccountingError("Select the policy finished-goods account")
    query = select(ProductionOutputTransferReceipt).where(
        ProductionOutputTransferReceipt.organization_id == organization_id
    )
    if before_entry_id is not None:
        query = query.where(ProductionOutputTransferReceipt.entry_id < before_entry_id)
    receipts = (await session.scalars(query.order_by(ProductionOutputTransferReceipt.entry_id))).all()
    admitted = set()
    for receipt in receipts:
        entry = await session.get(Entry, receipt.entry_id)
        if entry is None or entry.posting_date > through:
            continue
        try:
            expected = PostingInput.model_validate(receipt.posting)
            actual = await actual_posting(session, entry)
        except (AttributeError, TypeError, ValueError) as exc:
            raise AccountingError("Finished-goods output receipt package is malformed") from exc
        lines = (await session.scalars(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))).all()
        debit = [(index, line) for index, line in enumerate(lines) if line.side == "debit"]
        if len(debit) != 1:
            raise AccountingError("Finished-goods output receipt has ambiguous debit layer")
        index, line = debit[0]
        if line.account_code != account:
            continue
        dimensions = line.dimensions or {}
        if (dimensions.get("warehouse") != target["warehouse"] or dimensions.get("sku") != target["sku"]
            or policy.inventory_method != "weighted_average"
            and target.get("lot") and dimensions.get("lot") != target["lot"]):
            continue
        command = receipt.command if isinstance(receipt.command, dict) else {}
        basis = receipt.basis if isinstance(receipt.basis, dict) else {}
        basis_target = basis.get("target") if isinstance(basis.get("target"), dict) else {}
        checks = {
            "receipt": isinstance(receipt.command, dict) and isinstance(receipt.basis, dict),
            "org": entry.organization_id == organization_id,
            "operation": entry.operation == "production_output_transfer",
            "source": entry.source == f"production:output-transfer:{organization_id}:{receipt.order_id}",
            "version": entry.source_version == 1,
            "digest": entry.digest == receipt.digest and digest(expected) == receipt.digest,
            "command": command.get("order_id") == receipt.order_id
            and command.get("basis_digest") == receipt.basis_digest and command.get("digest") == receipt.digest,
            "basis": basis.get("policy_id") == entry.policy_id
            and basis_target.get("finished_goods_account") == account,
            "posting": actual.model_dump() == expected.model_dump(),
        }
        if not all(checks.values()):
            raise AccountingError("Finished-goods output receipt does not match its ledger package: "
                                  + ", ".join(key for key, value in checks.items() if not value))
        if await output_transfer_source_state(
            session, receipt, through.strftime("%Y-%m"), through_date=through, before_entry_id=before_entry_id,
        ) != "unchanged":
            raise AccountingError("Finished-goods output cost basis is stale; correct output cost before disposal")
        if expected.lines[index].account != line.account_code:
            raise AccountingError("Finished-goods output receipt line order differs from ledger")
        if any(not dimensions.get(key) for key in ("warehouse", "sku", "lot")):
            raise AccountingError("Finished-goods output lacks warehouse, SKU or lot identity")
        if (line.category != "asset" or line.cash or line.currency != "BYN" or line.quantity is None
            or line.quantity <= 0 or line.amount <= 0):
            raise AccountingError("Finished-goods output layer is not a positive BYN inventory movement")
        admitted.add((entry.id, line.id))
    return frozenset(admitted)
