"""Reproduce a saved late-cost receipt from its original authenticated history."""
from decimal import Decimal
from types import MappingProxyType
from typing import Annotated

from pydantic import BeforeValidator, Field, model_validator
from sqlalchemy import text

from modules.accounting import service
from modules.accounting.closing_commands import actual_posting
from modules.accounting.late_cost_posting import ExpenseAccounts, candidate, material_candidate
from modules.accounting.late_cost_preview import calculate, validate_currency
from modules.accounting.late_cost_sources import expense_history
from modules.accounting.models import Entry, LateCostReceipt, Policy
from modules.accounting.schemas import Input, LateCostPreviewInput, Money, PostingInput, exact


class VerifiedValueLines(frozenset):
    """Authenticated value-only lines with optional immutable V3 origins.

    It remains a ``frozenset`` so legacy callers keep admitting only the exact
    verified entry/line pairs.  V3 pool lines additionally identify the one
    acquisition layer they may adjust; replay must never infer it from
    analytics alone.
    """

    def __new__(cls, lines=(), *, pool_origins=None):
        result = super().__new__(cls, lines)
        result.pool_origins = MappingProxyType(dict(pool_origins or {}))
        return result


class LateCostCommand(Input):
    allocation: LateCostPreviewInput
    accounts: ExpenseAccounts


class MaterialOutputSelection(Input):
    output_entry_id: int = Field(gt=0, strict=True)
    amount_byn: Money = Field(gt=0)


class MaterialLateCostCommand(LateCostCommand):
    """Versioned opt-in; legacy receipt snapshots never gain these fields."""
    command_version: int = Field(default=2, strict=True, ge=2, le=2)
    material_outputs: list[MaterialOutputSelection] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_outputs(self):
        identities = [row.output_entry_id for row in self.material_outputs]
        if len(set(identities)) != len(identities):
            raise ValueError("Material output selections must be unique")
        return self


SignedMoney = Annotated[Decimal, BeforeValidator(exact), Field(max_digits=20, decimal_places=2)]


class PoolOutputSelection(Input):
    """V3 selection is intentionally distinct from persisted V2 material snapshots."""

    output_entry_id: int = Field(gt=0, strict=True)
    amount_byn: SignedMoney

    @model_validator(mode="after")
    def nonzero_amount(self):
        if self.amount_byn == 0:
            raise ValueError("Pool output selection amount must not be zero")
        return self


class PoolLateCostCommand(LateCostCommand):
    command_version: int = Field(strict=True)
    material_outputs: list[PoolOutputSelection] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def strict_pool_version_and_outputs(self):
        if type(self.command_version) is not int or self.command_version != 3:
            raise ValueError("Pool late-cost command version must be the integer 3")
        ids = [row.output_entry_id for row in self.material_outputs]
        if len(ids) != len(set(ids)):
            raise ValueError("Pool output selections must be unique")
        return self


def parse_command(snapshot):
    if not isinstance(snapshot, dict):
        raise service.AccountingError("Late cost command snapshot is invalid")
    if "command_version" not in snapshot:
        return LateCostCommand.model_validate(snapshot)
    if snapshot.get("command_version") != 2:
        raise service.AccountingError("Late cost command version is unsupported")
    return MaterialLateCostCommand.model_validate(snapshot)


