"""Prepare, confirm and authenticate atomic late-material/output cost packages."""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select, text

from modules.accounting import service
from modules.accounting.closing_commands import checksum
from modules.accounting.late_cost_posting import material_candidate
from modules.accounting.late_cost_preview import preview
from modules.accounting.late_cost_receipts import MaterialLateCostCommand
from modules.accounting.models import ProductionOutputTransferReceipt
from modules.accounting.production_output_cost_workflow import (
    ProductionOutputCostPreviewInput,
    preview_output_cost_correction,
)
from modules.wms.production_material_issues import ProductionMaterialIssue


async def prepare(session, organization_id, expense_id, command, procurement):
    """Derive output identities on the server; no ledger or receipt writes."""
    await service.lock_organization(session, organization_id)
    calculated = await preview(session, organization_id, expense_id, command.allocation, procurement)
    if calculated["inventory_method"] != "specific":
        raise service.AccountingError("Late material package requires authenticated specific source layers")
    posting = material_candidate(calculated, command.accounts)
    from modules.accounting.late_cost_commands import validate_account_roles

    accounts, _ = await service.validate_posting(session, organization_id, posting, late_cost=True)
    validate_account_roles(posting, accounts, material=True)
    origins = [origin for share in calculated["shares"] if share["destination"] == "production"
               for origin in share.get("production_origins", []) if Decimal(origin["amount_byn"]) > 0]
    if not origins:
        raise service.AccountingError("Late material package requires a positive production allocation")
    grouped, wip = {}, []
    for origin in origins:
        prefix = f"production:material:{organization_id}:"
        if not origin.get("source", "").startswith(prefix):
            raise service.AccountingError("Material origin has no organization-bound source")
        binding = (await session.scalars(select(ProductionMaterialIssue).where(
            ProductionMaterialIssue.organization_id == organization_id,
            ProductionMaterialIssue.request_key == origin["source"][len(prefix):],
        ))).one_or_none()
        if binding is None:
            raise service.AccountingError("Material origin WMS order binding is unavailable")
        receipt = (await session.scalars(select(ProductionOutputTransferReceipt).where(
            ProductionOutputTransferReceipt.organization_id == organization_id,
            ProductionOutputTransferReceipt.order_id == binding.order_id,
        ))).one_or_none()
        debit = {"account": origin["expense_account"], "dimensions": origin["expense_dimensions"],
                 "amount_byn": origin["amount_byn"]}
        if receipt is None:
            wip.append({**origin, "order_id": binding.order_id})
            continue
        item = grouped.setdefault(receipt.entry_id, {"receipt": receipt, "debits": [], "origins": []})
        item["debits"].append(debit)
        item["origins"].append(origin)
    outputs = []
    for output_id, item in sorted(grouped.items()):
        receipt = item["receipt"]
        data = ProductionOutputCostPreviewInput(original_entry_id=output_id,
            posting_date=command.allocation.posting_date, request_evidence=command.allocation.classification_evidence)
        current = await preview_output_cost_correction(session, organization_id,
            command.allocation.posting_date.strftime("%Y-%m"), data)
        if current["ledger_evidence"]["matrix"]:
            raise service.AccountingError("Reconcile existing output cost differences before adding late material costs")
        raw = await session.scalar(text(
            "SELECT accounting.preview_output_cost_with_wip(:org,:output,:day,NULL,CAST(:debits AS jsonb),NULL)::text"
        ), {"org": organization_id, "output": output_id, "day": data.posting_date,
            "debits": json.dumps(item["debits"], sort_keys=True)})
        evidence = json.loads(raw, parse_float=str)
        outputs.append({"output_entry_id": output_id, "order_id": receipt.order_id,
            "amount_byn": format(sum((Decimal(row["amount_byn"]) for row in item["debits"]), Decimal(0)), ".2f"),
            "original_digest": receipt.digest, "original_basis_digest": receipt.basis_digest,
            "current_basis_digest": current["basis_digest"], "prospective_evidence": evidence,
            "origins": item["origins"]})
    expected_outputs = [{key: row[key] for key in ("output_entry_id", "amount_byn")} for row in outputs]
    if isinstance(command, MaterialLateCostCommand) and [row.model_dump(mode="json") for row in command.material_outputs] != expected_outputs:
        raise service.AccountingError("Selected outputs differ from authenticated material history")
    material_command = MaterialLateCostCommand(allocation=command.allocation, accounts=command.accounts,
                                               material_outputs=expected_outputs)
    result = {"organization_id": organization_id, "expense_id": expense_id,
        "command": material_command.model_dump(mode="json"), "calculation": calculated,
        "posting": posting.model_dump(mode="json"), "posting_digest": service.digest(posting),
        "outputs": outputs, "wip_origins": wip, "posted": False, "confirmation_available": False}
    return {**result, "basis_digest": checksum(result)}


