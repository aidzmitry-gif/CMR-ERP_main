"""OfficeDoc scope is persisted assignment or verified linked deal, never owner text."""
from fastapi import HTTPException
from sqlalchemy import select

from core.domain.models import User
from core.services.auth import has_permission, resolve_effective_oidc_user
from modules.office.models import OfficeDoc
from modules.office.shipping_associations import OfficeInvoiceAssociation, ShippingReviewAssignment


async def current_actor(core, session, user, permission):
    if user is None or (not user.keycloak_user_id and (
        core.services.config.auth_mode != "dev" or user.username in {"", "anonymous"}
    )):
        raise HTTPException(403, "Identified actor required")
    identity = User.keycloak_user_id == user.keycloak_user_id if user.keycloak_user_id else User.username == user.username
    linked = await session.scalar(select(User).where(identity).execution_options(populate_existing=True))
    if linked is not None and linked.status != "active":
        raise HTTPException(403, "Inactive actor")
    effective = await resolve_effective_oidc_user(user, session)
    if not has_permission(core, effective, permission):
        raise HTTPException(403, f"Permission required: {permission}")
    return effective, effective.keycloak_user_id or effective.username


async def latest_assignment(session, doc_id):
    return await session.scalar(select(ShippingReviewAssignment).where(ShippingReviewAssignment.office_doc_id == doc_id)
        .order_by(ShippingReviewAssignment.revision.desc()).limit(1).execution_options(populate_existing=True))


async def authorize_doc(core, session, doc, user, permission, *, reviewer=False):
    user, actor = await current_actor(core, session, user, permission)
    association = await session.scalar(select(OfficeInvoiceAssociation).where(
        OfficeInvoiceAssociation.office_doc_id == doc.id).execution_options(populate_existing=True))
    if association is not None:
        # Read current grants without taking organization locks here: this
        # helper also runs after OfficeDoc locks and across multi-org lists.
        organizations = await core.services.accounting.source_organizations(session, user)
        if association.organization_id not in {row["id"] for row in organizations}:
            raise HTTPException(404, "Office shipping document not found")
    assignment = await latest_assignment(session, doc.id)
    revision = assignment.revision if assignment else 0
    if assignment is not None and assignment.subject == actor:
        return actor, revision
    if reviewer:
        # Confirmation always requires a current explicit reviewer, even chief.
        raise HTTPException(404, "Office shipping document not found")
    if has_permission(core, user, "office.shipping.review.assign"):
        return actor, revision
    if doc.deal_id is not None:
        try:
            await core.services.sales_source.authorize_shipping_deal(session, doc.deal_id, user)
            return actor, revision
        except HTTPException as exc:
            if exc.status_code not in {403, 404}:
                raise
    raise HTTPException(404, "Office shipping document not found")


async def locked_doc(core, session, doc_id, user, permission):
    # Discovery without locks; no unknown-source writer acquires org after doc.
    assoc = await session.scalar(select(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.office_doc_id == doc_id))
    if assoc is not None:
        await core.services.accounting.source_member(session, assoc.organization_id, user)
    doc = await session.scalar(select(OfficeDoc).where(OfficeDoc.id == doc_id)
        .with_for_update().execution_options(populate_existing=True))
    if doc is None:
        raise HTTPException(404, "Office document not found")
    current = await session.scalar(select(OfficeInvoiceAssociation).where(OfficeInvoiceAssociation.office_doc_id == doc_id)
        .execution_options(populate_existing=True))
    if (current.id if current else None) != (assoc.id if assoc else None):
        raise HTTPException(409, "Office ownership changed while waiting; retry")
    await authorize_doc(core, session, doc, user, permission)
    return doc


async def visible_docs(core, session, user):
    await current_actor(core, session, user, "office.doc.read")
    rows = list(await session.scalars(select(OfficeDoc).order_by(OfficeDoc.id.desc())))
    result = []
    for row in rows:
        try:
            await authorize_doc(core, session, row, user, "office.doc.read")
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
        result.append(row)
    return result


async def assign_reviewer(core, session, doc_id, user, *, subject, expected_revision, evidence):
    # Only the OfficeDoc lock: bind takes this same lock after org/Sales locks.
    doc = await session.scalar(select(OfficeDoc).where(OfficeDoc.id == doc_id)
        .with_for_update().execution_options(populate_existing=True))
    if doc is None:
        raise HTTPException(404, "Office document not found")
    permission = "office.shipping.review.assign" if subject else "office.shipping.review.revoke"
    _, actor = await current_actor(core, session, user, permission)
    previous = await latest_assignment(session, doc_id)
    revision = previous.revision if previous else 0
    if expected_revision != revision:
        raise HTTPException(409, "Reviewer assignment changed")
    if not evidence.strip():
        raise HTTPException(422, "Reviewer assignment evidence is required")
    if subject:
        # Persist a real stable subject. Username lookup is allowed only in dev.
        identity = User.keycloak_user_id == subject if core.services.config.auth_mode != "dev" else (
            (User.keycloak_user_id == subject) | ((User.keycloak_user_id.is_(None)) & (User.username == subject)))
        target = await session.scalar(select(User).where(identity).execution_options(populate_existing=True))
        if target is None or target.status != "active":
            raise HTTPException(422, "Reviewer must be an active registered identity")
    row = ShippingReviewAssignment(office_doc_id=doc_id, revision=revision + 1, subject=subject,
        evidence=evidence, actor=actor)
    session.add(row)
    await session.flush()
    return {"document_id": doc_id, "assignment_revision": row.revision, "subject": row.subject}
