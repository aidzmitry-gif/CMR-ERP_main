"""Read-only inventory cost preview for policy-selected valuation layers."""
import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction

from sqlalchemy import select

from modules.accounting.models import Entry, Line, Policy
from modules.accounting.service import AccountingError, lock_organization
from modules.accounting.zero_value_disposals import (
    AllocatedZeroValueDisposalCommand,
    AuthenticatedZeroValueDisposal,
    receipt_digest,
)


def _chronological_events(rows, org_id, cutoff, zero_value_disposals, before_registration_token=None,
                          authenticated_dispositions=(), inventory_account=None):
    """Merge ledger rows with authenticated, entryless physical credits only."""
    from modules.accounting.inventory_allocation_loader import AuthenticatedInventoryDisposition

    rows = [(entry, line) for entry, line in rows
            if before_registration_token is None or entry.id < before_registration_token]
    if not zero_value_disposals and not authenticated_dispositions:
        return [(entry.posting_date, entry.id, line.id, entry, line, None) for entry, line in rows]
    sources = {(entry.id, line.id): (entry, line) for entry, line in rows}
    receipt_ids, tokens, disposition_entries, replaced, admitted_dispositions = set(), set(), set(), set(), []
    for receipt in zero_value_disposals:
        if not isinstance(receipt, AuthenticatedZeroValueDisposal) or receipt.organization_id != org_id:
            raise AccountingError("Zero-value disposal provenance is not authenticated for this organization")
        if (receipt.receipt_id in receipt_ids or receipt.registration_token in tokens
            or receipt.digest != receipt_digest(receipt.organization_id, receipt.actor, receipt.command)):
            raise AccountingError("Zero-value disposal receipt identity or digest changed during replay")
        receipt_ids.add(receipt.receipt_id)
        tokens.add(receipt.registration_token)
    for disposition in authenticated_dispositions:
        if not isinstance(disposition, AuthenticatedInventoryDisposition):
            raise AccountingError("Inventory allocation replay event has an unsupported type")
        disposition.verify_snapshot()
        if disposition.organization_id != org_id:
            raise AccountingError("Inventory allocation provenance is not authenticated for this organization")
        accounts = {layer.inventory_account for layer in disposition.allocation.layers}
        if len(accounts) != 1:
            raise AccountingError("Inventory allocation spans more than one account")
        if inventory_account is not None and accounts != {inventory_account}:
            continue
        if before_registration_token is not None and disposition.registration_token >= before_registration_token:
            continue
        if disposition.entry_id in disposition_entries or disposition.registration_token in tokens:
            raise AccountingError("Inventory allocation replay registration is duplicated")
        disposition_entries.add(disposition.entry_id)
        tokens.add(disposition.registration_token)
        positive = [layer for layer in disposition.allocation.layers if layer.amount_byn > 0]
        if len(positive) != len(disposition.replaced_credit_line_ids):
            raise AccountingError("Inventory allocation replacement count changed")
        for line_id, layer in zip(disposition.replaced_credit_line_ids, positive, strict=True):
            replacement = sources.get((disposition.entry_id, line_id))
            if replacement is None:
                raise AccountingError("Inventory allocation replacement line is missing from replay history")
            entry, line = replacement
            if (entry.id != disposition.entry_id or entry.posting_date != disposition.posting_date
                    or entry.source != disposition.source or entry.source_version != disposition.source_version
                    or line.side != "credit" or line.account_code != layer.inventory_account
                    or line.quantity != layer.quantity or line.amount != layer.amount_byn
                    or line.dimensions != layer.inventory_dimensions or line.currency != "BYN"
                    or line.category != "asset" or line.cash):
                raise AccountingError("Inventory allocation replacement line changed")
        if any(line_id in replaced for line_id in disposition.replaced_credit_line_ids):
            raise AccountingError("Inventory allocation replaces a credit more than once")
        replaced.update(disposition.replaced_credit_line_ids)
        admitted_dispositions.append(disposition)
    events = [(entry.posting_date, entry.id, line.id, entry, line, None) for entry, line in rows
              if line.id not in replaced]
    for receipt in zero_value_disposals:
        if before_registration_token is not None and receipt.registration_token >= before_registration_token:
            continue
        command = receipt.command
        is_v4 = isinstance(command, AllocatedZeroValueDisposalCommand)
        if is_v4:
            accounts = {layer.inventory_account for layer in command.allocation.layers}
            if len(accounts) != 1:
                raise AccountingError("Allocation zero-value receipt spans more than one account")
            if inventory_account is not None and accounts != {inventory_account}:
                continue
        for layer in command.inventory_layers:
            source = sources.get((layer.source_entry_id, layer.source_line_id))
            if (source is None or source[0].posting_date > receipt.posting_date
                or source[0].id >= receipt.registration_token or source[1].side != "debit"
                or source[1].quantity is None or source[1].quantity <= 0
                or source[1].account_code != layer.inventory_account
                or (source[1].dimensions or {}) != layer.inventory_dimensions):
                raise AccountingError("Zero-value disposal source layer does not match ledger history")
            if not is_v4:
                events.append((receipt.posting_date, receipt.registration_token, receipt.receipt_id, None, None, (receipt, layer)))
        if is_v4:
            events.append((receipt.posting_date, receipt.registration_token, receipt.receipt_id, None, None, receipt))
    for disposition in admitted_dispositions:
        events.append((disposition.posting_date, disposition.registration_token, 0, None, None, disposition))
    return sorted(events, key=lambda item: item[:3])


