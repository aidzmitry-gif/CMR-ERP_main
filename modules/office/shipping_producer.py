"""Office request preparation, explicit association and exact payload verification."""
from copy import deepcopy
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.runtime.deps import get_core, get_session
from core.services.auth import get_current_user, has_permission
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


def office_row_snapshot(doc):
    snapshot = snapshot_row(doc)
    # Legacy frozen source states predate author scope; NULL adds no new fact.
    if snapshot.get("draft_owner_subject") is None:
        snapshot.pop("draft_owner_subject", None)
    return snapshot


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
                "source_state_sha256": snapshot_hash({"document": office_row_snapshot(doc),
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


async def _shipping_read_rows(session, doc_id):
    doc = await session.scalar(select(OfficeDoc).where(OfficeDoc.id == doc_id)
        .execution_options(populate_existing=True))
    if doc is None:
        raise HTTPException(404, "Office document not found")
    request = await session.scalar(select(ShippingRequest).where(ShippingRequest.office_doc_id == doc_id)
        .execution_options(populate_existing=True))
    association = await session.scalar(select(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.office_doc_id == doc_id)
        .execution_options(populate_existing=True))
    assignment = await latest_assignment(session, doc_id)
    return doc, request, association, assignment


def _shipping_read_snapshot(rows):
    doc, request, association, assignment = rows
    return deepcopy({"document": {**source_snapshot(doc), "stage": doc.stage},
        "request": snapshot_row(request) if request is not None else None,
        "association": snapshot_row(association) if association is not None else None,
        "assignment": snapshot_row(assignment) if assignment is not None else None})


async def _shipping_context(session, core, user, doc_id):
    rows = await _shipping_read_rows(session, doc_id)
    frozen = _shipping_read_snapshot(rows)  # Never adopt a binding appearing after authorization.
    actor, revision = await authorize_doc(core, session, rows[0], user, "office.doc.read")
    effective, _ = await current_actor(core, session, user, "office.doc.read")
    doc, raw, assoc, assignment = (frozen[key] for key in ("document", "request", "association", "assignment"))
    source = {key: value for key, value in doc.items() if key != "stage"}
    current_hash = canonical_hash(source)
    reviewer = bool(assignment and assignment["subject"] == actor)
    result = {"source_snapshot": source, "source_sha256": current_hash, "assignment_revision": revision,
        "document_stage": doc["stage"], "principal": actor, "is_current_reviewer": reviewer,
        "capabilities": {"can_request": reviewer and has_permission(core, effective, "office.carrier.request"),
            "can_associate": reviewer and has_permission(core, effective, "office.shipping.associate")},
        "request": None, "association": None, "source_matches_request": True,
        "logistics": {"state": "not_prepared", "intake_id": None, "pending_reason": "", "target": None, "shipment": None}}
    expected_association = None
    if raw is None and assoc is not None:
        conflict("Office association has no prepared request")
    if raw is not None:
        model, computed = canonical_shipping_payload(raw["payload"])
        if (str(UUID(raw["id"])) != raw["id"] or raw["office_doc_id"] != doc_id
                or raw["source_snapshot"]["document_id"] != doc_id
                or canonical_hash(raw["source_snapshot"]) != raw["source_sha256"]
                or model.source.model_dump() != {"kind": "office", "key": "office:shipping-request:" + raw["id"], "revision": "1"}
                or model.source_refs.document_id != doc_id
                or model.source_refs.document_number != raw["source_snapshot"]["number"]
                or computed != raw["payload_sha256"]):
            conflict("Prepared Office request attribution changed")
        result["request"] = {"request_key": raw["request_key"], "actor": raw["actor"],
            "created_at": raw["created_at"], "source_snapshot": raw["source_snapshot"],
            "envelope_id": raw["id"], "payload": model.model_dump(),
            "payload_sha256": computed, "source_sha256": raw["source_sha256"]}
        result["source_matches_request"] = current_hash == raw["source_sha256"]
        if assoc is not None:
            if (assoc["office_doc_id"] != doc_id or assoc["request_id"] != raw["id"]
                    or str(UUID(assoc["id"])) != assoc["id"]
                    or str(UUID(assoc["execution_id"])) != assoc["execution_id"]):
                conflict("Office association refers to another request")
            evidence = Evidence.model_validate(assoc["evidence_refs"])
            confirmation = ConfirmInput(request_key=assoc["request_key"], expected_source_hash=raw["source_sha256"],
                expected_assignment_revision=assoc["assignment_revision"], exact_invoice=assoc["exact_invoice"],
                envelope_id=raw["id"], expected_payload_hash=computed,
                expected_intent_digest=assoc["intent_digest"], evidence_refs=evidence)
            exact = confirmation.exact_invoice.model_dump()
            historical = await session.scalar(select(ShippingReviewAssignment).where(
                ShippingReviewAssignment.office_doc_id == doc_id,
                ShippingReviewAssignment.revision == assoc["assignment_revision"],
            ).execution_options(populate_existing=True))
            if (historical is None or not historical.subject or historical.subject != assoc["actor"]
                    or assoc["organization_id"] != exact["organization_id"]
                    or evidence.source_sha256 != raw["source_sha256"]
                    or evidence.invoice_sha256 != exact["expected_content_sha256"]
                    or shipping_intent_digest(exact, model.intent) != assoc["intent_digest"]
                    or canonical_hash(confirmation.model_dump()) != assoc["confirmation_sha256"]):
                conflict("Office association history changed")
            expected_association = {"exact_invoice": exact, "execution_id": assoc["execution_id"],
                                    "intent_digest": assoc["intent_digest"]}
            result["association"] = {"association_id": assoc["id"], "request_key": assoc["request_key"],
                **expected_association, "assignment_revision": assoc["assignment_revision"],
                "current_review_matches": bool(assignment and assignment["revision"] == assoc["assignment_revision"]
                                               and assignment["subject"] == historical.subject)}
        status = getattr(core.services.logistics, "shipping_source_status", None)
        if not result["source_matches_request"]:
            result["logistics"]["state"] = "source_changed"
        elif status is None:
            result["logistics"]["state"] = "unavailable"
        else:
            result["logistics"] = await status(session, source=model.source.model_dump(), payload_sha256=computed,
                                                expected_association=expected_association)
    current = await _shipping_read_rows(session, doc_id)
    final_actor, final_revision = await authorize_doc(core, session, current[0], user, "office.doc.read")
    if _shipping_read_snapshot(current) != frozen or (final_actor, final_revision) != (actor, revision):
        conflict("Office shipping context changed while reading; refresh")
    return result


@router.post("/docs/{doc_id}/shipping-reviewer")
async def shipping_reviewer(doc_id: int, data: AssignmentInput, session=Depends(transaction),
    core=Depends(get_core), user=Depends(get_current_user)):
    result = await assign_reviewer(core, session, doc_id, user, **data.model_dump())
    await session.commit()
    return result


@router.get("/docs/{doc_id}/shipping-source")
async def shipping_source(doc_id: int, session=Depends(transaction), core=Depends(get_core), user=Depends(get_current_user)):
    try:
        with session.no_autoflush:
            return await _shipping_context(session, core, user, doc_id)
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(409, "Saved Office shipping context is invalid") from exc


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
