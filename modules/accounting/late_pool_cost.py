"""Prepare a complete, signed late-cost pool package without writing it."""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select, text

from modules.accounting import service
from modules.accounting.closing_commands import checksum
from modules.accounting.late_cost_commands import validate_account_roles
from modules.accounting.late_cost_pool import preview_expense
from modules.accounting.late_cost_posting import pool_candidate
from modules.accounting.late_cost_receipts import PoolLateCostCommand
from modules.accounting.models import ProductionOutputTransferReceipt
from modules.accounting.production_output_cost_workflow import (
    ProductionOutputCostPreviewInput,
    preview_output_cost_correction,
)
from modules.wms.production_material_issues import ProductionMaterialIssue


def _wip_destination(destination):
    return destination.get("account", "").split(".")[0] == "20"


async def _resolve_wip_origins(session, organization_id, calculated):
    """Bind every WIP value movement to its immutable material issue and order."""
    origins = []
    prefix = f"production:material:{organization_id}:"
    for pool in calculated["pools"]:
        for movement in pool["movements"]:
            destination = movement.get("destination")
            if not isinstance(destination, dict) or not _wip_destination(destination):
                continue
            if movement.get("kind") != "entry" or type(movement.get("entry_id")) is not int:
                raise service.AccountingError("WIP late-cost destination requires a material issue entry")
            source = destination.get("source", "")
            if not source.startswith(prefix) or not source[len(prefix):]:
                raise service.AccountingError("WIP late-cost destination has no organization-bound material source")
            binding = await session.scalar(select(ProductionMaterialIssue).where(
                ProductionMaterialIssue.organization_id == organization_id,
                ProductionMaterialIssue.request_key == source[len(prefix):],
            ))
            if binding is None:
                raise service.AccountingError("WIP late-cost material order binding is unavailable")
            amount = Decimal(movement["delta_byn"])
            if not amount:
                continue
            origins.append({
                "entry_id": movement["entry_id"],
                "order_id": binding.order_id,
                "source": source,
                "source_version": destination.get("source_version"),
                "account": destination["account"],
                "dimensions": destination["dimensions"],
                "amount_byn": format(amount, ".2f"),
                "pool": {"account": pool["account"], "warehouse": pool["warehouse"], "sku": pool["sku"]},
            })
    return origins


async def _resolve_outputs(session, organization_id, command, origins, procurement):
    """Project each released order using the signed, read-only SQL overlay."""
    grouped = {}
    wip = []
    for origin in origins:
        receipt = await session.scalar(select(ProductionOutputTransferReceipt).where(
            ProductionOutputTransferReceipt.organization_id == organization_id,
            ProductionOutputTransferReceipt.order_id == origin["order_id"],
        ))
        if receipt is None:
            wip.append(origin)
            continue
        grouped.setdefault(receipt.entry_id, {"receipt": receipt, "origins": []})["origins"].append(origin)

    outputs = []
    for output_id, item in sorted(grouped.items()):
        signed_amount = sum((Decimal(origin["amount_byn"]) for origin in item["origins"]), Decimal())
        if not signed_amount:
            raise service.AccountingError("Signed late-cost movements for one output net to zero; split and review them explicitly")
        receipt = item["receipt"]
        correction = ProductionOutputCostPreviewInput(
            original_entry_id=output_id,
            posting_date=command.allocation.posting_date,
            request_evidence=command.allocation.classification_evidence,
        )
        current = await preview_output_cost_correction(
            session, organization_id, command.allocation.posting_date.strftime("%Y-%m"), correction,
            procurement=procurement,
        )
        if current["ledger_evidence"]["matrix"]:
            raise service.AccountingError("Reconcile existing output cost differences before adding pool late costs")
        overlay = [{"account": origin["account"], "dimensions": origin["dimensions"],
                    "amount_byn": origin["amount_byn"]} for origin in item["origins"]]
        raw = await session.scalar(text(
            "SELECT accounting.preview_output_cost_with_signed_wip(:org,:output,:day,NULL,"
            "CAST(:overlay AS jsonb),NULL)::text"
        ), {"org": organization_id, "output": output_id, "day": command.allocation.posting_date,
            "overlay": json.dumps(overlay, sort_keys=True)})
        outputs.append({
            "output_entry_id": output_id,
            "order_id": receipt.order_id,
            "amount_byn": format(signed_amount, ".2f"),
            "original_digest": receipt.digest,
            "original_basis_digest": receipt.basis_digest,
            "current_basis_digest": current["basis_digest"],
            "prospective_evidence": json.loads(raw, parse_float=str),
            "origins": item["origins"],
        })
    return outputs, wip


async def prepare(session, organization_id, expense_id, command, procurement):
    """Return an immutable-review candidate. This function never posts or saves."""
    if not isinstance(command, PoolLateCostCommand):
        raise service.AccountingError("A reviewed version 3 pool late-cost command is required")
    await service.lock_organization(session, organization_id)
    calculated = await preview_expense(session, organization_id, expense_id, command.allocation, procurement)
    posting = pool_candidate(calculated, command.accounts)
    accounts, _ = await service.validate_posting(session, organization_id, posting, late_cost=True)
    validate_account_roles(posting, accounts, material=True)
    origins = await _resolve_wip_origins(session, organization_id, calculated)
    outputs, wip = await _resolve_outputs(session, organization_id, command, origins, procurement)
    expected_outputs = [{"output_entry_id": row["output_entry_id"], "amount_byn": row["amount_byn"]} for row in outputs]
    actual_outputs = [row.model_dump(mode="json") for row in command.material_outputs]
    if actual_outputs != expected_outputs:
        raise service.AccountingError("Selected pool outputs differ from authenticated WIP history")
    reviewed = PoolLateCostCommand(
        command_version=3,
        allocation=command.allocation,
        accounts=command.accounts,
        material_outputs=expected_outputs,
    )
    result = {
        "organization_id": organization_id,
        "expense_id": expense_id,
        "command": reviewed.model_dump(mode="json"),
        "calculation": calculated,
        "posting": posting.model_dump(mode="json"),
        "posting_digest": service.digest(posting),
        "outputs": outputs,
        "wip_origins": wip,
        "posted": False,
        "confirmation_available": False,
    }
    return {**result, "basis_digest": checksum(result)}