async def _inventory_rows(session, org_id, data):
    await lock_organization(session, org_id)
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == org_id, Policy.effective_from <= data.posting_date,
    ).order_by(Policy.effective_from.desc()).limit(1))
    if policy is None or policy.id != data.policy_id:
        raise AccountingError("Select the applicable accounting policy")
    if policy.inventory_method not in {"specific", "fifo", "weighted_average"}:
        raise AccountingError("The selected inventory valuation method is not supported")
    finished_goods = False
    if data.account.split(".")[0] not in {"10", "41"}:
        from modules.accounting.production_output_inventory import is_finished_goods_account

        if not is_finished_goods_account(policy, data.account):
            raise AccountingError("Select an owned inventory account 10/41 or the policy finished-goods account")
        finished_goods = True
    rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == org_id, Line.account_code == data.account,
    ).order_by(Entry.posting_date, Entry.id, Line.id))).all()
    verified_output_lines = frozenset()
    if finished_goods:
        from modules.accounting.production_output_inventory import verified_output_lines

        verified_output_lines = await verified_output_lines(
            session, org_id, policy, data.account, data.posting_date,
            {"warehouse": data.warehouse, "sku": data.sku, "lot": getattr(data, "lot", "")},
        )
    return policy, rows, verified_output_lines, finished_goods