async def verified_value_lines(session, organization_id, rows, procurement):
    """Authenticate every value-only line before allowing it into costing."""
    candidates = [(entry, line) for entry, line in rows if line.quantity is None]
    if not candidates:
        return VerifiedValueLines()
    candidate_keys = {(entry.id, line.id) for entry, line in candidates}
    candidate_entries = {entry.id: entry for entry, _ in candidates}
    v3_entries = {entry.id for entry, _ in candidates
                  if entry.operation == "inventory_late_cost"
                  and entry.rule_version == "late-cost-pool-v3"}
    pool_origins = {}
    if v3_entries:
        links_present = await session.scalar(text(
            "SELECT to_regclass('accounting.late_pool_inventory_value_link') IS NOT NULL"))
        if links_present is not True:
            raise service.AccountingError("V3 pool value adjustments require immutable acquisition links")
        link_rows = (await session.execute(text("""
            SELECT p.id AS package_id, p.late_entry_id,
                   link.value_entry_id, link.value_line_id,
                   link.acquisition_entry_id, link.acquisition_line_id
            FROM accounting.late_pool_package p
            LEFT JOIN accounting.late_pool_inventory_value_link link ON link.package_id=p.id
            WHERE p.organization_id=:org
        """), {"org": organization_id})).mappings().all()
        package_by_entry = {}
        for row in link_rows:
            entry_id = row["late_entry_id"]
            if entry_id not in v3_entries:
                continue
            prior = package_by_entry.setdefault(entry_id, row["package_id"])
            if prior != row["package_id"]:
                raise service.AccountingError("V3 pool entry has inconsistent immutable packages")
            if row["value_line_id"] is not None:
                key = (row["value_entry_id"], row["value_line_id"])
                origin = (row["acquisition_entry_id"], row["acquisition_line_id"])
                if key in pool_origins:
                    raise service.AccountingError("V3 pool value line has duplicate immutable origins")
                pool_origins[key] = origin
        if set(package_by_entry) != v3_entries:
            raise service.AccountingError("V3 pool value adjustment has no immutable package")
        for entry_id in sorted(v3_entries):
            await session.execute(text("SELECT accounting.verify_late_pool_package(:package)"),
                                  {"package": package_by_entry[entry_id]})
        missing = {key for key in candidate_keys if key[0] in v3_entries} - set(pool_origins)
        if missing:
            raise service.AccountingError("V3 pool value adjustment has no immutable acquisition origin")
    output_entries = {entry.id for entry, _ in candidates if entry.operation == "production_output_cost_correction"}
    if output_entries:
        from modules.accounting.production_output_revisions import verify_value_entry

        for entry_id in sorted(output_entries):
            await verify_value_entry(session, organization_id, entry_id)
    procurement_entries = set(candidate_entries) - output_entries - v3_entries
    if procurement_entries and procurement is None:
        raise service.AccountingError("Cost adjustments require the procurement source gateway")
    for entry_id in sorted(procurement_entries):
        await verify_receipt(session, organization_id, entry_id, procurement)
    return VerifiedValueLines(candidate_keys, pool_origins=pool_origins)


async def verify_receipt(session, organization_id, entry_id, procurement):
    """Caller authorizes organization access; no current-period recalculation."""
    await service.lock_organization(session, organization_id)
    entry = await session.get(Entry, entry_id)
    if entry is None or entry.organization_id != organization_id:
        raise service.AccountingError("Late cost has no matching source receipt")
    if entry.operation == "inventory_late_cost" and entry.rule_version == "late-cost-pool-v3":
        # V3 has no LateCostReceipt: its immutable package is the receipt.
        # Read it without replaying today's pools so later expenses can verify
        # the historical value movement that already belongs to this lot.
        from modules.accounting.late_pool_cost import load_package

        package = await load_package(session, organization_id, entry_id)
        if package.get("entry_id") != entry_id or package.get("organization_id") != organization_id:
            raise service.AccountingError("V3 late cost immutable package identity is inconsistent")
        preview = package.get("preview")
        if not isinstance(preview, dict):
            raise service.AccountingError("V3 late cost immutable package is incomplete")
        try:
            return PostingInput.model_validate(preview["posting"])
        except (KeyError, ValueError) as exc:
            raise service.AccountingError("V3 late cost immutable posting is invalid") from exc
    saved = await session.get(LateCostReceipt, entry_id)
    if saved is None or saved.organization_id != organization_id:
        raise service.AccountingError("Late cost has no matching source receipt")
    command = parse_command(saved.command)
    policy = await session.get(Policy, command.allocation.policy_id)
    if (policy is None or policy.organization_id != organization_id
        or policy.inventory_method not in {"specific", "fifo", "weighted_average"}
        or policy.effective_from > entry.posting_date or command.allocation.expected_version != saved.source_version):
        raise service.AccountingError("Late cost policy or source version is inconsistent")
    history = await expense_history(session, organization_id, saved.expense_id, saved.source_version,
        command.allocation.posting_date, procurement, before_entry_id=entry_id)
    await validate_currency(session, history["document"]["currency"], command.allocation)
    calculated = calculate(organization_id, saved.expense_id, command.allocation, policy, history)
    expected = (material_candidate if isinstance(command, MaterialLateCostCommand) else candidate)(calculated, command.accounts)
    if (calculated != saved.calculation or PostingInput.model_validate(saved.posting).model_dump() != expected.model_dump()
        or service.digest(expected) != saved.digest or entry.digest != saved.digest or entry.actor != saved.actor
        or (await actual_posting(session, entry)).model_dump() != expected.model_dump()):
        raise service.AccountingError("Late cost source, calculation or ledger package changed")
    return expected
