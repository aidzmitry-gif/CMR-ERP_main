"""Append-only Office shipping source, reviewer history and invoice association."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, event, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base
from core.services.shipping_payload import canonical_hash


class ShippingRequest(Base):
    __tablename__ = "shipping_request"
    __table_args__ = {"schema": "office"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    office_doc_id: Mapped[int] = mapped_column(ForeignKey("office.office_doc.id"), unique=True)
    request_key: Mapped[str] = mapped_column(String(64), unique=True)
    source_snapshot: Mapped[dict] = mapped_column(JSON)
    source_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OfficeInvoiceAssociation(Base):
    __tablename__ = "office_invoice_association"
    __table_args__ = {"schema": "office"}
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("office.shipping_request.id"), unique=True)
    office_doc_id: Mapped[int] = mapped_column(ForeignKey("office.office_doc.id"), unique=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    exact_invoice: Mapped[dict] = mapped_column(JSON)
    execution_id: Mapped[str] = mapped_column(String(36))
    intent_digest: Mapped[str] = mapped_column(String(64))
    assignment_revision: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(64), unique=True)
    confirmation_sha256: Mapped[str] = mapped_column(String(64))
    evidence_refs: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShippingReviewAssignment(Base):
    __tablename__ = "shipping_review_assignment"
    __table_args__ = (
        UniqueConstraint("office_doc_id", "revision", name="uq_office_shipping_review_revision"),
        {"schema": "office"},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    office_doc_id: Mapped[int] = mapped_column(ForeignKey("office.office_doc.id"))
    revision: Mapped[int] = mapped_column(Integer)
    # Empty subject is an explicit revocation, never public access.
    subject: Mapped[str] = mapped_column(String(200))
    evidence: Mapped[str] = mapped_column(String(1000))
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def source_snapshot(doc):
    return {"document_id": doc.id, "number": doc.number, "company": doc.company,
            "title": doc.title, "amount": format(doc.amount, ".2f"),
            "region": doc.region, "weight": doc.weight, "address": doc.address,
            "deal_id": doc.deal_id}


def source_hash(doc):
    return canonical_hash(source_snapshot(doc))


def immutable(*args):
    raise ValueError("Office shipping history is immutable")


for _model in (ShippingRequest, OfficeInvoiceAssociation, ShippingReviewAssignment):
    event.listen(_model, "before_update", immutable)
    event.listen(_model, "before_delete", immutable)