def _distribute_pool_value(layers, amount):
    """Keep the actual ledger value on the remaining physical quantities."""
    active = [layer for layer in layers if layer["quantity"] > 0]
    cents = Fraction(amount) * 100
    if cents < 0 or cents.denominator != 1:
        raise AccountingError("Weighted-average history has an invalid remaining book value")
    if not active:
        if cents:
            raise AccountingError("Empty inventory pool retains book value")
        for layer in layers:
            layer["amount"] = Decimal(0)
        return
    quantity = sum((Fraction(layer["quantity"]) for layer in active), Fraction())
    quotas = [cents * Fraction(layer["quantity"]) / quantity for layer in active]
    values = [quota.numerator // quota.denominator for quota in quotas]
    residual = cents.numerator - sum(values)
    ranked = sorted(range(len(active)), key=lambda index: (-(quotas[index] - values[index]), index))
    for index in ranked[:residual]:
        values[index] += 1
    for layer, value in zip(active, values, strict=True):
        layer["amount"] = Decimal(value) / 100
    for layer in layers:
        if layer["quantity"] == 0:
            layer["amount"] = Decimal(0)


def _valuation_layers(rows, target, posting_date, *, verified_value_lines=frozenset(),
                      verified_output_lines=frozenset(), finished_goods=False, method="fifo",
                      zero_value_disposals=(), authenticated_dispositions=(), organization_id=None,
                      before_registration_token=None, inventory_account=None):
    """Build chronological available inventory layers for FIFO/average methods.

    The physical identity remains explicit (warehouse/SKU/lot).  A debit adds
    a layer and a credit consumes earlier layers.  Late value-only adjustments
    are admitted only through an existing verified late-cost receipt.  The
    adjustment must match exactly one still-open physical layer; ambiguous
    same-lot layers are rejected instead of silently changing the wrong layer.
    """
    from modules.accounting.inventory_allocation_loader import AuthenticatedInventoryDisposition

    layers = []
    requested_lot = target.get("lot")
    if authenticated_dispositions or any(
        isinstance(receipt, AuthenticatedZeroValueDisposal)
        and isinstance(receipt.command, AllocatedZeroValueDisposalCommand)
        for receipt in zero_value_disposals
    ):
        # Replay complete source packets before projecting a requested lot.
        target = {**target, "lot": ""}
    evidence = []
    matched = False
    checked_zero_receipts = set()
    pool_value_origins = getattr(verified_value_lines, "pool_origins", {})
    if organization_id is None and zero_value_disposals:
        raise AccountingError("Zero-value disposal replay needs an organization identity")
    for _, _, _, entry, line, zero_event in _chronological_events(
        rows, organization_id, posting_date, zero_value_disposals, before_registration_token,
        authenticated_dispositions, inventory_account
    ):
        if isinstance(zero_event, AuthenticatedInventoryDisposition):
            allocation = zero_event.allocation
            first = allocation.layers[0].inventory_dimensions
            if first.get("warehouse") != target["warehouse"] or first.get("sku") != target["sku"]:
                continue
            if zero_event.posting_date > posting_date:
                raise AccountingError("Selected SKU has later movements; chronological costing is required")
            if method == "specific":
                raise AccountingError("Explicit source allocation replay requires FIFO or weighted-average policy")
            if method != allocation.valuation_method:
                raise AccountingError("Inventory allocation policy differs from replay policy")
            scope = zero_event.selection_lot if method == "fifo" else ""
            selected_layers = [layer for layer in layers if not scope or layer["lot"] == scope]
            updated = replay_source_allocation(selected_layers, allocation)
            by_origin = {(layer["entry_id"], layer["line_id"]): layer for layer in updated}
            layers = [by_origin.get((layer["entry_id"], layer["line_id"]), layer) for layer in layers]
            evidence.append({"entry_id": zero_event.entry_id, "line_id": None, "source": zero_event.source,
                             "source_version": zero_event.source_version, "side": "credit",
                             "quantity": format(allocation.quantity, ".6f"), "amount_byn": format(allocation.amount_byn, ".2f"),
                             "explicit_allocation": True})
            matched = True
            continue
        if (isinstance(zero_event, AuthenticatedZeroValueDisposal)
                and isinstance(zero_event.command, AllocatedZeroValueDisposalCommand)):
            command = zero_event.command
            allocation = command.allocation
            first = allocation.layers[0].inventory_dimensions
            if ((inventory_account is not None and allocation.layers[0].inventory_account != inventory_account)
                    or first.get("warehouse") != target["warehouse"] or first.get("sku") != target["sku"]):
                continue
            if zero_event.posting_date > posting_date:
                raise AccountingError("Selected SKU has later movements; chronological costing is required")
            if method != command.valuation_method:
                raise AccountingError("Allocation zero-value policy differs from replay policy")
            scope = command.document["lot"] if method == "fifo" else ""
            selected_layers = [layer for layer in layers if not scope or layer["lot"] == scope]
            updated = replay_source_allocation(selected_layers, allocation)
            by_origin = {(layer["entry_id"], layer["line_id"]): layer for layer in updated}
            layers = [by_origin.get((layer["entry_id"], layer["line_id"]), layer) for layer in layers]
            evidence.append({"receipt_id": zero_event.receipt_id, "registration_token": zero_event.registration_token,
                             "entry_id": None, "line_id": None, "source": command.source,
                             "source_version": command.source_version, "side": "credit",
                             "quantity": format(allocation.quantity, ".6f"), "amount_byn": "0.00",
                             "zero_value_disposal": True, "explicit_allocation": True})
            matched = True
            continue
        if zero_event is not None:
            receipt, source_layer = zero_event
            dimensions = source_layer.inventory_dimensions
            if dimensions.get("warehouse") != target["warehouse"] or dimensions.get("sku") != target["sku"]:
                continue
            if method != "weighted_average" and target.get("lot") and dimensions.get("lot") != target["lot"]:
                continue
            if receipt.posting_date > posting_date:
                raise AccountingError("Selected SKU has later movements; chronological costing is required")
            matches = [layer for layer in layers if layer["entry_id"] == source_layer.source_entry_id
                       and layer["line_id"] == source_layer.source_line_id and layer["quantity"] >= source_layer.quantity]
            if len(matches) != 1:
                raise AccountingError("Zero-value disposal exceeds or misses its source inventory layer")
            pool_value = sum((layer["amount"] for layer in layers), Decimal(0))
            pool_quantity = sum((layer["quantity"] for layer in layers), Decimal(0))
            layer = matches[0]
            if method == "weighted_average" and receipt.receipt_id not in checked_zero_receipts:
                command_quantity = sum((item.quantity for item in receipt.command.inventory_layers
                                        if item.inventory_dimensions.get("warehouse") == target["warehouse"]
                                        and item.inventory_dimensions.get("sku") == target["sku"]), Decimal(0))
                expected_cost = (pool_value * command_quantity / pool_quantity).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP)
                if expected_cost != 0:
                    raise AccountingError("Zero-value disposal command still carries rounded pool value")
                checked_zero_receipts.add(receipt.receipt_id)
            expected_cost = (layer["amount"] if source_layer.quantity == layer["quantity"]
                             else (layer["amount"] * source_layer.quantity / layer["quantity"]).quantize(
                                 Decimal("0.01"), rounding=ROUND_HALF_UP)) if method != "weighted_average" else Decimal(0)
            if expected_cost != 0:
                raise AccountingError("Zero-value disposal source layer still carries book value")
            layer["quantity"] -= source_layer.quantity
            if method != "weighted_average":
                layer["amount"] -= expected_cost
            if method == "weighted_average":
                _distribute_pool_value(layers, pool_value)
            evidence.append({"receipt_id": receipt.receipt_id, "entry_id": None, "line_id": None,
                             "source": receipt.command.source, "source_version": receipt.command.source_version,
                             "side": "credit", "quantity": format(source_layer.quantity, ".6f"),
                             "amount_byn": "0.00", "lot": dimensions["lot"], "zero_value_disposal": True})
            matched = True
            continue
        dimensions = line.dimensions or {}
        required = ("warehouse", "sku", "lot")
        if any(not dimensions.get(key) for key in required):
            raise AccountingError("Inventory account contains movements without warehouse, SKU or lot; reconcile first")
        if line.category != "asset" or line.cash:
            raise AccountingError("Lot movement is not owned inventory")
        if line.currency != "BYN":
            raise AccountingError("Foreign-currency inventory requires a separate issue rule")
        if entry.posting_date > posting_date:
            if dimensions.get("warehouse") == target["warehouse"] and dimensions.get("sku") == target["sku"]:
                raise AccountingError("Selected SKU has later movements; chronological costing is required")
            continue
        if dimensions.get("warehouse") != target["warehouse"] or dimensions.get("sku") != target["sku"]:
            continue
        if method != "weighted_average" and target.get("lot") and dimensions.get("lot") != target["lot"]:
            continue
        if finished_goods and line.side == "debit" and (entry.id, line.id) not in verified_output_lines and (entry.id, line.id) not in verified_value_lines:
            raise AccountingError("Finished-goods layer has no verified production output receipt")
        matched = True
        value_key = (entry.id, line.id)
        value_only = value_key in verified_value_lines
        if value_only:
            origin = pool_value_origins.get(value_key)
            if origin is not None:
                if (entry.operation != "inventory_late_cost" or entry.rule_version != "late-cost-pool-v3"
                        or line.quantity is not None or line.amount <= 0
                        or line.category != "asset" or line.cash or line.currency != "BYN"
                        or not isinstance(origin, tuple) or len(origin) != 2
                        or any(type(item) is not int or item <= 0 for item in origin)):
                    raise AccountingError("Invalid V3 inventory value adjustment")
                matches = [layer for layer in layers
                           if (layer["entry_id"], layer["line_id"]) == origin and layer["quantity"] > 0]
                if len(matches) != 1 or matches[0]["dimensions"] != dimensions:
                    raise AccountingError("V3 late cost does not identify one open acquisition layer")
                signed_amount = Decimal(line.amount) if line.side == "debit" else -Decimal(line.amount)
                if matches[0]["amount"] + signed_amount < 0:
                    raise AccountingError("V3 late cost makes its acquisition layer value negative")
                matches[0]["amount"] += signed_amount
                evidence.append({"entry_id": entry.id, "line_id": line.id, "source": entry.source,
                                 "source_version": entry.source_version, "side": line.side,
                                 "quantity": None, "amount_byn": format(Decimal(line.amount), ".2f"),
                                 "lot": dimensions["lot"], "late_cost": True,
                                 "acquisition_entry_id": origin[0], "acquisition_line_id": origin[1]})
                continue
            if (entry.operation not in {"inventory_late_cost", "production_output_cost_correction"}
                or entry.operation == "inventory_late_cost" and line.side != "debit"
                or line.quantity is not None or line.amount <= 0):
                raise AccountingError("Invalid verified inventory value adjustment")
            matches = [layer for layer in layers
                       if layer["dimensions"] == dimensions and layer["quantity"] > 0]
            if len(matches) != 1:
                raise AccountingError("Late cost must identify exactly one open inventory layer")
            amount = Decimal(line.amount)
            matches[0]["amount"] += amount if line.side == "debit" else -amount
            if method == "weighted_average":
                _distribute_pool_value(layers, sum((layer["amount"] for layer in layers), Decimal(0)))
            elif matches[0]["amount"] < 0:
                raise AccountingError("Output cost revision makes the layer value negative")
            evidence.append({"entry_id": entry.id, "line_id": line.id, "source": entry.source,
                             "source_version": entry.source_version, "side": line.side,
                             "quantity": None, "amount_byn": format(amount, ".2f"),
                             "lot": dimensions["lot"], "late_cost": True})
            continue
        if line.quantity is None:
            raise AccountingError("Inventory movement needs quantity for FIFO or weighted-average costing")
        quantity = Decimal(line.quantity)
        amount = Decimal(line.amount)
        if quantity <= 0 or amount <= 0:
            raise AccountingError("Inventory layer quantity and value must be positive")
        evidence.append({"entry_id": entry.id, "line_id": line.id, "source": entry.source,
                         "source_version": entry.source_version, "side": line.side,
                         "quantity": format(quantity, ".6f"), "amount_byn": format(amount, ".2f"),
                         "lot": dimensions["lot"]})
        if line.side == "debit":
            layers.append({"lot": dimensions["lot"], "quantity": quantity, "amount": amount,
                           "dimensions": dict(dimensions), "entry_id": entry.id, "line_id": line.id,
                           "posting_date": entry.posting_date.isoformat()})
            continue
        pool_value = sum((layer["amount"] for layer in layers), Decimal(0))
        remaining = quantity
        for layer in layers:
            if remaining <= 0:
                break
            if layer["quantity"] <= 0 or layer["dimensions"] != dimensions:
                continue
            take = min(layer["quantity"], remaining)
            unit = layer["amount"] / layer["quantity"]
            layer["quantity"] -= take
            if method != "weighted_average":
                layer["amount"] -= unit * take
            remaining -= take
        if remaining > 0:
            raise AccountingError("Inventory history has insufficient quantity in the credited lot")
        if method == "weighted_average":
            _distribute_pool_value(layers, pool_value - amount)
    if not matched:
        return [], evidence
    if method == "weighted_average":
        _distribute_pool_value(layers, sum((layer["amount"] for layer in layers), Decimal(0)))
    available = [layer for layer in layers if layer["quantity"] > 0 and layer["amount"] >= 0
                 and (not requested_lot or layer["lot"] == requested_lot)]
    return available, evidence


