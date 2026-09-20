"""Prepare and confirm a complete, signed late-cost pool package."""
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
from modules.accounting.models import Entry, Line, ProductionOutputTransferReceipt, SourceControl
from modules.accounting.production_output_cost_workflow import (
    ProductionOutputCostPreviewInput,
    preview_output_cost_correction,
)
from modules.accounting.schemas import LineInput, PostingInput
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
            source_lines = (await session.scalars(select(Line).where(
                Line.entry_id == movement["entry_id"],
                Line.side == "debit",
                Line.account_code == destination["account"],
            ))).all()
            source_lines = [line for line in source_lines if line.dimensions == destination["dimensions"]]
            if len(source_lines) != 1:
                raise service.AccountingError(
                    "WIP late-cost movement must resolve to one immutable material issue line")
            origins.append({
                "source_entry_id": movement["entry_id"],
                "source_line_id": source_lines[0].id,
                "order_id": binding.order_id,
                "source": source,
                "source_version": destination.get("source_version"),
                "account": destination["account"],
                "dimensions": destination["dimensions"],
                "amount_byn": format(amount, ".2f"),
                "pool": {"account": pool["account"], "warehouse": pool["warehouse"], "sku": pool["sku"]},
            })
    return origins


async def _store_inventory_value_links(session, package_id, entry, posting, calculated):
    """Bind each posted V3 inventory value line to its reviewed acquisition line.

    ``pool_candidate`` deliberately keeps destination order stable.  Verify the
    persisted order against the immutable PostingInput before using it as the
    source-line identity; matching only account and analytics would be unsafe
    when a package contains equal-looking value adjustments.
    """
    actual_lines = (await session.scalars(select(Line).where(Line.entry_id == entry.id)
                                          .order_by(Line.id))).all()
    if len(actual_lines) != len(posting.lines):
        raise service.AccountingError("V3 pool posting line count changed before immutable linking")
    for actual, expected in zip(actual_lines, posting.lines, strict=True):
        if (actual.account_code != expected.account or actual.side != expected.side
                or Decimal(actual.amount) != Decimal(expected.amount)
                or actual.dimensions != expected.dimensions or actual.quantity != expected.quantity):
            raise service.AccountingError("V3 pool posting line order changed before immutable linking")
    expected_index = 0
    linked = 0
    for destination in calculated["destinations"]:
        amount = Decimal(destination["delta_byn"])
        if not amount:
            continue
        if expected_index >= len(actual_lines):
            raise service.AccountingError("V3 pool destination has no posted ledger line")
        actual = actual_lines[expected_index]
        expected_index += 1
        if destination.get("kind") != "inventory":
            continue
        source_entry_id, source_line_id = destination.get("source_entry_id"), destination.get("source_line_id")
        if (actual.account_code != destination.get("account") or actual.account_code.split(".")[0] not in {"10", "41"}
                or actual.dimensions != destination.get("dimensions")
                or actual.side != ("debit" if amount > 0 else "credit")
                or Decimal(actual.amount) != amount.copy_abs() or actual.quantity is not None
                or type(source_entry_id) is not int or source_entry_id <= 0
                or type(source_line_id) is not int or source_line_id <= 0):
            raise service.AccountingError("V3 inventory destination differs from its reviewed acquisition origin")
        await session.execute(text("""
            INSERT INTO accounting.late_pool_inventory_value_link
              (package_id, value_entry_id, value_line_id, acquisition_entry_id, acquisition_line_id)
            VALUES (:package,:value_entry,:value_line,:acquisition_entry,:acquisition_line)
        """), {"package": package_id, "value_entry": entry.id, "value_line": actual.id,
                "acquisition_entry": source_entry_id, "acquisition_line": source_line_id})
        linked += 1
    if expected_index > len(actual_lines):
        raise service.AccountingError("V3 pool destinations exceed posted ledger lines")
    return linked


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
        evidence = json.loads(raw, parse_float=str)
        original = await session.get(Entry, output_id)
        if original is None or original.organization_id != organization_id:
            raise service.AccountingError("Released output entry is unavailable in this organization")
        prospective = PostingInput(
            source=f"accounting:late-pool-preview:{organization_id}:{output_id}",
            source_version=1,
            operation="production_output_cost_correction",
            document_date=command.allocation.posting_date,
            operation_date=command.allocation.posting_date,
            posting_date=command.allocation.posting_date,
            policy_id=original.policy_id,
            rule_version="production-output-cost-revision-v1",
            explanation=command.allocation.classification_evidence,
            correction_of=output_id,
            lines=[LineInput(**{**row, "amount": f"{Decimal(str(row['amount'])):.2f}"})
                   for row in evidence["matrix"]],
        )
        await service.validate_posting(
            session, organization_id, prospective, production_output_correction=True)
        outputs.append({
            "output_entry_id": output_id,
            "order_id": receipt.order_id,
            "amount_byn": format(signed_amount, ".2f"),
            "original_digest": receipt.digest,
            "original_basis_digest": receipt.basis_digest,
            "current_basis_digest": current["basis_digest"],
            "prospective_evidence": evidence,
            "origins": item["origins"],
        })
    return outputs, wip


