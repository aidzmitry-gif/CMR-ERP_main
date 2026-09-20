"""Internal prospective valuation over caller-authenticated inventory history.

No posting authority: callers must load complete book history, authenticate source
receipts and resolve destination documents before using the monetary differences.
"""
from decimal import Decimal, localcontext
from fractions import Fraction

from modules.accounting.inventory_allocation_loader import AuthenticatedInventoryDisposition
from modules.accounting.inventory_cost import (
    _chronological_events,
    _distribute_pool_value,
    _valuation_layers,
    project_source_allocation,
)
from modules.accounting.service import AccountingError
from modules.accounting.zero_value_disposals import (
    AllocatedZeroValueDisposalCommand,
    AuthenticatedZeroValueDisposal,
)


async def load_expense_pools(session, organization_id, expense_id, version, on, policy_id,
                             procurement, *, before_entry_id=None):
    """Internal complete history with primary-source and destination provenance.

    The result contains DB rows and authenticated replay objects, not a public
    payload. Acquisition ordinals are converted once to actual database Line IDs.
    A future receipt verifier may bind the original registration cutoff explicitly.
    """
    from sqlalchemy import select

    from modules.accounting import service
    from modules.accounting.closing_commands import actual_posting, checksum
    from modules.accounting.inventory_allocation_loader import (
        load_authenticated_inventory_dispositions,
    )
    from modules.accounting.late_cost_receipts import verified_value_lines
    from modules.accounting.late_cost_sources import expense_basis
    from modules.accounting.models import (
        Entry,
        InventoryIssueReceipt,
        InventorySaleReceipt,
        Line,
        Policy,
    )
    from modules.accounting.production_material_cost import verify_material_issue_receipt
    from modules.accounting.purchases import PurchaseDocument
    from modules.accounting.zero_value_disposals import available_authenticated_zero_value_disposals

    source = await expense_basis(session, organization_id, expense_id, version, procurement)
    policy = await session.scalar(select(Policy).where(Policy.organization_id == organization_id,
        Policy.effective_from <= on).order_by(Policy.effective_from.desc()).limit(1))
    if policy is None or policy.id != policy_id:
        raise AccountingError("Late-cost pool requires the applicable reviewed policy")
    query = select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == organization_id,
        Line.account_code.in_({link["account"] for link in source["receipt_sources"]}))
    if before_entry_id is not None:
        anchor = await session.get(Entry, before_entry_id)
        if (anchor is None or anchor.organization_id != organization_id or anchor.posting_date != on
                or anchor.operation != "inventory_late_cost" or anchor.source_version != version
                or anchor.source != f"procurement:additional-expense:{expense_id}"):
            raise AccountingError("Late-cost cutoff must identify this exact expense posting")
        query = query.where(Entry.id < before_entry_id)
    rows = list((await session.execute(query.order_by(Entry.posting_date, Entry.id, Line.id))).all())
    evidence, entry_lines = {}, {}
    for entry, _ in rows:
        if entry.id in evidence:
            continue
        posting = await actual_posting(session, entry)
        if entry.operation == "inventory_purchase":
            prefix = "procurement:receipt:"
            if not entry.source.startswith(prefix) or not entry.source[len(prefix):].isdigit():
                raise AccountingError("Pool purchase needs its primary procurement receipt")
            basis = await procurement.posted_receipt_basis(
                session, organization_id, int(entry.source[len(prefix):]), entry.source_version)
            expected = PurchaseDocument.model_validate(basis["document"]).posting()
            if (basis["entry_id"] != entry.id or basis["actor"] != entry.actor or basis["digest"] != entry.digest
                    or service.digest(expected) != entry.digest or posting.model_dump() != expected.model_dump()):
                raise AccountingError("Pool purchase differs from its authenticated primary receipt")
        # Database numeric scale can differ from the original command's scale.
        # Compare purchases semantically above; fingerprint actual rows as well
        # as stored digests instead of rehashing normalized rows as a command.
        evidence[entry.id] = {"digest": entry.digest, "posting": posting.model_dump(mode="json")}
        entry_lines[entry.id] = list((await session.scalars(select(Line).where(
            Line.entry_id == entry.id).order_by(Line.id))).all())
    origins = {}
    for link in source["receipt_sources"]:
        lines = entry_lines.get(link["entry_id"], [])
        ordinal = link["acquisition_line"]
        if not 1 <= ordinal <= len(lines):
            raise AccountingError("Expense acquisition is missing from the complete history")
        line = lines[ordinal - 1]
        if line.side != "debit" or line.account_code != link["account"] or line.dimensions != link["inventory_dimensions"]:
            raise AccountingError("Expense acquisition ordinal differs from its actual inventory line")
        origins[(link["receipt_id"], link["version"], link["line_number"])] = (link["entry_id"], line.id)
    zeros = await available_authenticated_zero_value_disposals(session, organization_id,
        before_registration_token=before_entry_id, procurement=procurement)
    pools = []
    for account in sorted({link["account"] for link in source["receipt_sources"]}):
        account_rows = [(entry, line) for entry, line in rows if line.account_code == account]
        values = await verified_value_lines(session, organization_id, account_rows, procurement)
        dispositions = await load_authenticated_inventory_dispositions(session, organization_id,
            before_entry_id=before_entry_id, procurement=procurement, inventory_account=account)
        destinations = {}
        for event in dispositions:
            if event.source.startswith("production:material:"):
                await verify_material_issue_receipt(session, organization_id, event.entry_id, procurement=procurement)
            receipt = await session.get(InventoryIssueReceipt, event.entry_id)
            if receipt is None:
                receipt = await session.get(InventorySaleReceipt, event.entry_id)
            destinations[("entry", event.entry_id)] = {
                "account": receipt.command["expense_account"], "dimensions": receipt.command["expense_dimensions"],
                "source": event.source, "source_version": event.source_version}
        for event in zeros:
            destinations[("zero_receipt", event.receipt_id)] = {
                "account": event.command.destination_account, "dimensions": event.command.destination_dimensions,
                "source": event.command.source, "source_version": event.command.source_version}
        scopes = {(link["warehouse"], link["item"]["sku"]) for link in source["receipt_sources"] if link["account"] == account}
        for warehouse, sku in sorted(scopes):
            pools.append({"account": account, "warehouse": warehouse, "sku": sku,
                "rows": account_rows, "dispositions": dispositions, "zeros": zeros,
                "verified_values": values, "destinations": destinations})
    fingerprint = {"source": source, "origins": [{"primary": key, "ledger": value} for key, value in sorted(origins.items())],
        "entries": sorted(evidence.items()), "zero_receipts": [{"id": row.receipt_id,
            "token": row.registration_token, "digest": row.digest} for row in zeros],
        "policy_id": policy_id, "on": on.isoformat(), "before_entry_id": before_entry_id}
    return {"source": source, "origins": origins, "pools": pools, "method": policy.inventory_method,
            "policy_id": policy.id, "on": on.isoformat(), "rule": policy.late_cost_allocation,
            "normative_verified": policy.normative_verified,
            "basis_digest": checksum(fingerprint), "before_registration_token": before_entry_id}


