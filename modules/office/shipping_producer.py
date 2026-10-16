"""Office request preparation, explicit association and exact payload verification."""
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.runtime.deps import get_core, get_session
from core.services.auth import get_current_user
from core.services.logistics import (
    ExactInvoiceIdentity,
    SourceDiscoveryV1,
    producer_sources_snapshot,
    snapshot_hash,
    snapshot_row,
)
from core.services.shipping_payload import (
    ShippingIntent,
    StrictShippingModel,
    canonical_hash,
    canonical_shipping_payload,
    shipping_intent_digest,
)
from modules.office.models import OfficeDoc
from modules.office.shipping_access import (
    assign_reviewer,
    authorize_doc,
    current_actor,
    latest_assignment,
)
from modules.office.shipping_associations import (
    OfficeInvoiceAssociation,
    ShippingRequest,
    ShippingReviewAssignment,
    source_hash,
    source_snapshot,
)


class RequestInput(StrictShippingModel):
    request_key: str = Field(min_length=1, max_length=64)
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_assignment_revision: int = Field(ge=1)
    intent: ShippingIntent


class Evidence(StrictShippingModel):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    invoice_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    explanation: str = Field(min_length=1, max_length=1000)


class ConfirmInput(StrictShippingModel):
    request_key: str = Field(min_length=1, max_length=64)
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_assignment_revision: int = Field(ge=1)
    exact_invoice: ExactInvoiceIdentity
    envelope_id: str = Field(min_length=36, max_length=36)
    expected_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_intent_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_refs: Evidence


class AssignmentInput(StrictShippingModel):
    subject: str = Field(max_length=200)
    expected_revision: int = Field(ge=0)
    evidence: str = Field(min_length=1, max_length=1000)


def conflict(message):
    raise HTTPException(409, message)


def request_result(row):
    return {"envelope_id": row.id, "payload": row.payload, "payload_sha256": row.payload_sha256,
            "source_sha256": row.source_sha256}