def _matrix(rows):
    return sorted((row["account"], row["side"], json.dumps(row["dimensions"], sort_keys=True),
                   Decimal(str(row["amount"]))) for row in rows)


async def load_package(session, organization_id, entry_id, procurement):
    """Read the complete saved result using its historical evidence, never recost it."""
    from modules.accounting.late_cost_receipts import verify_receipt
    from modules.accounting.models import LateCostReceipt

    await service.lock_organization(session, organization_id)
    saved = await session.get(LateCostReceipt, entry_id)
    if saved is None or saved.organization_id != organization_id:
        raise service.AccountingError("Late material package was not found in this organization")
    if saved.command.get("command_version") != 2:
        raise service.AccountingError("A versioned late material package is required")
    package = (await session.execute(text(
        "SELECT basis_digest, preview FROM accounting.late_material_package "
        "WHERE late_entry_id=:entry AND organization_id=:org"
    ), {"entry": entry_id, "org": organization_id})).mappings().one_or_none()
    if package is None:
        raise service.AccountingError("Late material package evidence is missing")
    preview = package["preview"]
    if (not isinstance(preview, dict) or preview.get("basis_digest") != package["basis_digest"]
        or checksum({key: value for key, value in preview.items() if key != "basis_digest"}) != package["basis_digest"]):
        raise service.AccountingError("Late material package basis digest is inconsistent")
    await verify_receipt(session, organization_id, entry_id, procurement)
    await session.execute(text("SELECT accounting.verify_late_material_package(:entry)"), {"entry": entry_id})
    links = (await session.execute(text(
        "SELECT output_entry_id, output_revision_id, amount FROM accounting.late_material_output_cost_link "
        "WHERE late_entry_id=:entry AND organization_id=:org ORDER BY output_entry_id"
    ), {"entry": entry_id, "org": organization_id})).mappings().all()
    return {"organization_id": organization_id, "expense_id": saved.expense_id,
        "entry_id": entry_id, "source_version": saved.source_version,
        "request_key": saved.request_key, "digest": saved.digest,
        "basis_digest": package["basis_digest"], "command": saved.command,
        "preview": preview, "posted": True,
        "output_revisions": [{"output_entry_id": row["output_entry_id"],
            "output_revision_id": row["output_revision_id"], "amount_byn": format(row["amount"], ".2f")}
            for row in links]}