def _matrix(rows):
    return sorted((row["account"], row["side"], json.dumps(row["dimensions"], sort_keys=True),
                   Decimal(str(row["amount"]))) for row in rows)


def _verified_preview(saved):
    """Reject a malformed stored package before returning historical evidence."""
    preview = saved["preview"]
    if (not isinstance(preview, dict) or preview.get("basis_digest") != saved["basis_digest"]
            or checksum({key: value for key, value in preview.items() if key != "basis_digest"})
            != saved["basis_digest"]):
        raise service.AccountingError("Late pool package basis digest is inconsistent")
    if (preview.get("organization_id") != saved["organization_id"]
            or preview.get("posting_digest") != saved["digest"]
            or preview.get("command") != saved["command"]
            or preview.get("calculation") != saved["calculation"]
            or preview.get("posting") != saved["posting"]):
        raise service.AccountingError("Late pool package evidence is incomplete")
    return preview


async def load_package(session, organization_id, entry_id):
    """Read an immutable V3 package without recosting current source documents."""
    await service.lock_organization(session, organization_id)
    saved = (await session.execute(text("""
        SELECT id, organization_id, request_key, late_entry_id, command, calculation,
               preview, posting, basis_digest, digest, actor
        FROM accounting.late_pool_package
        WHERE late_entry_id=:entry AND organization_id=:org
    """), {"entry": entry_id, "org": organization_id})).mappings().one_or_none()
    if saved is None:
        raise service.AccountingError("Late pool package was not found in this organization")
    preview = _verified_preview(saved)
    await session.execute(text("SELECT accounting.verify_late_pool_package(:package)"),
                          {"package": saved["id"]})
    links = (await session.execute(text("""
        SELECT output_entry_id, output_revision_id, amount
        FROM accounting.late_pool_output_cost_link
        WHERE package_id=:package
        ORDER BY output_entry_id
    """), {"package": saved["id"]})).mappings().all()
    inventory_links = (await session.execute(text("""
        SELECT value_entry_id, value_line_id, acquisition_entry_id, acquisition_line_id
        FROM accounting.late_pool_inventory_value_link
        WHERE package_id=:package
        ORDER BY value_line_id
    """), {"package": saved["id"]})).mappings().all()
    return {
        "organization_id": organization_id,
        "expense_id": preview["expense_id"],
        "entry_id": saved["late_entry_id"],
        "request_key": str(saved["request_key"]),
        "digest": saved["digest"],
        "basis_digest": saved["basis_digest"],
        "command": saved["command"],
        "preview": preview,
        "posted": True,
        "output_revisions": [{
            "output_entry_id": row["output_entry_id"],
            "output_revision_id": row["output_revision_id"],
            "amount_byn": format(row["amount"], ".2f"),
        } for row in links],
        "inventory_value_links": [{
            "value_entry_id": row["value_entry_id"], "value_line_id": row["value_line_id"],
            "acquisition_entry_id": row["acquisition_entry_id"],
            "acquisition_line_id": row["acquisition_line_id"],
        } for row in inventory_links],
    }


