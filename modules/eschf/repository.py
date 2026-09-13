"""Local persistence boundary; no preparation, crypto implementation or transport.

The application must inject an authenticated adapter from trusted server wiring.
Do not construct it from HTTP fields. Raw evidence alone never establishes trust.
The adapter verifies portal ECP and the signed-to-final-XML relation; synthetic
adapters belong only in tests. No default adapter or success fallback exists.

Every mutation uses the caller's transaction, including core outbox events. A
claim is *intent*, not a transport capability: commit it before any future I/O;
after uncertain commit, crash or timeout reconcile, never dispatch it again.
The outbox carries audit notifications only, never a repeatable send command.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.contract import Permission
from core.services.auth import GUEST, CurrentUser, has_permission
from core.services.eventbus import OutboxEventBus
from modules.eschf.lifecycle import Delivery, PortalEvidence, observe
from modules.eschf.models import (
    Attempt,
    Decision,
    DeliveryRecord,
    NumberReservation,
    Observation,
    Original,
    SignedArtifact,
    Snapshot,
)
from modules.eschf.preparation import canonical, sha256

PERMISSIONS = tuple(
    Permission(f"eschf.{name}")
    for name in (
        "read",
        "prepare",
        "approve",
        "queue",
        "worker",
        "reconcile",
    )
)


@dataclass(frozen=True)
class SnapshotInput:
    """Internal G03 output. Source ACL/resolver/freshness precede this boundary.

    Binding is canonical JSON retaining the complete source/native projection.
    Its hash proves storage integrity, not native freshness or source authority.
    """

    number: str
    taxpayer_unp: str
    binding_snapshot: bytes
    unsigned_xml: bytes
    adapter_id: str
    environment: Literal["synthetic", "native"]


@dataclass(frozen=True)
class VerificationTarget:
    snapshot_id: UUID
    number: str
    taxpayer_unp: str
    unsigned_sha256: str
    signed_sha256: str | None
    binding_sha256: str
    environment: str


@dataclass(frozen=True)
class SignedVerification:
    """Adapter-verified relation to the exact final preview, plus audit proof."""

    number: str
    taxpayer_unp: str
    unsigned_sha256: str
    signed_sha256: str
    verification_evidence: bytes


class EvidenceAdapter(Protocol):
    adapter_id: str
    environment: Literal["synthetic", "native"]

    async def verify_signed(
        self,
        raw_signed: bytes,
        target: VerificationTarget,
    ) -> SignedVerification:
        """Verify signer/signature and exact final XML relation, or raise."""
        ...

    async def verify_portal(
        self, raw_evidence: bytes, target: VerificationTarget
    ) -> PortalEvidence:
        """Authenticate portal ECP/source; return verified identity/status or raise."""
        ...


def _hash(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _bytes(value: bytes) -> None:
    if not isinstance(value, bytes) or not value or len(value) > 16 * 1024 * 1024:
        raise ValueError("nonempty bounded artifact bytes required")


def _binding(value: SnapshotInput) -> dict:
    _bytes(value.binding_snapshot)
    _bytes(value.unsigned_xml)
    binding = json.loads(value.binding_snapshot)
    if not isinstance(binding, dict) or canonical(binding) != value.binding_snapshot:
        raise ValueError("canonical binding snapshot required")
    for field in ("source_document_id", "source_document_version"):
        if type(binding.get(field)) is not int or binding[field] <= 0:
            raise ValueError("positive source identity/version required")
    for field in ("source_content_sha256", "source_snapshot_sha256"):
        if not _hash(binding.get(field)):
            raise ValueError("source artifact hashes required")
    if binding.get("prepared_xml_sha256") != sha256(value.unsigned_xml):
        raise ValueError("final unsigned XML hash mismatch")
    for field in (
        "provider_identity",
        "recipient_selection",
        "native_version_evidence",
        "binding_evidence",
    ):
        if not isinstance(binding.get(field), dict) or not binding[field]:
            raise ValueError(f"{field} required from trusted resolver")
    for field in ("native_information_base_id", "native_metadata_object", "basis_reference"):
        if not isinstance(binding.get(field), str) or not binding[field].strip():
            raise ValueError(f"{field} required from trusted resolver")
    UUID(binding["native_invoice_uuid"])
    if not re.fullmatch(r"[0-9]{9}", value.taxpayer_unp) or not re.fullmatch(
        rf"{value.taxpayer_unp}-[0-9]{{4}}-[0-9]{{10}}", value.number
    ):
        raise ValueError("ESCHF taxpayer/number mismatch")
    if value.environment not in {"synthetic", "native"} or not value.adapter_id.strip():
        raise ValueError("explicit adapter provenance required")
    return binding


class Repository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        core,
        event_bus: OutboxEventBus,
        adapter: EvidenceAdapter | None = None,
    ) -> None:
        self.session = session
        self.core = core
        self.event_bus = event_bus
        self.adapter = adapter

    def _access(self, user: CurrentUser, permission: str) -> str:
        if (
            not user.username.strip()
            or user.roles == [GUEST]
            or not has_permission(self.core, user, f"eschf.{permission}")
        ):
            raise PermissionError(f"eschf.{permission} required")
        return user.keycloak_user_id or user.username

    def _emit(self, snapshot_id: UUID, action: str, actor: str, **detail) -> None:
        self.event_bus.emit(
            self.session,
            f"eschf.{action}",
            {
                "entity_ref": f"eschf:{snapshot_id}",
                "by": actor,
                **detail,
            },
        )

    async def _locked(
        self,
        snapshot_id: UUID,
        *,
        verify: bool = True,
    ) -> tuple[Snapshot, DeliveryRecord]:
        row = (
            await self.session.execute(
                select(DeliveryRecord)
                .where(DeliveryRecord.snapshot_id == snapshot_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        snapshot = await self.session.get(Snapshot, snapshot_id)
        assert snapshot is not None
        await self.session.execute(
            select(Original).where(Original.id == snapshot.original_id).with_for_update(),
        )
        if verify:
            expected = await self._projection(snapshot)
            if any(getattr(row, key) != value for key, value in expected.items()):
                raise ValueError(
                    "delivery projection integrity mismatch; recover from immutable facts"
                )
        return snapshot, row

    async def _projection(self, snapshot: Snapshot) -> dict:
        """Reconstruct ESCHF state from immutable, document-linked facts."""
        decisions = {
            d.kind: d
            for d in (
                await self.session.execute(
                    select(Decision).where(Decision.snapshot_id == snapshot.id),
                )
            ).scalars()
        }
        approval, queued, unknown = (decisions.get(k) for k in ("approved", "queued", "unknown"))
        signed = await self.session.get(SignedArtifact, snapshot.id)
        attempt = await self.session.get(Attempt, snapshot.id)
        latest = (
            await self.session.execute(
                select(Observation)
                .where(Observation.snapshot_id == snapshot.id)
                .order_by(Observation.since.desc(), Observation.id.desc())
                .limit(1),
            )
        ).scalar_one_or_none()
        successor = await self.session.scalar(
            select(Snapshot.id).where(Snapshot.supersedes_id == snapshot.id),
        )
        if (
            (signed is not None and approval is None)
            or (queued is not None and signed is None)
            or (attempt is not None and queued is None)
            or (unknown is not None and attempt is None)
            or (latest is not None and attempt is None)
            or (successor is not None and attempt is not None)
        ):
            raise ValueError("inconsistent immutable delivery facts")
        if approval is not None and (approval.binding_sha256, approval.unsigned_sha256) != (
            snapshot.binding_sha256,
            snapshot.unsigned_sha256,
        ):
            raise ValueError("approval evidence differs from immutable preview")
        state = "prepared"
        if approval is not None:
            state = "approved"
        if signed is not None:
            state = "signed"
        if queued is not None:
            state = "queued"
        if attempt is not None:
            state = "delivery_unknown" if unknown is not None else "in_flight"
        if latest is not None:
            state = latest.resulting_state
        if successor is not None:
            state = "superseded"
        return {
            "state": state,
            "approved_by": approval.actor if approval else None,
            "approved_at": approval.at if approval else None,
            "approved_binding_sha256": approval.binding_sha256 if approval else None,
            "approved_unsigned_sha256": approval.unsigned_sha256 if approval else None,
            "queued_at": queued.at if queued else None,
            "portal_since": latest.since if latest else None,
            "evidence_sha256": latest.evidence_sha256 if latest else None,
            "observation_id": latest.id if latest else None,
            "unknown_reason": unknown.reason if unknown else None,
        }

    async def _apply_projection(self, snapshot: Snapshot, row: DeliveryRecord) -> None:
        await self.session.flush()
        for key, value in (await self._projection(snapshot)).items():
            setattr(row, key, value)
        await self.session.flush()

    async def recover_projection(self, user: CurrentUser, snapshot_id: UUID) -> str:
        """Repair derived fields only. An existing attempt can never become queued."""
        actor = self._access(user, "reconcile")
        snapshot, row = await self._locked(snapshot_id, verify=False)
        await self._apply_projection(snapshot, row)
        self._emit(snapshot_id, "projection_recovered", actor, state=row.state)
        await self.session.flush()
        return row.state

    def _target(self, snapshot: Snapshot, signed: SignedArtifact | None = None):
        if (
            self.adapter is None
            or not self.adapter.adapter_id.strip()
            or self.adapter.environment != snapshot.environment
        ):
            raise ValueError("trusted evidence adapter unavailable or wrong environment")
        return VerificationTarget(
            snapshot.id,
            snapshot.number,
            snapshot.taxpayer_unp,
            snapshot.unsigned_sha256,
            signed.signed_sha256 if signed else None,
            snapshot.binding_sha256,
            snapshot.environment,
        )

    async def get(self, user: CurrentUser, snapshot_id: UUID) -> tuple[Snapshot, DeliveryRecord]:
        self._access(user, "read")
        return await self._locked(snapshot_id)

    async def prepare(self, user: CurrentUser, value: SnapshotInput) -> UUID:
        """Persist trusted G03 output, not resolve or regenerate a source document."""
        actor = self._access(user, "prepare")
        binding = _binding(value)
        original = Original(
            source_document_id=binding["source_document_id"],
            document_type="ORIGINAL",
            environment=value.environment,
        )
        self.session.add(original)
        await self.session.flush()
        return await self._insert_snapshot(actor, value, binding, original.id)

    async def supersede(
        self,
        user: CurrentUser,
        snapshot_id: UUID,
        value: SnapshotInput,
    ) -> UUID:
        """Refresh the latest preview before any attempt; keep all old artifacts.

        A new native number is allowed, but previously reserved numbers stay
        attached to the same source identity. Approval/signature never carries over.
        """
        actor = self._access(user, "prepare")
        binding = _binding(value)
        previous, row = await self._locked(snapshot_id)
        if (
            await self.session.scalar(
                select(Attempt.snapshot_id).where(Attempt.original_id == previous.original_id)
            )
            is not None
        ):
            raise ValueError("attempt exists; preparation refresh is forbidden")
        if row.state not in {"prepared", "approved", "signed", "queued"}:
            raise ValueError("only the latest never-attempted preparation can be superseded")
        if (binding["source_document_id"], value.environment) != (
            previous.source_document_id,
            previous.environment,
        ):
            raise ValueError("preparation refresh must keep its source identity and environment")
        fresh_id = await self._insert_snapshot(
            actor,
            value,
            binding,
            previous.original_id,
            supersedes_id=snapshot_id,
        )
        await self._apply_projection(previous, row)
        self._emit(snapshot_id, "preparation_superseded", actor, replacement=str(fresh_id))
        await self.session.flush()
        return fresh_id

    async def _insert_snapshot(
        self,
        actor: str,
        value: SnapshotInput,
        binding: dict,
        original_id: UUID,
        *,
        supersedes_id: UUID | None = None,
    ) -> UUID:
        reservation = await self.session.get(NumberReservation, (value.taxpayer_unp, value.number))
        if reservation is None or reservation.original_id != original_id:
            await self.session.execute(
                NumberReservation.__table__.insert().values(
                    taxpayer_unp=value.taxpayer_unp,
                    number=value.number,
                    original_id=original_id,
                )
            )
            await self.session.flush()  # A different source's reservation fails the unique key.
        snapshot = Snapshot(
            original_id=original_id,
            supersedes_id=supersedes_id,
            document_type="ORIGINAL",
            number=value.number,
            taxpayer_unp=value.taxpayer_unp,
            source_document_id=binding["source_document_id"],
            source_document_version=binding["source_document_version"],
            source_content_sha256=binding["source_content_sha256"],
            source_snapshot_sha256=binding["source_snapshot_sha256"],
            binding_snapshot=value.binding_snapshot,
            binding_sha256=sha256(value.binding_snapshot),
            unsigned_xml=value.unsigned_xml,
            unsigned_sha256=sha256(value.unsigned_xml),
            adapter_id=value.adapter_id,
            environment=value.environment,
            created_by=actor,
        )
        self.session.add(snapshot)
        await self.session.flush()
        self.session.add(DeliveryRecord(snapshot_id=snapshot.id, state="prepared"))
        self._emit(snapshot.id, "prepared", actor, binding_sha256=snapshot.binding_sha256)
        await self.session.flush()
        return snapshot.id

    async def approve(
        self,
        user: CurrentUser,
        snapshot_id: UUID,
        *,
        binding_sha256: str,
        unsigned_sha256: str,
    ) -> None:
        actor = self._access(user, "approve")
        snapshot, row = await self._locked(snapshot_id)
        if (binding_sha256, unsigned_sha256) != (snapshot.binding_sha256, snapshot.unsigned_sha256):
            raise ValueError("preview changed; explicit approval of exact bytes required")
        if row.state != "prepared":
            raise ValueError("only prepared snapshot can be approved")
        self.session.add(
            Decision(
                snapshot_id=snapshot_id,
                kind="approved",
                actor=actor,
                at=datetime.now(UTC),
                binding_sha256=binding_sha256,
                unsigned_sha256=unsigned_sha256,
            )
        )
        await self._apply_projection(snapshot, row)
        self._emit(snapshot_id, "approved", actor, unsigned_sha256=unsigned_sha256)
        await self.session.flush()

    async def attach_signed(self, user: CurrentUser, snapshot_id: UUID, raw_signed: bytes) -> None:
        """Verify and retain existing signed bytes. Does not perform signing."""
        actor = self._access(user, "approve")
        _bytes(raw_signed)
        snapshot, row = await self._locked(snapshot_id)
        if row.state != "approved":
            raise ValueError("exact unsigned preview must be approved first")
        target = self._target(snapshot)
        verified = await self.adapter.verify_signed(raw_signed, target)
        if (
            verified.number,
            verified.taxpayer_unp,
            verified.unsigned_sha256,
            verified.signed_sha256,
        ) != (
            snapshot.number,
            snapshot.taxpayer_unp,
            row.approved_unsigned_sha256,
            sha256(raw_signed),
        ):
            raise ValueError("signed artifact is not the approved final XML")
        _bytes(verified.verification_evidence)
        self.session.add(
            SignedArtifact(
                snapshot_id=snapshot_id,
                signed_bytes=raw_signed,
                signed_sha256=sha256(raw_signed),
                unsigned_sha256=verified.unsigned_sha256,
                verification_evidence=verified.verification_evidence,
                verification_sha256=sha256(verified.verification_evidence),
                adapter_id=self.adapter.adapter_id,
                created_by=actor,
            )
        )
        await self._apply_projection(snapshot, row)
        self._emit(snapshot_id, "signed_artifact_attached", actor, signed_sha256=sha256(raw_signed))
        await self.session.flush()

    async def enqueue(self, user: CurrentUser, snapshot_id: UUID) -> None:
        actor = self._access(user, "queue")
        snapshot, row = await self._locked(snapshot_id)
        if row.state != "signed":
            raise ValueError("only a signed, never-attempted document can be queued")
        if await self.session.get(Attempt, snapshot_id) is not None:
            raise ValueError("attempt exists; reconcile without automatic repeat")
        if await self.session.get(SignedArtifact, snapshot_id) is None:
            raise ValueError("verified signed artifact required")
        self.session.add(
            Decision(snapshot_id=snapshot_id, kind="queued", actor=actor, at=datetime.now(UTC))
        )
        await self._apply_projection(snapshot, row)
        self._emit(snapshot_id, "queued", actor)
        await self.session.flush()

    async def claim_next(self, user: CurrentUser) -> Attempt | None:
        """Lock one queued row and persist one intent; caller owns commit.

        No lease expiration/reclaim path exists: even a committed intent whose
        process died before I/O requires reconciliation. Outbox is not a sender.
        """
        actor = self._access(user, "worker")
        if self.session.get_bind().dialect.name != "postgresql":
            raise ValueError("durable concurrent claiming requires PostgreSQL")
        row = (
            await self.session.execute(
                select(DeliveryRecord)
                .where(DeliveryRecord.state == "queued")
                .order_by(DeliveryRecord.queued_at, DeliveryRecord.snapshot_id)
                .limit(1)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        snapshot, row = await self._locked(row.snapshot_id)
        signed = (
            await self.session.execute(
                select(SignedArtifact).where(SignedArtifact.snapshot_id == row.snapshot_id)
            )
        ).scalar_one()
        attempt = Attempt(
            snapshot_id=row.snapshot_id,
            original_id=snapshot.original_id,
            signed_sha256=signed.signed_sha256,
            worker_id=actor,
        )
        self.session.add(attempt)
        await self._apply_projection(snapshot, row)
        self._emit(row.snapshot_id, "attempt_recorded", actor, claim_id=str(attempt.claim_id))
        await self.session.flush()
        return attempt

    async def mark_unknown(self, user: CurrentUser, snapshot_id: UUID, *, reason: str) -> None:
        actor = self._access(user, "reconcile")
        if reason not in {"timeout", "process_restart", "lost_response", "commit_unknown"}:
            raise ValueError("explicit uncertainty reason required")
        snapshot, row = await self._locked(snapshot_id)
        if row.state != "in_flight":
            raise ValueError("no unresolved active attempt")
        self.session.add(
            Decision(
                snapshot_id=snapshot_id,
                kind="unknown",
                actor=actor,
                at=datetime.now(UTC),
                reason=reason,
            )
        )
        await self._apply_projection(snapshot, row)
        self._emit(snapshot_id, "delivery_unknown", actor, reason=reason)
        await self.session.flush()

    async def observe(self, user: CurrentUser, snapshot_id: UUID, raw_evidence: bytes) -> str:
        actor = self._access(user, "reconcile")
        _bytes(raw_evidence)
        snapshot, row = await self._locked(snapshot_id)
        if await self.session.get(Attempt, snapshot_id) is None:
            raise ValueError("no delivery attempt")
        signed = (
            await self.session.execute(
                select(SignedArtifact).where(SignedArtifact.snapshot_id == snapshot_id)
            )
        ).scalar_one()
        target = self._target(snapshot, signed)
        evidence = await self.adapter.verify_portal(raw_evidence, target)
        if evidence.evidence_sha256 != sha256(raw_evidence):
            raise ValueError("evidence hash differs from raw authenticated bytes")
        # Validate identity/signature even when the raw artifact was seen before.
        if evidence.signature_verified is not True or (
            evidence.number,
            evidence.taxpayer_unp,
            evidence.signed_sha256,
        ) != (snapshot.number, snapshot.taxpayer_unp, signed.signed_sha256):
            raise ValueError("unverified or unrelated portal evidence")
        prior = (
            await self.session.execute(
                select(Observation).where(
                    Observation.snapshot_id == snapshot_id,
                    Observation.evidence_sha256 == evidence.evidence_sha256,
                )
            )
        ).scalar_one_or_none()
        if prior is not None:
            if (prior.kind, prior.code, prior.since) != (
                evidence.kind,
                evidence.code,
                evidence.since,
            ):
                raise ValueError("conflicting interpretation of an existing evidence artifact")
            return row.state  # Replay cannot downgrade a later authenticated state.
        result = observe(
            Delivery(
                snapshot.number,
                snapshot.taxpayer_unp,
                signed.signed_sha256,
                row.state,
                row.portal_since,
                row.evidence_sha256,
            ),
            evidence,
        )
        self.session.add(
            Observation(
                snapshot_id=snapshot_id,
                raw_evidence=raw_evidence,
                evidence_sha256=evidence.evidence_sha256,
                adapter_id=self.adapter.adapter_id,
                kind=evidence.kind,
                code=evidence.code,
                since=evidence.since,
                resulting_state=result.state,
            )
        )
        await self._apply_projection(snapshot, row)
        self._emit(
            snapshot_id,
            "portal_observed",
            actor,
            state=row.state,
            evidence_sha256=evidence.evidence_sha256,
            adapter_id=self.adapter.adapter_id,
        )
        await self.session.flush()
        return row.state