def _layer_payload(layer, quantity, amount, *, include_source_identity=False):
    quantity_text = format(quantity.normalize(), "f") if quantity else "0"
    payload = {"lot": layer["lot"], "quantity": quantity_text,
            "amount_byn": format(amount, ".2f"), "dimensions": layer["dimensions"]}
    if include_source_identity:
        payload.update(source_entry_id=layer["entry_id"], source_line_id=layer["line_id"])
    return payload


def _select_policy_layers(layers, quantity, method):
    """Return the deterministic FIFO/weighted allocation without mutating layers."""
    live = [layer for layer in layers if layer["quantity"] > 0]
    total_quantity = sum((layer["quantity"] for layer in live), Decimal(0))
    total_amount = sum((layer["amount"] for layer in live), Decimal(0))
    if quantity > total_quantity:
        raise AccountingError("Disposition allocation exceeds the available quantity or cost")
    remaining, allocated, selected = quantity, Decimal(0), []
    average = total_amount / total_quantity if method == "weighted_average" else None
    for layer in live:
        if remaining <= 0:
            break
        take = min(layer["quantity"], remaining)
        if method == "fifo":
            cost = layer["amount"] if take == layer["quantity"] else (layer["amount"] * take / layer["quantity"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            cost = (take * average).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if take == remaining:
                cost = (quantity * average).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) - allocated
        selected.append((layer, take, cost))
        allocated += cost
        remaining -= take
    if method == "weighted_average" and any(cost < 0 for _, _, cost in selected):
        # The legacy final-residual formula is preserved unless its per-layer
        # rounding would create an impossible negative monetary portion.
        total_cents = int((quantity * average).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
        quotas = [Fraction(total_cents) * Fraction(take) / Fraction(quantity) for _, take, _ in selected]
        cents = [quota.numerator // quota.denominator for quota in quotas]
        residual = total_cents - sum(cents)
        for index in sorted(range(len(cents)), key=lambda item: (-(quotas[item] - cents[item]), item))[:residual]:
            cents[index] += 1
        selected = [(layer, take, Decimal(value) / 100)
                    for (layer, take, _), value in zip(selected, cents, strict=True)]
    return live, total_quantity, total_amount, selected


def replay_source_allocation(layers, allocation):
    """Validate a complete versioned selection and return new layer balances.

    This pure calculation does not authenticate persisted commands. A durable
    caller must verify organization, source and registration boundary first.
    Legacy ledger replay is deliberately unchanged.
    """
    from modules.accounting.zero_value_disposals import InventoryDispositionAllocation

    selection = InventoryDispositionAllocation.model_validate(allocation)
    with localcontext() as context:
        context.prec = 64
        live, quantity, amount, selected = _select_policy_layers(layers, selection.quantity, selection.valuation_method)
        if selection.quantity > quantity or selection.amount_byn > amount:
            raise AccountingError("Disposition allocation exceeds the available quantity or cost")
        expected = [(layer["entry_id"], layer["line_id"], layer["dimensions"], take, cost)
                    for layer, take, cost in selected]
        actual = [(item.source_entry_id, item.source_line_id, item.inventory_dimensions,
                   item.quantity, item.amount_byn) for item in selection.layers]
        if actual != expected:
            raise AccountingError("Disposition allocation differs from the policy-selected sources or cost")
        result = [{**layer, "dimensions": dict(layer["dimensions"])} for layer in layers]
        by_source = {(layer["entry_id"], layer["line_id"]): layer for layer in result}
        if len(by_source) != len(result):
            raise AccountingError("Inventory history repeats an origin")
        for item in selection.layers:
            layer = by_source[item.source_entry_id, item.source_line_id]
            layer["quantity"] -= item.quantity
            if selection.valuation_method == "fifo":
                layer["amount"] -= item.amount_byn
        if selection.valuation_method == "weighted_average":
            _distribute_pool_value(result, amount - selection.amount_byn)
        return result


def project_source_allocation(baseline_layers, prospective_layers, allocation):
    """Revalue one authenticated disposition without rewriting its saved cost.

    The caller authenticates the complete chronological history and applies cost
    overlays to prospective layers. Both pools must retain identical physical
    origins and quantities. The original allocation still passes strict replay;
    only the separate prospective allocation may carry different money.
    This pure step does not authorize posting or authenticate source documents.
    """
    from modules.accounting.zero_value_disposals import InventoryDispositionAllocation

    selection = InventoryDispositionAllocation.model_validate(allocation)
    with localcontext() as context:
        context.prec = 64
        def physical(layers):
            return [{key: value for key, value in layer.items() if key != "amount"} for layer in layers]
        if physical(baseline_layers) != physical(prospective_layers):
            raise AccountingError("Prospective cost must preserve the complete physical inventory pool")
        for layer in [*baseline_layers, *prospective_layers]:
            amount = layer["amount"]
            if (not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0
                    or (Fraction(amount) * 100).denominator != 1):
                raise AccountingError("Prospective inventory cost must be nonnegative whole cents")
            if layer["quantity"] < 0 or (layer["quantity"] == 0 and amount != 0):
                raise AccountingError("An exhausted inventory layer cannot retain value")
        baseline = replay_source_allocation(baseline_layers, selection)
        _, _, _, selected = _select_policy_layers(
            prospective_layers, selection.quantity, selection.valuation_method)
        # The selector depends on quantities, not the prospective value overlay.
        # Keep its exact origin ordering and dimensions, including zero portions.
        expected = [(item.source_entry_id, item.source_line_id, item.inventory_dimensions, item.quantity)
                    for item in selection.layers]
        if [(layer["entry_id"], layer["line_id"], layer["dimensions"], take)
                for layer, take, _ in selected] != expected:
            raise AccountingError("Prospective cost changed the reviewed physical source selection")
        projected = InventoryDispositionAllocation.model_validate({
            **selection.model_dump(),
            "amount_byn": sum((cost for _, _, cost in selected), Decimal(0)),
            "layers": [{**item.model_dump(), "amount_byn": cost}
                       for item, (_, _, cost) in zip(selection.layers, selected, strict=True)],
        })
        prospective = replay_source_allocation(prospective_layers, projected)
        for before, after, disposed in ((baseline_layers, baseline, selection.amount_byn),
                                        (prospective_layers, prospective, projected.amount_byn)):
            if (sum(Fraction(layer["amount"]) for layer in before)
                    != sum(Fraction(layer["amount"]) for layer in after) + Fraction(disposed)):
                raise AccountingError("Inventory cost projection does not conserve pool value")
        return {"baseline_layers": baseline, "prospective_layers": prospective,
                "allocation": projected, "delta_byn": projected.amount_byn - selection.amount_byn}


def _lot_balance(rows, target, posting_date, *, verified_value_lines=frozenset(),
                  verified_output_lines=frozenset(), finished_goods=False, zero_value_disposals=(),
                 organization_id=None, before_registration_token=None, inventory_account=None):
    """Caller must authenticate each admitted (entry_id, line_id) cost adjustment.

    Public callers admit none until the durable late-cost verifier is wired.
    """
    evidence = []
    inventory_dimensions = None
    acquisition = None
    adjusted = False
    pool_value_origins = getattr(verified_value_lines, "pool_origins", {})
    with localcontext() as context:
        context.prec = 64
        quantity, amount = Decimal(0), Decimal(0)
        checked_zero_receipts = set()
        if organization_id is None and zero_value_disposals:
            raise AccountingError("Zero-value disposal replay needs an organization identity")
        for _, _, _, entry, line, zero_event in _chronological_events(
            rows, organization_id, posting_date, zero_value_disposals, before_registration_token,
            inventory_account=inventory_account
        ):
            if zero_event is not None:
                if (isinstance(zero_event, AuthenticatedZeroValueDisposal)
                        and isinstance(zero_event.command, AllocatedZeroValueDisposalCommand)):
                    raise AccountingError("Allocation zero-value replay requires FIFO or weighted-average policy")
                receipt, source_layer = zero_event
                dimensions = source_layer.inventory_dimensions
                if any(dimensions[key] != value for key, value in target.items()):
                    continue
                if receipt.posting_date > posting_date:
                    raise AccountingError("Selected lot has later movements; chronological costing is required")
                if receipt.receipt_id not in checked_zero_receipts:
                    command_quantity = sum((item.quantity for item in receipt.command.inventory_layers
                                            if item.inventory_dimensions == dimensions), Decimal(0))
                    if command_quantity > quantity or quantity <= 0:
                        raise AccountingError("Zero-value disposal cannot reduce a valued or exhausted specific lot")
                    command_cost = amount if command_quantity == quantity else (amount * command_quantity / quantity).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if command_cost != 0:
                        raise AccountingError("Zero-value disposal cannot reduce a valued or exhausted specific lot: rounded command cost is positive")
                    checked_zero_receipts.add(receipt.receipt_id)
                if quantity < source_layer.quantity:
                    raise AccountingError("Zero-value disposal cannot reduce a valued or exhausted specific lot")
                expected_cost = amount if quantity == source_layer.quantity else (amount * source_layer.quantity / quantity).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP)
                if expected_cost != 0:
                    raise AccountingError("Zero-value disposal cannot reduce a valued or exhausted specific lot")
                quantity -= source_layer.quantity
                amount -= expected_cost
                evidence.append({"receipt_id": receipt.receipt_id, "entry_id": None, "line_id": None,
                                 "source": receipt.command.source, "source_version": receipt.command.source_version,
                                 "side": "credit", "quantity": format(source_layer.quantity, ".6f"),
                                 "amount_byn": "0.00", "zero_value_disposal": True})
                continue
            dimensions = line.dimensions or {}
            if any(not dimensions.get(key) for key in target):
                raise AccountingError("Inventory account contains movements without warehouse, SKU or lot; reconcile first")
            if any(dimensions[key] != value for key, value in target.items()):
                continue
            if entry.posting_date > posting_date:
                raise AccountingError("Selected lot has later movements; chronological costing is required")
            if finished_goods and line.side == "debit" and (entry.id, line.id) not in verified_output_lines and (entry.id, line.id) not in verified_value_lines:
                raise AccountingError("Finished-goods layer has no verified production output receipt")
            value_key = (entry.id, line.id)
            value_only = value_key in verified_value_lines
            if value_only and value_key in pool_value_origins:
                raise AccountingError("V3 pool value adjustments require FIFO or weighted-average costing")
            if value_only and (entry.operation not in {"inventory_late_cost", "production_output_cost_correction"}
                               or line.quantity is not None
                               or entry.operation == "inventory_late_cost" and line.side != "debit"
                               or quantity <= 0 or line.amount <= 0):
                raise AccountingError("Invalid verified inventory value adjustment")
            if line.category != "asset" or line.cash or (line.quantity is None and not value_only):
                raise AccountingError("Lot movement has no quantity or is not owned inventory")
            if line.currency != "BYN":
                raise AccountingError("Foreign-currency inventory requires a separate issue rule")
            if inventory_dimensions is None:
                inventory_dimensions = dimensions
            elif inventory_dimensions != dimensions:
                raise AccountingError("Mixed lot analytics require explicit inventory layers before costing")
            if value_only:
                adjusted = True
            elif line.side == "debit":
                if adjusted:
                    raise AccountingError("Acquisition after cost adjustment requires separate lot layers")
                if acquisition is None:
                    acquisition = (line.amount, line.quantity)
                elif acquisition[0] * line.quantity != line.amount * acquisition[1]:
                    raise AccountingError("Different acquisition costs require separate lot identification")
            sign = 1 if line.side == "debit" else -1
            if not value_only:
                quantity += sign * line.quantity
            amount += sign * line.amount
            if quantity < 0 or amount < 0 or (quantity == 0 and amount != 0):
                raise AccountingError("Lot history has an invalid quantity/value balance; reconcile first")
            evidence.append({"entry_id": entry.id, "line_id": line.id, "source": entry.source,
                             "source_version": entry.source_version, "side": line.side,
                             "quantity": None if value_only else format(line.quantity, ".6f"), "amount_byn": format(line.amount, ".2f")})
        return quantity, amount, inventory_dimensions, evidence


async def preview_issue(session, org_id, data, *, procurement=None, source_allocations=False):
    from modules.accounting.late_cost_receipts import verified_value_lines

    policy, rows, output_lines, finished_goods = await _inventory_rows(session, org_id, data)
    verified = await verified_value_lines(session, org_id, rows, procurement)
    from modules.accounting.zero_value_disposals import available_authenticated_zero_value_disposals

    receipts = await available_authenticated_zero_value_disposals(session, org_id, procurement=procurement)
    from modules.accounting.inventory_allocation_loader import (
        load_authenticated_inventory_dispositions,
    )

    allocations = await load_authenticated_inventory_dispositions(session, org_id, procurement=procurement,
                                                                  inventory_account=data.account)
    explicit = source_allocations and policy.inventory_method in {"fifo", "weighted_average"}
    cost = issue_result(policy, rows, org_id, data, verified_value_lines=verified,
                        verified_output_lines=output_lines, finished_goods=finished_goods,
                        zero_value_disposals=receipts, authenticated_dispositions=allocations,
                        include_source_identity=explicit)
    if explicit:
        cost["source_allocation_version"] = 1
    return cost


async def replay_issue_result(session, policy, rows, org_id, data, *, verified_value_lines=frozenset(),
                              verified_output_lines=frozenset(), finished_goods=False,
                              before_registration_token=None, procurement=None):
    """Internal-only replay using DB-authenticated entryless zero-value receipts.

    This deliberately is not wired into public preview routes until their
    correction and late-cost contracts can carry the registration cutoff.
    """
    from modules.accounting.zero_value_disposals import load_authenticated_zero_value_disposals

    receipts = await load_authenticated_zero_value_disposals(
        session, org_id, before_registration_token=before_registration_token, procurement=procurement)
    return issue_result(policy, rows, org_id, data, verified_value_lines=verified_value_lines,
                        verified_output_lines=verified_output_lines, finished_goods=finished_goods,
                        zero_value_disposals=receipts, before_registration_token=before_registration_token)


def issue_result(policy, rows, org_id, data, *, verified_value_lines=frozenset(),
                 verified_output_lines=frozenset(), finished_goods=False, zero_value_disposals=(),
                 authenticated_dispositions=(), before_registration_token=None, include_source_identity=False):
    """Same calculation for live preview and verification of original history."""
    target = {"warehouse": data.warehouse, "sku": data.sku, "lot": data.lot}
    # Older internal reconstruction callers do not carry the policy method;
    # their historical contracts are the original specific-lot calculation.
    method = getattr(policy, "inventory_method", "specific")
    if authenticated_dispositions and method == "specific":
        raise AccountingError("Explicit source allocation replay requires FIFO or weighted-average policy")
    if include_source_identity and method not in {"fifo", "weighted_average"}:
        raise AccountingError("Explicit source allocation requires FIFO or weighted-average layer selection")
    with localcontext() as context:
        context.prec = 64
        inventory_layers = []
        if method == "specific":
            if not data.lot:
                raise AccountingError("Specific costing requires an explicit lot")
            quantity, amount, inventory_dimensions, evidence = _lot_balance(
                rows, target, data.posting_date, verified_value_lines=verified_value_lines,
                verified_output_lines=verified_output_lines, finished_goods=finished_goods,
                zero_value_disposals=zero_value_disposals, organization_id=org_id,
                before_registration_token=before_registration_token, inventory_account=data.account)
            if data.quantity > quantity:
                raise AccountingError("Insufficient book quantity in the selected lot")
            cost = amount if data.quantity == quantity else (amount * data.quantity / quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            inventory_layers = [_layer_payload({"lot": data.lot, "dimensions": inventory_dimensions}, data.quantity, cost)]
            method_target = target
        else:
            layers, evidence = _valuation_layers(rows, target, data.posting_date,
                                                 verified_value_lines=verified_value_lines,
                                                 verified_output_lines=verified_output_lines,
                                                 finished_goods=finished_goods, method=method,
                                                 zero_value_disposals=zero_value_disposals, organization_id=org_id,
                                                 authenticated_dispositions=authenticated_dispositions,
                                                 before_registration_token=before_registration_token,
                                                 inventory_account=data.account)
            quantity = sum((layer["quantity"] for layer in layers), Decimal("0"))
            amount = sum((layer["amount"] for layer in layers), Decimal("0"))
            if not layers or data.quantity > quantity:
                raise AccountingError("Insufficient book quantity for the selected SKU")
            method_target = {"warehouse": data.warehouse, "sku": data.sku}
            if method not in {"fifo", "weighted_average"}:
                raise AccountingError("The selected inventory valuation method is not supported")
            _, _, _, selected = _select_policy_layers(layers, data.quantity, method)
            inventory_layers = [_layer_payload(layer, take, layer_cost,
                                               include_source_identity=include_source_identity)
                                for layer, take, layer_cost in selected]
            cost = sum((Decimal(layer["amount_byn"]) for layer in inventory_layers), Decimal("0"))
            inventory_dimensions = method_target
        basis = {"organization_id": org_id, "request": data.model_dump(mode="json"), "evidence": evidence}
        basis["valuation_method"] = method
        basis["inventory_layers"] = inventory_layers
        if include_source_identity:
            basis["source_allocation_version"] = 1
        basis_digest = hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {"organization_id": org_id, "policy_id": policy.id, "method": method, "basis_digest": basis_digest,
                "posting_date": data.posting_date, "account": data.account, "dimensions": method_target,
                "inventory_dimensions": inventory_dimensions,
                "book_quantity": format(quantity, ".6f"), "book_value_byn": format(amount, ".2f"),
                "issue_quantity": format(data.quantity, ".6f"), "issue_cost_byn": format(cost, ".2f"),
                "remaining_quantity": format(quantity - data.quantity, ".6f"),
                "remaining_value_byn": format(amount - cost, ".2f"), "inventory_layers": inventory_layers, "evidence": evidence,
                "status": "preview", "stock_reserved": False, "posted": False,
                "final_cost_certified": False, "normative_verified": policy.normative_verified}


async def available_lots(session, org_id, data, *, procurement=None):
    from modules.accounting.late_cost_receipts import verified_value_lines

    policy, rows, output_lines, finished_goods = await _inventory_rows(session, org_id, data)
    verified = await verified_value_lines(session, org_id, rows, procurement)
    from modules.accounting.zero_value_disposals import available_authenticated_zero_value_disposals

    receipts = await available_authenticated_zero_value_disposals(session, org_id, procurement=procurement)
    from modules.accounting.inventory_allocation_loader import (
        load_authenticated_inventory_dispositions,
    )

    allocations = await load_authenticated_inventory_dispositions(session, org_id, procurement=procurement,
                                                                  inventory_account=data.account)
    # Match the issue rule: incomplete analytics anywhere on this account block costing.
    if any(any(not (line.dimensions or {}).get(key) for key in ("warehouse", "sku", "lot")) for _, line in rows):
        raise AccountingError("Inventory account contains movements without warehouse, SKU or lot; reconcile first")
    lots = sorted({line.dimensions["lot"] for _, line in rows
                   if line.dimensions["warehouse"] == data.warehouse and line.dimensions["sku"] == data.sku
                   and data.search.casefold() in line.dimensions["lot"].casefold()})
    result = []
    for lot in lots[:100]:
        target = {"warehouse": data.warehouse, "sku": data.sku, "lot": lot}
        try:
            if policy.inventory_method == "specific":
                if allocations:
                    raise AccountingError("Explicit source allocation replay requires FIFO or weighted-average policy")
                quantity, amount, _, _ = _lot_balance(rows, target, data.posting_date, verified_value_lines=verified,
                                                       verified_output_lines=output_lines, finished_goods=finished_goods,
                                                       zero_value_disposals=receipts, organization_id=org_id,
                                                       inventory_account=data.account)
            else:
                layers, _ = _valuation_layers(rows, target, data.posting_date, verified_value_lines=verified,
                                               verified_output_lines=output_lines, finished_goods=finished_goods,
                                               zero_value_disposals=receipts, organization_id=org_id,
                                               method=policy.inventory_method, inventory_account=data.account,
                                               authenticated_dispositions=allocations)
                quantity = sum((layer["quantity"] for layer in layers), Decimal("0"))
                amount = sum((layer["amount"] for layer in layers), Decimal("0"))
            verified_origins = [(entry.id, line.id) for entry, line in rows
                                if (entry.id, line.id) in output_lines
                                and (line.dimensions or {}) == target]
            zero_supported = policy.inventory_method == "specific" and len(verified_origins) == 1
            selectable = quantity > 0 and (amount > 0 or zero_supported)
            result.append({"lot": lot, "book_quantity": format(quantity, ".6f"),
                           "book_value_byn": format(amount, ".2f"),
                           "selectable": selectable,
                           "reason": None if selectable else "No supported positive quantity/value remaining"})
        except AccountingError as exc:
            result.append({"lot": lot, "book_quantity": None, "book_value_byn": None,
                           "selectable": False, "reason": str(exc)})
    return {"organization_id": org_id, "policy_id": policy.id, "posting_date": data.posting_date,
            "account": data.account, "warehouse": data.warehouse, "sku": data.sku,
            "lots": result, "has_more": len(lots) > 100, "stock_reserved": False,
            "final_cost_certified": False}
