"""Addressed Office projection of recorded invoice issues; never a stock command."""
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from core.runtime.deps import get_core
from core.services.auth import get_current_user, has_permission
from core.services.logistics import ExactInvoiceIdentity, snapshot_row
from core.services.shipping_payload import canonical_hash
from modules.office.models import OfficeDoc
from modules.office.shipping_access import authorize_doc, current_actor
from modules.office.shipping_associations import OfficeInvoiceAssociation, ShippingRequest
from modules.office.shipping_producer import (
    ConfirmInput,
    Evidence,
    OfficeShippingProducer,
    transaction,
)

router = APIRouter()


def reject(message):
    raise HTTPException(409, message)


async def association(session, doc_id):
    return await session.scalar(select(OfficeInvoiceAssociation).where(
        OfficeInvoiceAssociation.office_doc_id == doc_id).execution_options(populate_existing=True))


async def verify_office(session, services, doc, frozen):
    try:
        return await _verify_office(session, services, doc, frozen)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(409, "Office warehouse history requires reconciliation") from exc


async def _verify_office(session, services, doc, frozen):
    current = await association(session, doc.id)
    if current is None or snapshot_row(current) != frozen:
        reject("Office warehouse association changed; refresh")
    request = await session.get(ShippingRequest, current.request_id, populate_existing=True)
    if request is None:
        reject("Office warehouse request is missing")
    verified = await OfficeShippingProducer(SimpleNamespace(services=services)).verify_shipping_source(
        session, source_kind="office", source_key="office:shipping-request:" + request.id,
        source_revision="1", actual_payload_hash=request.payload_sha256)
    confirmation = ConfirmInput(request_key=current.request_key, expected_source_hash=request.source_sha256,
        expected_assignment_revision=current.assignment_revision, exact_invoice=current.exact_invoice,
        envelope_id=request.id, expected_payload_hash=request.payload_sha256,
        expected_intent_digest=current.intent_digest, evidence_refs=Evidence.model_validate(current.evidence_refs))
    if (verified is None or verified["association_id"] != current.id
            or str(UUID(current.id)) != current.id
            or canonical_hash(confirmation.model_dump()) != current.confirmation_sha256):
        reject("Office warehouse association history is invalid")
    return verified["exact_invoice"]


def values(doc, progress):
    references = {"physical-shipment:" + act["source_key"] for act in progress["acts"]}
    if doc.wms_ref and doc.wms_ref not in references:
        reject("Office warehouse reference has no matching verified invoice act")
    if not progress["acts"]:
        return {}
    latest = max(progress["acts"], key=lambda act: act["act_id"])
    result = {"wms_ref": "physical-shipment:" + latest["source_key"]}
    if len(result["wms_ref"]) > 64:
        reject("Verified warehouse reference exceeds Office storage")
    if doc.stage == "ready":
        if progress["state"] == "complete":
            result.update(stage="shipped", docs_status="Выдача по счёту полностью зарегистрирована",
                next_step="Собрать пакет документов по зарегистрированной выдаче")
        elif progress["state"] == "partial":
            released = any(row["released_qty"] != "0.00" for row in progress["lines"])
            result.update(docs_status="Выдача по счёту частично зарегистрирована", next_step=(
                "Частичная выдача: остаток резерва снят, сверить основание" if released else
                "Частичная выдача: сверить остаток счёта и документ на передачу"))
    # Later document/payment stages and actual operation date are never regressed.
    return result


async def source_facts(services, session, exact, *, read_only=False):
    try:
        identity = ExactInvoiceIdentity.model_validate(exact).model_dump()
        if read_only:
            return await services.sales_source.invoice_shipping_read_source(session, **identity)
        return await services.sales_source.invoice_shipping_source(session, **identity, operation="historical_claim")
    except ValueError as exc:
        raise HTTPException(409, "Exact invoice warehouse source requires reconciliation") from exc


async def collect_progress(services, session, organization_id, facts):
    method = getattr(services.wms_reservations, "invoice_shipping_progress", None)
    if not callable(method):
        raise HTTPException(503, "Warehouse progress service is unavailable")
    return await method(session, organization_id, facts)


async def addressed(core, session, user, doc_id, permission, *, read_only=False):
    doc = await session.get(OfficeDoc, doc_id, populate_existing=True)
    if doc is None:
        raise HTTPException(404, "Office document not found")
    initial_document = snapshot_row(doc)
    bound = await association(session, doc_id)
    frozen = snapshot_row(bound) if bound else None
    actor, revision = await authorize_doc(core, session, doc, user, permission)
    checked = await association(session, doc_id)
    if (snapshot_row(checked) if checked else None) != frozen:
        reject("Office warehouse binding changed during authorization; refresh")
    if frozen is None:
        # Explicitly unassociated is not evidence of no warehouse issue.
        if await association(session, doc_id) is not None:
            reject("Office warehouse binding appeared while reading; refresh")
        doc = await session.get(OfficeDoc, doc_id, populate_existing=True)
        if doc is None or snapshot_row(doc) != initial_document:
            reject("Unassociated Office document changed while reading; refresh")
        if await authorize_doc(core, session, doc, user, permission) != (actor, revision):
            reject("Office warehouse access changed; refresh")
        return doc, None
    exact = ExactInvoiceIdentity.model_validate(frozen["exact_invoice"]).model_dump()
    await core.services.accounting.source_member(session, exact["organization_id"], user)
    facts = await source_facts(core.services, session, exact, read_only=read_only)
    effective, _ = await current_actor(core, session, user, permission)
    await core.services.sales_source.authorize_shipping_deal(session, facts["deal_id"], effective)
    progress = await collect_progress(core.services, session, exact["organization_id"], facts)
    doc = await session.scalar(select(OfficeDoc).where(OfficeDoc.id == doc_id).with_for_update()
        .execution_options(populate_existing=True))
    if doc is None:
        reject("Office warehouse document disappeared")
    if await authorize_doc(core, session, doc, user, permission) != (actor, revision):
        reject("Office warehouse access changed while waiting; refresh")
    effective, final_actor = await current_actor(core, session, user, permission)
    if final_actor != actor:
        reject("Office warehouse principal changed while waiting; refresh")
    await core.services.sales_source.authorize_shipping_deal(session, facts["deal_id"], effective)
    if await verify_office(session, core.services, doc, frozen) != exact or progress["exact_invoice"] != exact:
        reject("Office warehouse invoice attribution changed")
    return doc, progress


