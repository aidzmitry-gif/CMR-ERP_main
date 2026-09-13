"""Authenticate late-expense acquisition sources through the owner gateway."""
from sqlalchemy import select

from core.services.procurement import ProcurementSourceGateway
from modules.accounting import service
from modules.accounting.closing_commands import actual_posting, checksum
from modules.accounting.late_cost_trace import trace_specific_lot
from modules.accounting.models import Entry, InventorySaleReceipt, Line, ShipmentAccountingReceipt
from modules.accounting.purchases import PurchaseDocument


async def verified_shipment_entries(session, organization_id, entry_ids: set[int]):
    """Return requested shipment pages only after whole-package verification.

    Missing package membership is an error. Inventory issues without a durable
    source receipt are deliberately not inferred to be shipment disposals.
    """
    from modules.accounting.shipment_commands import verify_saved

    await service.lock_organization(session, organization_id)
    receipts = (await session.scalars(select(ShipmentAccountingReceipt).where(
        ShipmentAccountingReceipt.organization_id == organization_id))).all()
    result = {}
    for receipt in receipts:
        pages = receipt.snapshot.get("pages", [])
        selected = {page.get("entry_id") for page in pages} & entry_ids
        if not selected:
            continue
        await verify_saved(session, receipt)
        for entry_id in selected:
            entry = await session.get(Entry, entry_id)
            if entry_id in result or entry.operation != "inventory_sale" or entry.actor != receipt.actor:
                raise service.AccountingError("Shipment disposition package identity or author is inconsistent")
            result[entry_id] = await actual_posting(session, entry)
    if set(result) != entry_ids:
        raise service.AccountingError("Inventory disposition has no verified shipment package")
    return result


async def expense_basis(session, organization_id, expense_id, expected_version, procurement: ProcurementSourceGateway):
    """Caller authorizes book access; this read holds the ledger's organization lock.

    Verifies original acquisitions only. Disposal tracing/policy/allocation and
    posting remain separate; successful output is not a final cost certificate.
    """
    await service.lock_organization(session, organization_id)
    source = await procurement.additional_expense_source(session, organization_id, expense_id, expected_version)
    verified = {}
    links = []
    for link in source["receipt_sources"]:
        key = (link["receipt_id"], link["version"])
        if key not in verified:
            basis = await procurement.posted_receipt_basis(session, organization_id, *key)
            document = PurchaseDocument.model_validate(basis["document"])
            expected = document.posting()
            entry = await session.get(Entry, basis["entry_id"])
            if (entry is None or entry.organization_id != organization_id or entry.actor != basis["actor"]
                or entry.digest != basis["digest"] or entry.digest != service.digest(expected)
                or (await actual_posting(session, entry)).model_dump() != expected.model_dump()):
                raise service.AccountingError("Receipt source does not match its actual accounting package")
            verified[key] = (basis, document)
        basis, document = verified[key]
        index = link["line_number"] - 1
        if (not 0 <= index < len(document.items) or basis["entry_id"] != link["entry_id"]
            or basis["digest"] != link["posting_digest"]):
            raise service.AccountingError("Expense receipt line does not match its accounting source")
        # Purchase rule emits inventory then optional VAT per primary line.
        ledger_line = 1 + sum(1 + int(item.vat_amount > 0) for item in document.items[:index])
        links.append({**link, "acquisition_line": ledger_line, "account": document.items[index].account,
                      "inventory_dimensions": document.posting().lines[ledger_line - 1].dimensions})
    return {**source, "receipt_sources": links, "acquisitions_verified": True,
            "disposals_verified": False, "posted": False, "final_cost_certified": False}


async def expense_history(session, organization_id, expense_id, expected_version, on, procurement: ProcurementSourceGateway,
                          *, before_entry_id=None):
    """Read all affected book-account movements, including dates after the cutoff.

    No public caller may provide its own filtered history. Caller authorizes book
    membership; the source verifier holds the same lock as ledger writers.
    """
    source = await expense_basis(session, organization_id, expense_id, expected_version, procurement)
    links = source["receipt_sources"]
    query = select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == organization_id, Line.account_code.in_({link["account"] for link in links}),
    )
    if before_entry_id is not None:
        anchor = await session.get(Entry, before_entry_id)
        if (anchor is None or anchor.organization_id != organization_id or anchor.operation != "inventory_late_cost"
            or anchor.posting_date != on or anchor.source != f"procurement:additional-expense:{expense_id}"
            or anchor.source_version != expected_version or any(link["entry_id"] >= anchor.id for link in links)):
            raise service.AccountingError("Historical cost boundary must identify this exact late-cost entry")
        query = query.where(Entry.id < before_entry_id)
    rows = (await session.execute(query.order_by(Entry.posting_date, Entry.id, Line.id))).all()
    for _, line in rows:
        if any(not line.dimensions.get(key) for key in ("warehouse", "sku", "lot")):
            raise service.AccountingError("Inventory account has incomplete lot analytics; reconcile before late costs")
    traces = []
    evidence = {}
    for link in links:
        target = {"warehouse": link["warehouse"], "sku": link["item"]["sku"], "lot": link["item"]["lot"]}
        affected = [(entry, line) for entry, line in rows if line.account_code == link["account"]
                    and all(line.dimensions[key] == value for key, value in target.items())]
        from modules.accounting.late_cost_receipts import verify_receipt as verify_late_cost

        cost_ids = {entry.id for entry, line in affected
                    if entry.operation == "inventory_late_cost" and line.quantity is None and line.side == "debit"}
        verified_costs = {entry_id: await verify_late_cost(session, organization_id, entry_id, procurement)
                          for entry_id in sorted(cost_ids)}
        for entry, line in affected:
            if line.side == "debit" and entry.id != link["entry_id"] and entry.id not in verified_costs:
                raise service.AccountingError("Multiple acquisitions require explicit cost layers")
        disposals = {entry.id for entry, line in affected if line.side == "credit"}
        from modules.accounting.inventory_issues import verify_receipt
        issue_ids = {entry.id for entry, line in affected if line.side == "credit" and entry.operation == "inventory_issue"}
        sale_ids = set((await session.scalars(select(InventorySaleReceipt.entry_id).where(
            InventorySaleReceipt.organization_id == organization_id,
            InventorySaleReceipt.entry_id.in_(disposals - issue_ids)))).all())
        verified = await verified_shipment_entries(session, organization_id, disposals - issue_ids - sale_ids)
        from modules.accounting.sales import verify_receipt as verify_sale

        for sale_id in sale_ids:
            verified[sale_id] = await verify_sale(session, organization_id, sale_id, procurement=procurement)
        for issue_id in issue_ids:
            verified[issue_id] = await verify_receipt(session, organization_id, issue_id, procurement=procurement)
        acquisition = await session.get(Entry, link["entry_id"])
        verified[acquisition.id] = await actual_posting(session, acquisition)
        verified.update(verified_costs)
        trace = trace_specific_lot(list(verified.items()), acquisition.id, link["acquisition_line"], on,
            verified_cost_entries=frozenset(verified_costs))
        traces.append({"receipt_id": link["receipt_id"], "version": link["version"], "line_number": link["line_number"], **trace})
        for entry, _ in affected:
            evidence[entry.id] = entry.digest
    result = {**source, "on": on.isoformat(), "lots": traces, "disposals_verified": True,
              "movement_evidence": [{"entry_id": entry_id, "digest": digest} for entry_id, digest in sorted(evidence.items())]}
    return {**result, "basis_digest": checksum(result)}
