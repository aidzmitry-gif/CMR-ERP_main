"""Durable ESCHF records. PostgreSQL schema is installed by Alembic.

No signer/transport is registered here. Immutable bytes and attempt intent survive
process restarts; delivery is the only mutable projection.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class Original(Base):
    """Immutable invoice identity, shared by every pre-attempt preview revision."""

    __tablename__ = "original"
    __table_args__ = (
        UniqueConstraint("source_document_id", "document_type"),
        {"schema": "eschf"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_document_id: Mapped[int]
    document_type: Mapped[str] = mapped_column(String(24))
    environment: Mapped[str] = mapped_column(String(16))


class NumberReservation(Base):
    """Previously previewed numbers stay owned when pre-attempt preparation changes."""

    __tablename__ = "number_reservation"
    __table_args__ = (
        UniqueConstraint(
            "taxpayer_unp", "number", "original_id", name="uq_number_original_identity"
        ),
        {"schema": "eschf"},
    )

    taxpayer_unp: Mapped[str] = mapped_column(String(9), primary_key=True)
    number: Mapped[str] = mapped_column(String(30), primary_key=True)
    original_id: Mapped[UUID] = mapped_column(ForeignKey("eschf.original.id"))


class Snapshot(Base):
    __tablename__ = "snapshot"
    __table_args__ = (
        UniqueConstraint("id", "unsigned_sha256", name="uq_snapshot_unsigned_identity"),
        UniqueConstraint("id", "original_id", name="uq_snapshot_original_identity"),
        UniqueConstraint("supersedes_id"),
        ForeignKeyConstraint(
            ["taxpayer_unp", "number", "original_id"],
            [
                "eschf.number_reservation.taxpayer_unp",
                "eschf.number_reservation.number",
                "eschf.number_reservation.original_id",
            ],
            name="fk_snapshot_number_identity",
        ),
        CheckConstraint("document_type = 'ORIGINAL'", name="original_only"),
        CheckConstraint("source_document_id > 0 AND source_document_version > 0", name="source"),
        CheckConstraint("environment IN ('synthetic', 'native')", name="environment"),
        CheckConstraint(
            "binding_sha256 = encode(sha256(binding_snapshot), 'hex') "
            "AND unsigned_sha256 = encode(sha256(unsigned_xml), 'hex')",
            name="artifact_hashes",
        ).ddl_if(dialect="postgresql"),
        {"schema": "eschf"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    original_id: Mapped[UUID] = mapped_column(ForeignKey("eschf.original.id"))
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("eschf.snapshot.id"))
    document_type: Mapped[str] = mapped_column(String(24))
    source_document_id: Mapped[int]
    source_document_version: Mapped[int]
    source_content_sha256: Mapped[str] = mapped_column(String(64))
    source_snapshot_sha256: Mapped[str] = mapped_column(String(64))
    taxpayer_unp: Mapped[str] = mapped_column(String(9))
    number: Mapped[str] = mapped_column(String(30))
    binding_snapshot: Mapped[bytes] = mapped_column(LargeBinary)
    binding_sha256: Mapped[str] = mapped_column(String(64))
    unsigned_xml: Mapped[bytes] = mapped_column(LargeBinary)
    unsigned_sha256: Mapped[str] = mapped_column(String(64))
    adapter_id: Mapped[str] = mapped_column(String(128))
    environment: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliveryRecord(Base):
    __tablename__ = "delivery"
    __table_args__ = (
        CheckConstraint(
            "state IN ('prepared', 'approved', 'signed', 'queued', 'superseded', 'in_flight', "
            "'delivery_unknown', 'portal_processing', 'precheck_rejected', 'issued', "
            "'recipient_signed', 'agreement_pending', 'cancelled', 'cancellation_pending', "
            "'reconciliation_required', 'portal_error')",
            name="state",
        ),
        CheckConstraint(
            "(state IN ('portal_processing', 'precheck_rejected', 'issued', 'recipient_signed', "
            "'agreement_pending', 'cancelled', 'cancellation_pending', 'reconciliation_required', "
            "'portal_error')) = (observation_id IS NOT NULL)",
            name="portal_evidence",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "observation_id"],
            ["eschf.observation.snapshot_id", "eschf.observation.id"],
            name="fk_delivery_observation_identity",
        ),
        {"schema": "eschf"},
    )

    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("eschf.snapshot.id"), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), default="prepared")
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_binding_sha256: Mapped[str | None] = mapped_column(String(64))
    approved_unsigned_sha256: Mapped[str | None] = mapped_column(String(64))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    portal_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    unknown_reason: Mapped[str | None] = mapped_column(String(32))
    observation_id: Mapped[UUID | None]


class Decision(Base):
    """Immutable approval/queue/uncertainty facts, not a generic event framework."""

    __tablename__ = "decision"
    __table_args__ = (
        CheckConstraint("kind IN ('approved', 'queued', 'unknown')", name="kind"),
        CheckConstraint(
            "(kind = 'approved' AND binding_sha256 IS NOT NULL AND unsigned_sha256 IS NOT NULL "
            "AND reason IS NULL) OR (kind = 'queued' AND binding_sha256 IS NULL AND "
            "unsigned_sha256 IS NULL AND reason IS NULL) OR (kind = 'unknown' AND "
            "binding_sha256 IS NULL AND unsigned_sha256 IS NULL AND reason IS NOT NULL AND reason IN "
            "('timeout', 'process_restart', 'lost_response', 'commit_unknown'))",
            name="payload",
        ),
        {"schema": "eschf"},
    )

    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("eschf.snapshot.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    actor: Mapped[str] = mapped_column(String(128))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    binding_sha256: Mapped[str | None] = mapped_column(String(64))
    unsigned_sha256: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(32))


class SignedArtifact(Base):
    __tablename__ = "signed_artifact"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "signed_sha256", name="uq_signed_artifact_identity"),
        ForeignKeyConstraint(
            ["snapshot_id", "unsigned_sha256"],
            ["eschf.snapshot.id", "eschf.snapshot.unsigned_sha256"],
            name="fk_signed_artifact_unsigned_identity",
        ),
        CheckConstraint(
            "signed_sha256 = encode(sha256(signed_bytes), 'hex') "
            "AND verification_sha256 = encode(sha256(verification_evidence), 'hex')",
            name="artifact_hashes",
        ).ddl_if(dialect="postgresql"),
        {"schema": "eschf"},
    )

    snapshot_id: Mapped[UUID] = mapped_column(primary_key=True)
    signed_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    signed_sha256: Mapped[str] = mapped_column(String(64))
    # Relation verified by the adapter, not equality of unsigned/signed hashes.
    unsigned_sha256: Mapped[str] = mapped_column(String(64))
    verification_evidence: Mapped[bytes] = mapped_column(LargeBinary)
    verification_sha256: Mapped[str] = mapped_column(String(64))
    adapter_id: Mapped[str] = mapped_column(String(128))
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Attempt(Base):
    """One immutable intent per signed document. A crash never deletes/requeues it."""

    __tablename__ = "attempt"
    __table_args__ = (
        UniqueConstraint("claim_id"),
        UniqueConstraint("original_id"),
        ForeignKeyConstraint(
            ["snapshot_id", "original_id"],
            ["eschf.snapshot.id", "eschf.snapshot.original_id"],
            name="fk_attempt_original_identity",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "signed_sha256"],
            ["eschf.signed_artifact.snapshot_id", "eschf.signed_artifact.signed_sha256"],
            name="fk_attempt_signed_identity",
        ),
        {"schema": "eschf"},
    )

    snapshot_id: Mapped[UUID] = mapped_column(primary_key=True)
    original_id: Mapped[UUID]
    claim_id: Mapped[UUID] = mapped_column(default=uuid4)
    signed_sha256: Mapped[str] = mapped_column(String(64))
    worker_id: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Observation(Base):
    __tablename__ = "observation"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "evidence_sha256"),
        UniqueConstraint("snapshot_id", "id", name="uq_observation_identity"),
        CheckConstraint(
            "evidence_sha256 = encode(sha256(raw_evidence), 'hex')",
            name="artifact_hash",
        ).ddl_if(dialect="postgresql"),
        {"schema": "eschf"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("eschf.attempt.snapshot_id"))
    raw_evidence: Mapped[bytes] = mapped_column(LargeBinary)
    evidence_sha256: Mapped[str] = mapped_column(String(64))
    adapter_id: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(64))
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resulting_state: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


TABLES = [
    model.__table__
    for model in (
        Original,
        NumberReservation,
        Snapshot,
        DeliveryRecord,
        Decision,
        SignedArtifact,
        Attempt,
        Observation,
    )
]