class OfficeShippingProducer:
    def __init__(self, core):
        self.core, self.services = core, core.services

    async def _invoice_snapshot_records(self, session, exact, user):
        try:
            await current_actor(self.core, session, user, "office.doc.read")
            associations = list(await session.scalars(select(OfficeInvoiceAssociation).where(
                OfficeInvoiceAssociation.organization_id == exact["organization_id"],
                OfficeInvoiceAssociation.exact_invoice["document_id"].as_integer() == exact["document_id"],
                OfficeInvoiceAssociation.exact_invoice["expected_version"].as_integer() == exact["expected_version"],
                OfficeInvoiceAssociation.exact_invoice["expected_content_sha256"].as_string() == exact["expected_content_sha256"],
            ).order_by(OfficeInvoiceAssociation.id).execution_options(populate_existing=True)))
            records = []
            for association in associations:
                doc = await session.scalar(select(OfficeDoc).where(OfficeDoc.id == association.office_doc_id)
                    .execution_options(populate_existing=True))
                if doc is None:
                    conflict("Office snapshot source changed")
                await authorize_doc(self.core, session, doc, user, "office.doc.read")
                row = await session.scalar(select(ShippingRequest).where(ShippingRequest.id == association.request_id)
                    .execution_options(populate_existing=True))
                if row is None or association.exact_invoice != exact or row.office_doc_id != doc.id:
                    conflict("Office snapshot association changed")
                records.append((association, row, doc))
            return records
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                raise HTTPException(403, "producer_scope_unavailable") from None
            raise

    async def discover_invoice_shipping_sources(self, session, *, exact_invoice, user):
        exact = ExactInvoiceIdentity.model_validate(exact_invoice).model_dump()
        records = await self._invoice_snapshot_records(session, exact, user)
        return SourceDiscoveryV1(source_kind="office", exact_invoice=exact,
            source_keys=sorted({f"office:shipping-request:{row.id}" for _, row, _ in records}),
            source_document_ids=sorted({doc.id for _, _, doc in records})).model_dump()

    async def lock_invoice_shipping_sources_snapshot(self, session, *, exact_invoice, user, discovery):
        exact = ExactInvoiceIdentity.model_validate(exact_invoice).model_dump()
        expected = SourceDiscoveryV1.model_validate(discovery).model_dump()
        current = await self.discover_invoice_shipping_sources(session, exact_invoice=exact, user=user)
        if current != expected:
            conflict("Office snapshot discovery changed")
        list(await session.scalars(select(OfficeDoc).where(OfficeDoc.id.in_(current["source_document_ids"]))
            .order_by(OfficeDoc.id).with_for_update().execution_options(populate_existing=True)))
        if await self.discover_invoice_shipping_sources(session, exact_invoice=exact, user=user) != expected:
            conflict("Office snapshot source changed while waiting")
        sources = []
        for association, row, doc in await self._invoice_snapshot_records(session, exact, user):
            model, hashed = canonical_shipping_payload(row.payload)
            # Read scope is current and checked under OfficeDoc lock. Historical
            # attribution remains visible without granting new fulfillment.
            verified = await self.verify_shipping_source(session, source_kind="office",
                source_key=f"office:shipping-request:{row.id}", source_revision="1", actual_payload_hash=hashed)
            if not verified or verified["exact_invoice"] != exact or verified["association_id"] != association.id:
                conflict("Office snapshot verification changed")
            historical = await session.scalar(select(ShippingReviewAssignment).where(
                ShippingReviewAssignment.office_doc_id == doc.id,
                ShippingReviewAssignment.revision == association.assignment_revision,
            ).execution_options(populate_existing=True))
            latest = await latest_assignment(session, doc.id)
            sources.append({"source": model.source.model_dump(),
                "envelope": {"record_id": row.id, "row_sha256": snapshot_hash(snapshot_row(row)),
                    "payload_sha256": hashed, "payload": model.model_dump()},
                "association": {"record_id": association.id, "revision": "1", "row_sha256": snapshot_hash(snapshot_row(association))},
                "execution_id": verified["execution_id"], "intent_digest": verified["intent_digest"],
                "source_state_sha256": snapshot_hash({"document": snapshot_row(doc),
                    "historical_assignment": snapshot_row(historical), "current_assignment": snapshot_row(latest)}),
                "fulfillment_allowed": verified["fulfillment_allowed"]})
        return producer_sources_snapshot(exact, sources)

    async def _request(self, session, kind, key, revision=None):
        if kind != "office" or not isinstance(key, str) or not key.startswith("office:shipping-request:"):
            return None
        raw = key.removeprefix("office:shipping-request:")
        try:
            if str(UUID(raw)) != raw or revision not in {None, "1"}:
                return None
        except ValueError:
            return None
        return await session.scalar(select(ShippingRequest).where(ShippingRequest.id == raw)
            .execution_options(populate_existing=True))

    async def authorize_shipping_intake(self, session, *, source_kind, source_key, user):
        row = await self._request(session, source_kind, source_key)
        if row is None:
            raise HTTPException(404, "Office shipping request not found")
        doc = await session.scalar(select(OfficeDoc).where(OfficeDoc.id == row.office_doc_id)
            .execution_options(populate_existing=True))
        await authorize_doc(self.core, session, doc, user, "office.shipping.associate", reviewer=True)

    async def resolve_shipping_source(self, session, *, source_kind, source_key, source_revision):
        row = await self._request(session, source_kind, source_key, source_revision)
        if row is None:
            return None
        assoc = await session.scalar(select(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.request_id == row.id))
        return dict(assoc.exact_invoice) if assoc else None

    async def verify_shipping_source(self, session, *, source_kind, source_key, source_revision, actual_payload_hash, user=None):
        try:
            return await self._verify_shipping_source(session, source_kind=source_kind, source_key=source_key,
                source_revision=source_revision, actual_payload_hash=actual_payload_hash, user=user)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(409, "Persisted shipping source is invalid") from exc

    async def _verify_shipping_source(self, session, *, source_kind, source_key, source_revision, actual_payload_hash, user=None):
        row = await self._request(session, source_kind, source_key, source_revision)
        if row is None:
            return None
        # Caller owns org/deal/invoice locks. All Office writers use this same row.
        doc = await session.scalar(select(OfficeDoc).where(OfficeDoc.id == row.office_doc_id)
            .with_for_update().execution_options(populate_existing=True))
        if user is not None:
            await authorize_doc(self.core, session, doc, user, "office.shipping.associate", reviewer=True)
        model, computed = canonical_shipping_payload(row.payload)
        if (doc is None or source_hash(doc) != row.source_sha256
                or canonical_hash(row.source_snapshot) != row.source_sha256
                or computed != row.payload_sha256 or actual_payload_hash != computed
                or model.source.key != source_key or model.source.revision != source_revision
                or model.source_refs.document_id != doc.id or model.source_refs.document_number != doc.number):
            conflict("Office source or actual payload changed")
        assoc = await session.scalar(select(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.request_id == row.id)
            .execution_options(populate_existing=True))
        if assoc is None:
            return None
        historical = await session.scalar(select(ShippingReviewAssignment).where(
            ShippingReviewAssignment.office_doc_id == doc.id,
            ShippingReviewAssignment.revision == assoc.assignment_revision,
        ).execution_options(populate_existing=True))
        if historical is None or not historical.subject or historical.subject != assoc.actor:
            conflict("Office historical reviewer attribution changed")
        assignment = await latest_assignment(session, doc.id)
        fulfillment_allowed = bool(assignment is not None
            and assignment.revision == historical.revision and assignment.subject == historical.subject)
        exact = ExactInvoiceIdentity.model_validate(assoc.exact_invoice).model_dump()
        evidence = Evidence.model_validate(assoc.evidence_refs)
        if (assoc.office_doc_id != doc.id or assoc.organization_id != exact["organization_id"]
                or evidence.source_sha256 != row.source_sha256 or evidence.invoice_sha256 != exact["expected_content_sha256"]
                or shipping_intent_digest(exact, model.intent) != assoc.intent_digest
                or str(UUID(assoc.execution_id)) != assoc.execution_id):
            conflict("Office association integrity changed")
        return {"exact_invoice": exact, "execution_id": assoc.execution_id, "intent_digest": assoc.intent_digest,
                "fulfillment_allowed": fulfillment_allowed,
                "payload_sha256": computed, "association_id": assoc.id, "association_revision": "1"}

    async def prepare(self, session, doc_id, data, user):
        # An unbound preparation takes only OfficeDoc; binding serializes on it.
        existing_assoc = await session.scalar(select(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.office_doc_id == doc_id))
        if existing_assoc:
            await self.services.accounting.source_member(session, existing_assoc.organization_id, user)
        doc = await session.scalar(select(OfficeDoc).where(OfficeDoc.id == doc_id)
            .with_for_update().execution_options(populate_existing=True))
        if doc is None:
            raise HTTPException(404, "Office document not found")
        current_assoc = await session.scalar(select(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.office_doc_id == doc_id)
            .execution_options(populate_existing=True))
        if (current_assoc.id if current_assoc else None) != (existing_assoc.id if existing_assoc else None):
            conflict("Office ownership changed while waiting; retry")
        actor, revision = await authorize_doc(self.core, session, doc, user, "office.carrier.request", reviewer=True)
        if source_hash(doc) != data.expected_source_hash or revision != data.expected_assignment_revision:
            conflict("Office source or reviewer changed")
        existing = await session.scalar(select(ShippingRequest).where(ShippingRequest.office_doc_id == doc_id))
        if existing:
            model, computed = canonical_shipping_payload(existing.payload)
            if (existing.request_key != data.request_key or existing.source_sha256 != data.expected_source_hash
                    or model.intent != data.intent or computed != existing.payload_sha256):
                conflict("Office shipping request already differs")
            return request_result(existing)
        if doc.stage != "ready":
            conflict("Only a ready Office document can create a new shipping request")
        request_id = str(uuid4())
        payload = {"schema_version": 1,
            "source": {"kind": "office", "key": f"office:shipping-request:{request_id}", "revision": "1"},
            "source_refs": {"document_id": doc.id, "document_number": doc.number, "log_ref": ""},
            "intent": data.intent.model_dump()}
        model, computed = canonical_shipping_payload(payload)
        row = ShippingRequest(id=request_id, office_doc_id=doc.id, request_key=data.request_key,
            source_snapshot=source_snapshot(doc), source_sha256=data.expected_source_hash,
            payload=model.model_dump(), payload_sha256=computed, actor=actor)
        session.add(row)
        await session.flush()
        self.services.event_bus.emit(session, "logistics.delivery.requested", {**row.payload, "payload_sha256": computed})
        return request_result(row)

    async def association(self, session, doc_id, data, user, *, confirm):
        hint = await session.get(OfficeDoc, doc_id)
        if hint is None:
            raise HTTPException(404, "Office document not found")
        await authorize_doc(self.core, session, hint, user, "office.shipping.associate", reviewer=True)
        exact = data.exact_invoice.model_dump()
        await self.services.accounting.source_owner_authority(session, exact["organization_id"], user)
        # Discovery only; existing association cannot be changed to another invoice.
        old = await session.scalar(select(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.office_doc_id == doc_id))
        if old is not None and old.exact_invoice != exact:
            conflict("Office association already names another exact invoice")
        try:
            facts = await self.services.sales_source.invoice_shipping_source(session, exact["document_id"],
                organization_id=exact["organization_id"], expected_version=exact["expected_version"],
                expected_content_sha256=exact["expected_content_sha256"], operation="historical_claim" if old else "fulfill")
        except ValueError as exc:
            conflict(str(exc))
        doc = await session.scalar(select(OfficeDoc).where(OfficeDoc.id == doc_id)
            .with_for_update().execution_options(populate_existing=True))
        if doc is None:
            raise HTTPException(404, "Office document not found")
        user, _ = await current_actor(self.core, session, user, "office.shipping.associate")
        actor, revision = await authorize_doc(self.core, session, doc, user, "office.shipping.associate", reviewer=True)
        await self.services.sales_source.authorize_shipping_deal(session, facts["deal_id"], user)
        if doc.deal_id is not None and doc.deal_id != facts["deal_id"]:
            conflict("Office linked deal differs from invoice")
        row = await session.scalar(select(ShippingRequest).where(ShippingRequest.office_doc_id == doc_id)
            .execution_options(populate_existing=True))
        if row is None or row.id != data.envelope_id:
            conflict("Prepare and review the immutable Office request first")
        model, computed = canonical_shipping_payload(row.payload)
        expected = shipping_intent_digest(exact, model.intent)
        if (source_hash(doc) != data.expected_source_hash or row.source_sha256 != data.expected_source_hash
                or canonical_hash(row.source_snapshot) != row.source_sha256
                or computed != row.payload_sha256 or computed != data.expected_payload_hash
                or revision != data.expected_assignment_revision or expected != data.expected_intent_digest
                or data.evidence_refs.source_sha256 != row.source_sha256
                or data.evidence_refs.invoice_sha256 != exact["expected_content_sha256"]):
            conflict("Office source, assignment, intent or evidence changed; review again")
        if not data.evidence_refs.explanation.strip():
            conflict("Documentary explanation is required")
        confirmation = canonical_hash(data.model_dump())
        old = await session.scalar(select(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.office_doc_id == doc_id)
            .execution_options(populate_existing=True))
        if old:
            if old.confirmation_sha256 != confirmation:
                conflict("Office association already differs")
            return {"association_id": old.id, "execution_id": old.execution_id, "intent_digest": old.intent_digest, "replayed": True}
        if not confirm:
            return {**request_result(row), "source_snapshot": row.source_snapshot, "verified_invoice": facts,
                    "exact_invoice": exact, "intent_digest": expected, "assignment_revision": revision}
        execution = await self.services.logistics.claim_execution(session, exact_invoice=exact,
            intent=model.intent.model_dump(), expected_digest=expected)
        if (execution.get("exact_invoice") != exact or execution.get("intent") != model.intent.model_dump()
                or execution.get("intent_digest") != expected or str(UUID(execution["execution_id"])) != execution["execution_id"]):
            conflict("Execution registry returned inconsistent evidence")
        assoc = OfficeInvoiceAssociation(id=str(uuid4()), request_id=row.id, office_doc_id=doc_id,
            organization_id=exact["organization_id"], exact_invoice=exact, execution_id=execution["execution_id"],
            intent_digest=expected, assignment_revision=revision, request_key=data.request_key,
            confirmation_sha256=confirmation, evidence_refs=data.evidence_refs.model_dump(), actor=actor)
        session.add(assoc)
        await session.flush()
        return {"association_id": assoc.id, "execution_id": assoc.execution_id, "intent_digest": expected, "replayed": False}


