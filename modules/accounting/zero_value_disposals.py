"""Immutable zero-value disposal commands, persistence and authenticated replay."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator
from sqlalchemy import select, text

from modules.accounting.schemas import Code, Input, Quantity


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def source_identity(source: str, source_version: int, operation: str) -> tuple[str, int, str]:
    """Return the exact identity shared with ``accounting.entry`` uniqueness."""
    if not source or source != source.strip() or any(character.isspace() for character in source):
        raise ValueError("Source identity must be nonempty and contain no whitespace")
    if type(source_version) is not int or source_version < 1:
        raise ValueError("Source version must be positive")
    if operation not in {"inventory_issue", "inventory_sale"}:
        raise ValueError("Zero-value disposal operation is unsupported")
    return source, source_version, operation


class ZeroValueInventoryLayer(Input):
    """One source line, retained even when several lines share analytics."""
    source_entry_id: int = Field(gt=0, strict=True)
    source_line_id: int = Field(gt=0, strict=True)
    inventory_account: Code
    inventory_dimensions: dict[str, str]
    quantity: Quantity

    @model_validator(mode="after")
    def complete_identity(self):
        if any(not self.inventory_dimensions.get(key) for key in ("warehouse", "sku", "lot")):
            raise ValueError("Zero-value layer needs warehouse, SKU and lot analytics")
        return self


class ZeroValueDisposalCommand(Input):
    operation: Literal["inventory_issue", "inventory_sale"]
    source: str = Field(min_length=1, max_length=160)
    source_version: int = Field(ge=1, strict=True)
    posting_date: date
    policy_id: int = Field(gt=0, strict=True)
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    destination_account: Code
    destination_dimensions: dict[str, str] = Field(default_factory=dict)
    inventory_layers: list[ZeroValueInventoryLayer] = Field(min_length=1, max_length=1000)
    explanation: str = Field(min_length=1, max_length=1000)

    @field_validator("source")
    @classmethod
    def exact_source(cls, value: str) -> str:
        source_identity(value, 1, "inventory_issue")
        return value

    @model_validator(mode="after")
    def complete_snapshot(self):
        source_identity(self.source, self.source_version, self.operation)
        if any(not key or not value.strip() or len(value) > 200 for key, value in self.destination_dimensions.items()):
            raise ValueError("Destination analytics must be nonempty and bounded")
        identities = [(layer.source_entry_id, layer.source_line_id) for layer in self.inventory_layers]
        if len(identities) != len(set(identities)):
            raise ValueError("Zero-value layers must not repeat the same source line")
        return self

    @property
    def identity(self) -> tuple[str, int, str]:
        return source_identity(self.source, self.source_version, self.operation)


class DatedZeroValueDisposalCommand(ZeroValueDisposalCommand):
    """Version two preserves primary-document dates without changing v1 hashes."""

    command_version: Literal[2]
    document_date: date
    operation_date: date


def parse_zero_value_command(snapshot: object) -> ZeroValueDisposalCommand:
    if not isinstance(snapshot, dict):
        raise ValueError("Zero-value disposal command must be an object")
    if "command_version" not in snapshot:
        return ZeroValueDisposalCommand.model_validate(snapshot)
    if type(snapshot["command_version"]) is not int or snapshot["command_version"] != 2:
        raise ValueError("Unsupported zero-value disposal command version")
    return DatedZeroValueDisposalCommand.model_validate(snapshot)


def receipt_digest(organization_id: int, actor: str, command: ZeroValueDisposalCommand) -> str:
    """Canonical, exact digest for the full immutable receipt snapshot."""
    if type(organization_id) is not int or organization_id <= 0 or not actor or actor != actor.strip():
        raise ValueError("Receipt organization and actor must be exact")
    payload = {"organization_id": organization_id, "actor": actor, "command": command.model_dump(mode="json")}
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


@dataclass(frozen=True)
class AuthenticatedZeroValueDisposal:
    """Internal replay input authenticated by the database loader."""
    receipt_id: int
    organization_id: int
    posting_date: date
    registration_token: int
    actor: str
    command: ZeroValueDisposalCommand
    digest: str

    def __post_init__(self):
        if (type(self.receipt_id) is not int or self.receipt_id <= 0
            or type(self.registration_token) is not int or self.registration_token <= 0):
            raise ValueError("Authenticated zero-value receipt identity must be positive")
        if self.digest != receipt_digest(self.organization_id, self.actor, self.command):
            raise ValueError("Authenticated zero-value receipt digest does not match its full snapshot")
        if self.posting_date != self.command.posting_date:
            raise ValueError("Authenticated zero-value receipt date does not match its command")


async def register_standalone_zero_value_issue(session, organization_id: int, actor: str,
                                               command: ZeroValueDisposalCommand):
    """Persist one entryless, zero-total issue; DB guards authenticate every layer.

    Mixed-money commands and sales intentionally remain outside this persistence
    slice.  A receipt id is not an accounting entry id.
    """
    from modules.accounting.models import Organization, Period, ZeroValueInventoryDisposalReceipt
    from modules.accounting.service import audit, lock_organization, period_for

    if command.operation != "inventory_issue":
        raise ValueError("Standalone zero-value persistence supports inventory issues only")
    await lock_organization(session, organization_id)
    snapshot = {"organization_id": organization_id, "actor": actor, "command": command.model_dump(mode="json")}
    digest = await session.scalar(text("SELECT accounting.financial_sha(CAST(:snapshot AS jsonb))"), {
        "snapshot": canonical_json(snapshot),
    })
    identity = command.identity
    existing = await session.scalar(select(ZeroValueInventoryDisposalReceipt).where(
        ZeroValueInventoryDisposalReceipt.organization_id == organization_id,
        ZeroValueInventoryDisposalReceipt.source == identity[0],
        ZeroValueInventoryDisposalReceipt.source_version == identity[1],
        ZeroValueInventoryDisposalReceipt.operation == identity[2],
    ))
    if existing is not None:
        if existing.digest != digest or existing.actor != actor:
            raise ValueError("Zero-value disposal identity was already registered with different content")
        return existing
    calculated_basis = await preview_standalone_zero_value_issue_basis(session, organization_id, command, locked=True)
    if command.basis_digest != calculated_basis:
        raise ValueError("Zero-value disposal basis changed; preview again")
    receipt = ZeroValueInventoryDisposalReceipt(
        organization_id=organization_id, source=identity[0], source_version=identity[1], operation=identity[2],
        entry_id=None, posting_date=command.posting_date, policy_id=command.policy_id,
        command=command.model_dump(mode="json"), basis_digest=command.basis_digest, digest=digest, actor=actor,
    )
    session.add(receipt)
    await session.flush()
    period = await period_for(session, organization_id, command.posting_date.strftime("%Y-%m"))
    affected = (await session.scalars(select(Period).where(
        Period.organization_id == organization_id, Period.month >= period.month,
    ).execution_options(populate_existing=True))).all()
    for item in affected:
        item.generation += 1
        item.evidence = {}
    org = await session.get(Organization, organization_id)
    org.generation += 1
    audit(session, organization_id, actor, "zero_value_disposal_registered", {
        "receipt_id": receipt.id, "digest": digest, "basis_digest": command.basis_digest,
    })
    await session.flush()
    return receipt


async def preview_standalone_zero_value_issue_basis(session, organization_id: int,
                                                    command: ZeroValueDisposalCommand, *, locked: bool = False) -> str:
    """Return the database-authenticated basis for the single supported issue slice.

    The receipt service takes the organization lock before comparing this value;
    callers preparing a command should keep that same transaction open through
    registration, or retry if the basis becomes stale.
    """
    from modules.accounting.service import lock_organization

    if command.operation != "inventory_issue" or len(command.inventory_layers) != 1:
        raise ValueError("Standalone zero-value preview supports one inventory issue layer only")
    if not locked:
        await lock_organization(session, organization_id)
    result = await session.scalar(text(
        "SELECT accounting.zero_value_disposal_basis(:org, CAST(:command AS jsonb), 2147483647)"
    ), {"org": organization_id, "command": canonical_json(command.model_dump(mode="json"))})
    if not isinstance(result, str) or len(result) != 64:
        raise ValueError("Database did not return a valid zero-value disposal basis")
    return result


async def load_authenticated_zero_value_disposals(session, organization_id: int, *,
                                                  before_registration_token: int | None = None):
    """Load and re-authenticate durable receipts for internal valuation replay.

    ``before_registration_token`` excludes registrations made after an original
    ledger entry, but deliberately does not filter dates: an already-registered
    future-dated receipt must remain visible to chronological replay validation.
    """
    from modules.accounting.models import ZeroValueInventoryDisposalReceipt
    from modules.accounting.service import AccountingError, lock_organization

    if before_registration_token is not None and (type(before_registration_token) is not int
                                                   or before_registration_token <= 0):
        raise ValueError("Historical zero-value replay cutoff must be a positive registration token")
    await lock_organization(session, organization_id)
    schema_present = await session.scalar(text(
        "SELECT to_regclass('accounting.inventory_zero_value_disposal_receipt') IS NOT NULL"
    ))
    if schema_present is not True:
        raise AccountingError("Zero-value disposal migration 0140 is required for authenticated replay")
    query = select(ZeroValueInventoryDisposalReceipt).where(
        ZeroValueInventoryDisposalReceipt.organization_id == organization_id,
    ).order_by(ZeroValueInventoryDisposalReceipt.registration_token, ZeroValueInventoryDisposalReceipt.id)
    if before_registration_token is not None:
        query = query.where(ZeroValueInventoryDisposalReceipt.registration_token < before_registration_token)
    receipts = (await session.scalars(query)).all()
    verified = []
    for row in receipts:
        try:
            command = parse_zero_value_command(row.command)
        except (ValidationError, ValueError) as exc:
            raise AccountingError("Zero-value disposal command is not a valid immutable snapshot") from exc
        if (row.operation != "inventory_issue" or row.entry_id is not None or command.operation != row.operation
            or command.source != row.source or command.source_version != row.source_version
            or command.posting_date != row.posting_date or command.policy_id != row.policy_id
            or command.basis_digest != row.basis_digest):
            raise AccountingError("Zero-value disposal receipt header does not match its snapshot")
        snapshot = {"organization_id": organization_id, "actor": row.actor, "command": command.model_dump(mode="json")}
        database_digest = await session.scalar(text(
            "SELECT accounting.financial_sha(CAST(:snapshot AS jsonb))"
        ), {"snapshot": canonical_json(snapshot)})
        calculated_basis = await session.scalar(text(
            "SELECT accounting.zero_value_disposal_basis(:org, CAST(:command AS jsonb), :cutoff)"
        ), {"org": organization_id, "command": canonical_json(command.model_dump(mode="json")),
            "cutoff": row.registration_token})
        if row.digest != database_digest or row.basis_digest != calculated_basis:
            raise AccountingError("Zero-value disposal receipt digest or historical basis changed")
        try:
            verified.append(AuthenticatedZeroValueDisposal(
                receipt_id=row.id, organization_id=row.organization_id, posting_date=row.posting_date,
                registration_token=row.registration_token, actor=row.actor, command=command, digest=row.digest,
            ))
        except ValueError as exc:
            raise AccountingError("Zero-value disposal receipt cannot be authenticated for replay") from exc
    return tuple(verified)


async def require_public_zero_value_schema(session) -> None:
    """Refuse the public path until all receipt/date guards are installed."""
    ready = await session.scalar(text("""
        SELECT to_regclass('accounting.inventory_zero_value_disposal_receipt') IS NOT NULL
           AND to_regprocedure('accounting.validate_zero_value_disposal_command(jsonb)') IS NOT NULL
    """))
    if ready is not True:
        from modules.accounting.service import AccountingError

        raise AccountingError("Zero-value issue API requires migrations 0140 through 0142")


async def available_authenticated_zero_value_disposals(session, organization_id: int, *, before_registration_token=None):
    """Return replay events only where the PostgreSQL receipt schema exists.

    SQLite legacy tests never model this PostgreSQL-only durable receipt.  The
    dedicated public zero route calls ``require_public_zero_value_schema`` and
    therefore never treats a missing production migration as empty history.
    """
    if session.get_bind().dialect.name != "postgresql":
        return ()
    present = await session.scalar(text(
        "SELECT to_regclass('accounting.inventory_zero_value_disposal_receipt') IS NOT NULL"
    ))
    if present is not True:
        from modules.accounting.service import AccountingError

        raise AccountingError("Zero-value receipt migration 0140 is required for PostgreSQL inventory replay")
    return await load_authenticated_zero_value_disposals(
        session, organization_id, before_registration_token=before_registration_token
    )