async def confirm(session, organization_id, expense_id, command: PoolLateCostCommand,
                  request_key, expected_basis_digest, actor, procurement, event_bus=None, *, expected_digest=None):
    """Atomically post the V3 pool ledger entry, output revisions and evidence package."""
    from uuid import uuid5

    from modules.accounting.production_output_cost_workflow import (
        ProductionOutputCostConfirmInput,
        confirm_output_cost_correction,
    )

    if not isinstance(command, PoolLateCostCommand):
        raise service.AccountingError("A reviewed version 3 pool late-cost command is required")
    await service.lock_organization(session, organization_id)
    exists = await session.scalar(text("SELECT to_regclass('accounting.late_pool_inventory_value_link') IS NOT NULL"))
    if exists is not True:
        raise service.AccountingError("Atomic late pool package requires migration 0155")
    saved_rows = (await session.execute(text("""
        SELECT id, organization_id, request_key, late_entry_id, command, calculation,
               preview, posting, basis_digest, digest, actor
        FROM accounting.late_pool_package
        WHERE organization_id=:org
          AND (request_key=CAST(:request_key AS uuid) OR preview->>'expense_id'=:expense_id)
    """), {"org": organization_id, "request_key": str(request_key),
            "expense_id": str(expense_id)})).mappings().all()
    if saved_rows:
        if len(saved_rows) != 1:
            raise service.AccountingError("Late pool package identity is inconsistent")
        saved = saved_rows[0]
        if (str(saved["request_key"]) != str(request_key)
                or saved["command"] != command.model_dump(mode="json")
                or saved["actor"] != actor
                or saved["basis_digest"] != expected_basis_digest
                or expected_digest is not None and saved["digest"] != expected_digest
                or _verified_preview(saved).get("expense_id") != expense_id):
            raise service.AccountingError("Late pool command conflicts with the saved package")
        await load_package(session, organization_id, saved["late_entry_id"])
        return await session.get(Entry, saved["late_entry_id"])
    prepared = await prepare(session, organization_id, expense_id, command, procurement)
    if prepared["basis_digest"] != expected_basis_digest:
        raise service.AccountingError("Late pool basis changed; preview again")
    if expected_digest is not None and prepared["posting_digest"] != expected_digest:
        raise service.AccountingError("Late pool posting changed; preview again")
    posting = PostingInput.model_validate(prepared["posting"])
    control = await session.scalar(select(SourceControl).where(
        SourceControl.organization_id == organization_id,
        SourceControl.source == posting.source,
    ))
    if control is None or control.version != posting.source_version or control.entry_id is not None:
        raise service.AccountingError("Late pool primary completeness state is inconsistent")
    # The package guard is deferred.  The savepoint makes every linked output
    # revision and the source-control resolution disappear on any failure.
    async with session.begin_nested():
        entry = await service.post(session, organization_id, posting, actor, event_bus, late_cost=True)
        control.entry_id = entry.id
        package_id = await session.scalar(text("""
            INSERT INTO accounting.late_pool_package
              (organization_id, request_key, late_entry_id, command, calculation, preview,
               posting, basis_digest, digest, actor)
            VALUES (:org,CAST(:request_key AS uuid),:entry,CAST(:command AS jsonb),
                    CAST(:calculation AS jsonb),CAST(:preview AS jsonb),CAST(:posting AS jsonb),
                    :basis,:digest,:actor)
            RETURNING id
        """), {
            "org": organization_id, "request_key": str(request_key), "entry": entry.id,
            "command": json.dumps(prepared["command"], sort_keys=True),
            "calculation": json.dumps(prepared["calculation"], sort_keys=True),
            "preview": json.dumps(prepared, sort_keys=True),
            "posting": json.dumps(prepared["posting"], sort_keys=True),
            "basis": expected_basis_digest, "digest": prepared["posting_digest"], "actor": actor,
        })
        await _store_inventory_value_links(session, package_id, entry, posting, prepared["calculation"])
        for output in prepared["outputs"]:
            data = ProductionOutputCostPreviewInput(
                original_entry_id=output["output_entry_id"],
                posting_date=command.allocation.posting_date,
                request_evidence=f"Late pool expense {expense_id}; entry {entry.id}",
            )
            month = data.posting_date.strftime("%Y-%m")
            actual = await preview_output_cost_correction(
                session, organization_id, month, data, procurement=procurement)
            actual_raw = await session.scalar(text(
                "SELECT accounting.output_cost_revision_evidence(:org,:output,:day,NULL)::text"
            ), {"org": organization_id, "output": output["output_entry_id"],
                "day": data.posting_date})
            actual_evidence = json.loads(actual_raw, parse_float=str)
            if _matrix(actual_evidence["matrix"]) != _matrix(
                    output["prospective_evidence"]["matrix"]):
                raise service.AccountingError(
                    "Actual output correction differs from reviewed prospective matrix")
            revision = await confirm_output_cost_correction(
                session, organization_id, month,
                ProductionOutputCostConfirmInput(
                    **data.model_dump(),
                    request_key=uuid5(request_key, f"output:{output['output_entry_id']}"),
                    basis_digest=actual["basis_digest"],
                ), actor, event_bus, procurement=procurement)
            if revision.entry_id is None:
                raise service.AccountingError("Late pool output correction has no ledger entry")
            await session.execute(text("""
                INSERT INTO accounting.late_pool_output_cost_link
                  (package_id, output_entry_id, output_revision_id, amount, evidence, origins)
                VALUES (:package,:output,:revision,:amount,CAST(:evidence AS jsonb),CAST(:origins AS jsonb))
            """), {
                "package": package_id, "output": output["output_entry_id"],
                "revision": revision.id, "amount": Decimal(output["amount_byn"]),
                "evidence": actual_raw,
                "origins": json.dumps(output["origins"], sort_keys=True),
            })
        await session.flush()
        await session.execute(text("SELECT procurement.check_additional_expense(:expense)"),
                              {"expense": expense_id})
        await session.execute(text("SELECT accounting.verify_late_pool_package(:package)"),
                              {"package": package_id})
        return entry


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