async def confirm(session, organization_id, expense_id, command: MaterialLateCostCommand,
                  request_key, expected_basis_digest, actor, procurement, event_bus=None):
    """Internal atomic package; outer caller owns the final transaction commit."""
    from uuid import uuid5

    from modules.accounting.late_cost_receipts import verify_receipt
    from modules.accounting.models import LateCostReceipt, SourceControl
    from modules.accounting.production_output_cost_workflow import (
        ProductionOutputCostConfirmInput,
        confirm_output_cost_correction,
    )
    from modules.accounting.schemas import PostingInput

    if not isinstance(command, MaterialLateCostCommand):
        raise service.AccountingError("A reviewed versioned material command is required")
    await service.lock_organization(session, organization_id)
    exists = await session.scalar(text("SELECT to_regclass('accounting.late_material_package') IS NOT NULL"))
    if exists is not True:
        raise service.AccountingError("Atomic late material package requires migration 0151")
    saved = await session.scalar(select(LateCostReceipt).where(
        LateCostReceipt.organization_id == organization_id,
        (LateCostReceipt.expense_id == expense_id) | (LateCostReceipt.request_key == str(request_key))))
    if saved is not None:
        package = (await session.execute(text(
            "SELECT basis_digest, preview FROM accounting.late_material_package WHERE late_entry_id=:entry"
        ), {"entry": saved.entry_id})).mappings().one_or_none()
        if (package is None or saved.expense_id != expense_id or saved.request_key != str(request_key)
            or saved.command != command.model_dump(mode="json") or saved.actor != actor
            or package["basis_digest"] != expected_basis_digest):
            raise service.AccountingError("Late material command conflicts with the saved package")
        await load_package(session, organization_id, saved.entry_id, procurement)
        return saved
    prepared = await prepare(session, organization_id, expense_id, command, procurement)
    if prepared["basis_digest"] != expected_basis_digest:
        raise service.AccountingError("Late material basis changed; preview again")
    posting = PostingInput.model_validate(prepared["posting"])
    control = await session.scalar(select(SourceControl).where(
        SourceControl.organization_id == organization_id, SourceControl.source == posting.source))
    if control is None or control.version != posting.source_version or control.entry_id is not None:
        raise service.AccountingError("Late material primary completeness state is inconsistent")
    # A caught downstream error must not leave a half-package in the outer transaction.
    async with session.begin_nested():
        entry = await service.post(session, organization_id, posting, actor, event_bus, late_cost=True)
        receipt = LateCostReceipt(entry_id=entry.id, organization_id=organization_id, expense_id=expense_id,
            source_version=posting.source_version, request_key=str(request_key), command=command.model_dump(mode="json"),
            calculation=prepared["calculation"], posting=prepared["posting"], digest=service.digest(posting), actor=actor)
        session.add(receipt)
        control.entry_id = entry.id
        await session.flush()
        await session.execute(text("""INSERT INTO accounting.late_material_package
            (late_entry_id, organization_id, basis_digest, preview)
            VALUES (:entry,:org,:basis,CAST(:preview AS jsonb))"""),
            {"entry": entry.id, "org": organization_id, "basis": expected_basis_digest,
             "preview": json.dumps(prepared, sort_keys=True)})
        for output in prepared["outputs"]:
            data = ProductionOutputCostPreviewInput(original_entry_id=output["output_entry_id"],
                posting_date=command.allocation.posting_date,
                request_evidence=f"Late material expense {expense_id}; entry {entry.id}")
            month = data.posting_date.strftime("%Y-%m")
            actual = await preview_output_cost_correction(session, organization_id, month, data)
            if _matrix(actual["ledger_evidence"]["matrix"]) != _matrix(output["prospective_evidence"]["matrix"]):
                raise service.AccountingError("Actual output correction differs from reviewed prospective matrix")
            revision = await confirm_output_cost_correction(session, organization_id, month,
                ProductionOutputCostConfirmInput(**data.model_dump(),
                    request_key=uuid5(request_key, f"output:{output['output_entry_id']}"),
                    basis_digest=actual["basis_digest"]), actor, event_bus)
            await session.execute(text("""INSERT INTO accounting.late_material_output_cost_link
                (late_entry_id, output_revision_id, organization_id, output_entry_id, amount, digest, source)
                VALUES (:entry,:revision,:org,:output,:amount,:digest,CAST(:source AS jsonb))"""),
                {"entry": entry.id, "revision": revision.id, "org": organization_id,
                 "output": output["output_entry_id"], "amount": Decimal(output["amount_byn"]),
                 "digest": entry.digest, "source": json.dumps(output, sort_keys=True)})
        await verify_receipt(session, organization_id, entry.id, procurement)
        await session.execute(text("SELECT accounting.verify_late_material_package(:entry)"), {"entry": entry.id})
        return receipt