def response_body(doc, progress, *, principal, can_reconcile):
    return {"office_document_id": doc.id, "document_stage": doc.stage, "wms_ref": doc.wms_ref,
            "state": "unassociated" if progress is None else "observed", "progress": progress,
            "principal": principal, "can_reconcile": can_reconcile}


@router.get("/docs/{doc_id}/warehouse-progress")
async def read_progress(doc_id: int, response: Response, session=Depends(transaction),
                        core=Depends(get_core), user=Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    with session.no_autoflush:
        doc, progress = await addressed(core, session, user, doc_id, "office.doc.read", read_only=True)
        effective, principal = await current_actor(core, session, user, "office.doc.read")
        return response_body(doc, progress, principal=principal,
            can_reconcile=progress is not None and has_permission(core, effective, "office.stage.move"))


@router.post("/docs/{doc_id}/warehouse-progress/reconcile")
async def reconcile_progress(doc_id: int, response: Response, session=Depends(transaction),
                             core=Depends(get_core), user=Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    with session.no_autoflush:
        doc, progress = await addressed(core, session, user, doc_id, "office.stage.move")
        if progress is None:
            reject("A persisted exact invoice association is required")
        changes = values(doc, progress)
        for name, value in changes.items():
            setattr(doc, name, value)
        _, principal = await current_actor(core, session, user, "office.stage.move")
        result = response_body(doc, progress, principal=principal, can_reconcile=True)
    await session.commit()
    return result


async def on_warehouse_fact(payload, ctx, *, remainder=False):
    org, document = payload.get("organization_id"), payload.get("document_id")
    if any(type(value) is not int or value <= 0 for value in (org, document)):
        reject("A positive saved warehouse organization and invoice are required")
    services, session = ctx.services, ctx.session
    with session.no_autoflush:
        if await services.sales_source.invoice_organization(session, document) != org:
            reject("Warehouse event invoice belongs to another organization")
        await services.accounting.lock_event_organization(session, org)
        if await services.sales_source.invoice_organization(session, document) != org:
            reject("Warehouse event invoice ownership changed while waiting")
        try:
            facts = await services.sales_source.invoice_reservation(session, document)
        except ValueError as exc:
            raise HTTPException(409, "Warehouse event source requires reconciliation") from exc
        if facts["organization_id"] != org:
            reject("Warehouse event invoice ownership changed while waiting")
        exact = ExactInvoiceIdentity(organization_id=org, document_id=document,
            expected_version=facts["version"], expected_content_sha256=facts["content_sha256"]).model_dump()
        rows = list(await session.scalars(select(OfficeInvoiceAssociation).where(
            OfficeInvoiceAssociation.organization_id == org).order_by(OfficeInvoiceAssociation.office_doc_id)
            .execution_options(populate_existing=True)))
        frozen = {row.office_doc_id: snapshot_row(row) for row in rows if row.exact_invoice == exact}
        if not frozen:
            return
        progress = await collect_progress(services, session, org, facts)
        if progress["exact_invoice"] != exact:
            reject("Warehouse event progress identity changed")
        if remainder:
            anchor_id = payload.get("release_id")
            match = any(row["release_id"] == anchor_id and row["digest"] == payload.get("digest")
                        for row in progress["releases"])
        else:
            anchor_id = payload.get("act_id")
            match = any(row["act_id"] == anchor_id and row["digest"] == payload.get("digest")
                        and row["source_key"] == payload.get("source_key") for row in progress["acts"])
        if type(anchor_id) is not int or anchor_id <= 0 or not match:
            reject("Warehouse event anchor does not match a verified saved receipt")
        documents = list(await session.scalars(select(OfficeDoc).where(OfficeDoc.id.in_(frozen))
            .order_by(OfficeDoc.id).with_for_update().execution_options(populate_existing=True)))
        if {doc.id for doc in documents} != set(frozen):
            reject("Office warehouse source group is incomplete")
        changes = []
        for doc in documents:
            if await verify_office(session, services, doc, frozen[doc.id]) != exact:
                reject("Office warehouse source group changed")
            changes.append((doc, values(doc, progress)))
        for doc, update in changes:
            for name, value in update.items():
                setattr(doc, name, value)


async def on_physical_shipped(payload, ctx):
    await on_warehouse_fact(payload, ctx)


async def on_remainder_released(payload, ctx):
    await on_warehouse_fact(payload, ctx, remainder=True)
