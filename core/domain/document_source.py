"""Immutable, held observations of source documents; no native document binding."""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class DocumentSourceRevision(Base):
    __tablename__ = "document_source_revision"
    __table_args__ = (
        UniqueConstraint(
            "namespace", "entity", "source_guid", "revision_no", name="uq_document_source_revision"
        ),
        UniqueConstraint(
            "namespace", "entity", "source_guid", "data_version", name="uq_document_source_version"
        ),
        CheckConstraint("revision_no > 0", name="positive"),
        CheckConstraint("period_start < period_end", name="period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(128))
    source_guid: Mapped[str] = mapped_column(String(36))
    source_scope: Mapped[str] = mapped_column(String(48))
    revision_no: Mapped[int] = mapped_column()
    source_sha: Mapped[str] = mapped_column(String(64))
    data_version: Mapped[str] = mapped_column(String(255))
    previous_sha: Mapped[str | None] = mapped_column(String(64))
    source_text: Mapped[str] = mapped_column(Text)
    holds: Mapped[list[str]] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    organization_sha256: Mapped[str] = mapped_column(String(64))
    period_start: Mapped[datetime] = mapped_column(DateTime)
    period_end: Mapped[datetime] = mapped_column(DateTime)
    entity_scopes_sha256: Mapped[str] = mapped_column(String(64))
    entity_scopes_text: Mapped[str] = mapped_column(Text)