async def preview_expense(session, organization_id, expense_id, data, procurement, *, before_entry_id=None):
    """Calculate a complete document from server-selected sources; never post it."""
    from modules.accounting.late_cost_preview import validate_currency

    loaded = await load_expense_pools(session, organization_id, expense_id, data.expected_version,
        data.posting_date, data.policy_id, procurement, before_entry_id=before_entry_id)
    await validate_currency(session, loaded["source"]["document"]["currency"], data)
    return calculate_expense(loaded, data)


def calculate_expense(loaded, data):
    """Internal calculation after load_expense_pools and currency validation."""
    from modules.accounting.closing_commands import checksum
    from modules.accounting.late_cost_allocation import AllocationInput, preview_allocation
    from modules.accounting.late_cost_preview import source_conversion
    from modules.accounting.schemas import LateCostPolicyInput

    source = loaded["source"]
    if (loaded["policy_id"] != data.policy_id or loaded["on"] != data.posting_date.isoformat()
            or source["version"] != data.expected_version):
        raise AccountingError("Expense pool request differs from its authenticated history")
    if loaded["method"] not in {"fifo", "weighted_average"} or loaded["rule"] is None:
        raise AccountingError("Expense pool needs an explicit supported valuation and allocation policy")
    rule = LateCostPolicyInput.model_validate(loaded["rule"])
    source_amount, conversion = source_conversion(source["document"], data)
    rows = {(entry.id, line.id): line for pool in loaded["pools"] for entry, line in pool["rows"]}
    lots = []
    for primary, origin in sorted(loaded["origins"].items()):
        line = rows[origin]
        lots.append({"receipt_id": primary[0], "version": primary[1], "line_number": primary[2],
            "received_quantity": line.quantity, "received_value_byn": line.amount,
            "remaining_quantity": line.quantity, "disposed_quantity": "0", "production_quantity": "0"})
    # First apportion the document between original receipts by approved policy.
    # Physical disposition proportions must not drive weighted-average money.
    apportioned = preview_allocation(AllocationInput(**rule.model_dump(),
        amount_byn=data.capitalizable_amount_byn, lots=lots))
    additions, origins = {}, []
    for share in apportioned["shares"]:
        if share["destination"] != "remaining":
            continue
        primary = (share["receipt_id"], share["version"], share["line_number"])
        origin = loaded["origins"][primary]
        amount = Decimal(share["amount_byn"])
        origins.append({"receipt_id": primary[0], "version": primary[1], "line_number": primary[2],
            "source_entry_id": origin[0], "source_line_id": origin[1], "amount_byn": share["amount_byn"]})
        if amount:
            additions[origin] = amount
    pools, destinations, used = [], [], set()
    for pool in loaded["pools"]:
        selected = {origin: amount for origin, amount in additions.items()
            if rows[origin].account_code == pool["account"]
            and rows[origin].dimensions["warehouse"] == pool["warehouse"]
            and rows[origin].dimensions["sku"] == pool["sku"]}
        if not selected:
            continue
        if used & selected.keys():
            raise AccountingError("Expense source was assigned to more than one inventory pool")
        used.update(selected)
        projected = project_pool(pool["rows"], organization_id=source["organization_id"],
            account=pool["account"], warehouse=pool["warehouse"], sku=pool["sku"], method=loaded["method"],
            on=data.posting_date, additions=selected, dispositions=pool["dispositions"], zeros=pool["zeros"],
            verified_values=pool["verified_values"], before_token=loaded["before_registration_token"])
        for movement in projected["movements"]:
            identity = (movement["kind"], movement.get("entry_id", movement.get("receipt_id")))
            destination = pool["destinations"].get(identity)
            if destination is None:
                raise AccountingError("Expense disposition lacks an authenticated destination")
            movement["destination"] = destination
            destinations.append({"kind": movement["kind"], "identity": identity[1],
                "account": destination["account"], "dimensions": destination["dimensions"],
                "delta_byn": movement["delta_byn"]})
        for remaining in projected["remaining"]:
            destinations.append({"kind": "inventory", "source_entry_id": remaining["source_entry_id"],
                "source_line_id": remaining["source_line_id"], "account": pool["account"],
                "dimensions": remaining["dimensions"], "delta_byn": remaining["delta_byn"]})
        pools.append({"account": pool["account"], "warehouse": pool["warehouse"], "sku": pool["sku"], **projected})
    if used != set(additions) or sum(Fraction(row["delta_byn"]) for row in destinations) != Fraction(data.capitalizable_amount_byn):
        raise AccountingError("Expense destinations must cover the complete capitalizable amount")
    result = {"calculation_version": 3, "organization_id": source["organization_id"],
        "expense_id": source["expense_id"], "source_version": source["version"],
        "document": source["document"], "request": data.model_dump(mode="json"),
        "inventory_method": loaded["method"], "rule": rule.model_dump(),
        "normative_verified": loaded["normative_verified"], "history_digest": loaded["basis_digest"],
        "source_amount_byn": format(source_amount, ".2f"),
        "conversion": conversion.model_dump(mode="json") if conversion else None,
        "source_apportionment": origins, "pools": pools, "destinations": destinations,
        "posted": False, "confirmation_available": False}
    return {**result, "basis_digest": checksum(result)}


