"""Project saved shipping facts onto Office cards; never authorize fulfillment."""
from types import SimpleNamespace
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from core.services.logistics import ExactInvoiceIdentity
from core.services.shipping_payload import canonical_hash
from modules.office.models import OfficeDoc
from modules.office.shipping_associations import OfficeInvoiceAssociation, ShippingRequest
from modules.office.shipping_producer import ConfirmInput, Evidence, OfficeShippingProducer


def display(value):
    """Only presentation text is shortened, never references or identities."""
    return value if len(value) <= 64 else value[:63] + "…"


def status_values(doc, status):
    values = {}
    shipment, target = status["shipment"], status["target"]
    if shipment is None and doc.logistics_ref:
        raise HTTPException(409, "Office reference has no proven saved shipment")
    if shipment is not None:
        reference = shipment["number"]
        if not reference or len(reference) > 64 or (doc.logistics_ref and doc.logistics_ref != reference):
            raise HTTPException(409, "Office shipment reference conflicts with saved attribution")
        values["logistics_ref"] = reference
        values["delivery"] = display(shipment["carrier_name"] or "")
        state = shipment["status"]
        if state == "delivered":
            text = "Доставлено, закрываем документы"
        elif state == "withdrawn":
            text = "Доставка отозвана"
        elif shipment["tracking_status"]:
            text = "Доставка: " + shipment["tracking_status"]
        else:
            text = {"planned": "Доставка запланирована", "assigned": "Назначен перевозчик",
                    "in_transit": "Груз в пути"}.get(state, "Доставка: " + state)
    elif status["state"] == "withdrawn" or (target and target["status"] == "withdrawn"):
        text = "Заявка на доставку отозвана"
    elif target is not None:
        text = "Выбор перевозчика"
    else:
        text = "Заявка ожидает обработки"
    return {**values, "docs_status": display(text)}
    # Payment stage and actual operation date cannot be inferred from shipping/ETA.


async def _legacy_ids(session, shipment):
    if shipment is None:
        return []
    return list(await session.scalars(select(OfficeDoc.id).where(
        OfficeDoc.logistics_ref == shipment["number"],
        ~select(ShippingRequest.id).where(ShippingRequest.office_doc_id == OfficeDoc.id).exists(),
    ).order_by(OfficeDoc.id)))