async def transaction(session=Depends(get_session)):
    try:
        yield session
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Shipping request key or association already exists") from exc
    except Exception:
        await session.rollback()
        raise


router = APIRouter()


@router.post("/docs/{doc_id}/shipping-reviewer")
async def shipping_reviewer(doc_id: int, data: AssignmentInput, session=Depends(transaction),
    core=Depends(get_core), user=Depends(get_current_user)):
    result = await assign_reviewer(core, session, doc_id, user, **data.model_dump())
    await session.commit()
    return result


@router.get("/docs/{doc_id}/shipping-source")
async def shipping_source(doc_id: int, session=Depends(transaction), core=Depends(get_core), user=Depends(get_current_user)):
    doc = await session.get(OfficeDoc, doc_id)
    if doc is None:
        raise HTTPException(404, "Office document not found")
    _, revision = await authorize_doc(core, session, doc, user, "office.doc.read")
    return {"source_snapshot": source_snapshot(doc), "source_sha256": source_hash(doc), "assignment_revision": revision}


@router.post("/docs/{doc_id}/shipping-association-preview")
async def shipping_association_preview(doc_id: int, data: ConfirmInput, session=Depends(transaction),
    core=Depends(get_core), user=Depends(get_current_user)):
    return await OfficeShippingProducer(core).association(session, doc_id, data, user, confirm=False)


@router.post("/docs/{doc_id}/shipping-association-confirm")
async def shipping_association_confirm(doc_id: int, data: ConfirmInput, session=Depends(transaction),
    core=Depends(get_core), user=Depends(get_current_user)):
    result = await OfficeShippingProducer(core).association(session, doc_id, data, user, confirm=True)
    await session.commit()
    return result