def project_pool(rows, *, organization_id, account, warehouse, sku, method, on,
                 additions, dispositions=(), zeros=(), verified_values=frozenset(), before_token=None):
    """Replay one complete pool twice; additions identify real acquisition lines.

    Monetary and entryless dispositions retain distinct identities. Legacy
    unallocated credits are rejected rather than guessing their source selection.
    Saved receipt amounts are checked against baseline, never against the overlay.
    """
    if method not in {"fifo", "weighted_average"} or account.split(".")[0] not in {"10", "41"}:
        raise AccountingError("Late-cost pool requires FIFO or weighted owned inventory")
    if not warehouse or not sku or not additions:
        raise AccountingError("Late-cost pool and source additions must be explicit")
    if any(line.account_code != account for _, line in rows):
        raise AccountingError("Late-cost history must contain exactly the selected book account")
    for identity, value in additions.items():
        if (not isinstance(identity, tuple) or len(identity) != 2
                or any(type(part) is not int or part <= 0 for part in identity)
                or not isinstance(value, Decimal) or not value.is_finite() or value <= 0
                or (Fraction(value) * 100).denominator != 1):
            raise AccountingError("Late-cost additions require exact origins and positive whole cents")
    target = {"warehouse": warehouse, "sku": sku, "lot": ""}
    with localcontext() as context:
        context.prec = 64
        expected, _ = _valuation_layers(rows, target, on, method=method,
            verified_value_lines=verified_values, zero_value_disposals=zeros,
            authenticated_dispositions=dispositions, organization_id=organization_id,
            inventory_account=account, before_registration_token=before_token)
        baseline, prospective, movements, applied = [], [], [], set()
        events = _chronological_events(rows, organization_id, on, zeros, before_token, dispositions, account)
        for _, _, _, entry, line, event in events:
            if isinstance(event, AuthenticatedInventoryDisposition):
                allocation, scope = event.allocation, event.selection_lot
                identity = {"kind": "entry", "entry_id": event.entry_id,
                            "registration_token": event.registration_token}
            elif isinstance(event, AuthenticatedZeroValueDisposal):
                if not isinstance(event.command, AllocatedZeroValueDisposalCommand):
                    raise AccountingError("Late-cost replay requires explicit zero source allocation")
                allocation, scope = event.command.allocation, event.command.document["lot"]
                identity = {"kind": "zero_receipt", "receipt_id": event.receipt_id,
                            "registration_token": event.registration_token}
            elif event is not None:
                receipt, layer = event
                if (layer.inventory_account == account and layer.inventory_dimensions["warehouse"] == warehouse
                        and layer.inventory_dimensions["sku"] == sku):
                    raise AccountingError("Late-cost replay requires explicit zero source allocation")
                continue
            else:
                dimensions = line.dimensions
                if dimensions["warehouse"] != warehouse or dimensions["sku"] != sku:
                    continue
                source = (entry.id, line.id)
                if source in verified_values:
                    for pool in (baseline, prospective):
                        matches = [layer for layer in pool if layer["dimensions"] == dimensions and layer["quantity"] > 0]
                        if len(matches) != 1:
                            raise AccountingError("Historical late cost requires an unambiguous surviving layer")
                        matches[0]["amount"] += line.amount if line.side == "debit" else -line.amount
                        if matches[0]["amount"] < 0:
                            raise AccountingError("Historical value correction exhausts prospective cost")
                        if method == "weighted_average":
                            _distribute_pool_value(pool, sum(layer["amount"] for layer in pool))
                    continue
                if line.side != "debit":
                    raise AccountingError("Late-cost pool contains a disposition without authenticated source allocation")
                layer = {"entry_id": entry.id, "line_id": line.id, "lot": dimensions["lot"],
                         "dimensions": dict(dimensions), "quantity": line.quantity, "amount": line.amount,
                         "posting_date": entry.posting_date.isoformat()}
                baseline.append(layer)
                extra = additions.get(source, Decimal(0))
                if extra:
                    if entry.operation != "inventory_purchase":
                        raise AccountingError("Late-cost addition must identify an inventory purchase")
                    applied.add(source)
                prospective.append({**layer, "dimensions": dict(dimensions), "amount": line.amount + extra})
                continue
            first = allocation.layers[0]
            if (first.inventory_account != account or first.inventory_dimensions["warehouse"] != warehouse
                    or first.inventory_dimensions["sku"] != sku):
                continue
            scope = scope if method == "fifo" else ""
            projected = project_source_allocation(
                [layer for layer in baseline if not scope or layer["lot"] == scope],
                [layer for layer in prospective if not scope or layer["lot"] == scope], allocation)
            for pool, key in ((baseline, "baseline_layers"), (prospective, "prospective_layers")):
                updated = {(layer["entry_id"], layer["line_id"]): layer for layer in projected[key]}
                pool[:] = [updated.get((layer["entry_id"], layer["line_id"]), layer) for layer in pool]
            movements.append({**identity, "baseline": allocation.model_dump(mode="json"),
                "prospective": projected["allocation"].model_dump(mode="json"),
                "delta_byn": format(projected["delta_byn"], ".2f")})
        if applied != set(additions):
            raise AccountingError("Late-cost acquisition sources are missing from the selected history")
        if method == "weighted_average":
            for pool in (baseline, prospective):
                _distribute_pool_value(pool, sum(layer["amount"] for layer in pool))
        if [layer for layer in baseline if layer["quantity"] > 0] != expected:
            raise AccountingError("Late-cost baseline differs from the existing inventory valuation engine")
        remaining = [{"source_entry_id": old["entry_id"], "source_line_id": old["line_id"],
            "inventory_account": account, "dimensions": old["dimensions"], "quantity": format(old["quantity"], ".6f"),
            "baseline_byn": format(old["amount"], ".2f"), "prospective_byn": format(new["amount"], ".2f"),
            "delta_byn": format(new["amount"] - old["amount"], ".2f")}
            for old, new in zip(baseline, prospective, strict=True) if old["quantity"] > 0]
        if (sum(Fraction(value) for value in additions.values())
                != sum(Fraction(row["delta_byn"]) for row in movements + remaining)):
            raise AccountingError("Late-cost pool does not conserve the complete additional value")
        return {"movements": movements, "remaining": remaining, "posted": False,
                "before_registration_token": before_token}