async def _project(ctx, candidates, *, selector=None, legacy_shipment=None):
    session = ctx.session
    producer = OfficeShippingProducer(SimpleNamespace(services=ctx.services))
    prepared = []
    with session.no_autoflush:
        for candidate in candidates:
            source = candidate["source"]
            request = await producer._request(session, source["kind"], source["key"], source["revision"])
            if request is None:
                raise HTTPException(409, "Office projection source is missing")
            prepared.append((candidate, request.id, request.office_doc_id))
        legacy_ids = await _legacy_ids(session, legacy_shipment)
        # Include legacy candidates in the same lock set; no late first-match lock.
        lock_ids = sorted({doc_id for _, _, doc_id in prepared} | set(legacy_ids))
        documents = {doc.id: doc for doc in await session.scalars(select(OfficeDoc).where(
            OfficeDoc.id.in_(lock_ids)).order_by(OfficeDoc.id)
            .with_for_update().execution_options(populate_existing=True))}
        if selector is not None:
            fresh = await ctx.services.logistics.office_shipping_projection_context(session, **selector)
            if fresh["sources"] != candidates:
                raise HTTPException(409, "Office projection source group changed while waiting")
            if legacy_shipment is not None:
                legacy_shipment = fresh["shipment"]
                if await _legacy_ids(session, legacy_shipment) != legacy_ids:
                    raise HTTPException(409, "Office legacy projection group changed while waiting")
        updates = []
        for candidate, request_id, doc_id in prepared:
            source = candidate["source"]
            verified = await producer.verify_shipping_source(session, source_kind=source["kind"],
                source_key=source["key"], source_revision=source["revision"],
                actual_payload_hash=candidate["payload_sha256"])
            request = await session.get(ShippingRequest, request_id, populate_existing=True)
            association = await session.scalar(select(OfficeInvoiceAssociation).where(
                OfficeInvoiceAssociation.request_id == request_id).execution_options(populate_existing=True))
            expected = None
            if association is not None:
                confirmation = ConfirmInput(request_key=association.request_key,
                    expected_source_hash=request.source_sha256,
                    expected_assignment_revision=association.assignment_revision,
                    exact_invoice=association.exact_invoice, envelope_id=request.id,
                    expected_payload_hash=request.payload_sha256,
                    expected_intent_digest=association.intent_digest,
                    evidence_refs=Evidence.model_validate(association.evidence_refs))
                if (verified is None or str(UUID(association.id)) != association.id
                        or canonical_hash(confirmation.model_dump()) != association.confirmation_sha256
                        or verified["association_id"] != association.id):
                    raise HTTPException(409, "Office projection association history changed")
                expected = {key: verified[key] for key in ("exact_invoice", "execution_id", "intent_digest")}
            status = await ctx.services.logistics.shipping_source_status(session, source=source,
                payload_sha256=candidate["payload_sha256"], expected_association=expected)
            if status["intake_id"] != candidate["intake_id"]:
                raise HTTPException(409, "Office projection intake changed")
            if doc_id not in documents:
                raise HTTPException(409, "Office projection document is missing")
            updates.append((documents[doc_id], status_values(documents[doc_id], status)))
        for doc_id in legacy_ids:
            if doc_id not in documents:
                raise HTTPException(409, "Office legacy projection document is missing")
            doc = documents[doc_id]
            updates.append((doc, status_values(doc, {"state": "resolved", "target": None,
                                                   "shipment": legacy_shipment})))
        # Validate the entire group before changing any display fields.
        for doc, values in updates:
            for name, value in values.items():
                setattr(doc, name, value)


async def project_context(ctx, *, include_legacy=False, **selector):
    """An event ID wakes a reread; its carrier, state and date are not proof."""
    context = await ctx.services.logistics.office_shipping_projection_context(ctx.session, **selector)
    await _project(ctx, context["sources"], selector=selector,
                   legacy_shipment=context["shipment"] if include_legacy else None)


async def on_intake_observed(payload, ctx):
    await project_context(ctx, intake_id=payload.get("intake_id"))


async def on_contract_signed(payload, ctx):
    await project_context(ctx, rfq_id=payload.get("rfq_id"))


async def on_invoice_cancelled(payload, ctx):
    exact = ExactInvoiceIdentity(organization_id=payload.get("organization_id"),
        document_id=payload.get("document_id"), expected_version=payload.get("document_version"),
        expected_content_sha256=payload.get("content_sha256")).model_dump()
    with ctx.session.no_autoflush:
        associations = list(await ctx.session.scalars(select(OfficeInvoiceAssociation).where(
            OfficeInvoiceAssociation.organization_id == exact["organization_id"])))
        candidates = []
        for association in associations:
            if association.exact_invoice != exact:
                continue
            request = await ctx.session.get(ShippingRequest, association.request_id, populate_existing=True)
            if request is None:
                raise HTTPException(409, "Cancelled invoice Office source is missing")
            source = {"kind": "office", "key": "office:shipping-request:" + request.id, "revision": "1"}
            status = await ctx.services.logistics.shipping_source_status(ctx.session, source=source,
                payload_sha256=request.payload_sha256, expected_association={"exact_invoice": exact,
                    "execution_id": association.execution_id, "intent_digest": association.intent_digest})
            if status["intake_id"] is not None:
                candidates.append({"source": source, "payload_sha256": request.payload_sha256,
                                   "intake_id": status["intake_id"]})
        await _project(ctx, candidates)
