"""Versioned manual accounting documents before immutable ledger posting."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select

from modules.accounting import service
from modules.accounting.counterparty_snapshot import verified_counterparty
from modules.accounting.models import (
    Entry,
    ManualDocument,
    ManualDocumentRevision,
    ManualDocumentVoid,
    Organization,
    Period,
)
from modules.accounting.schemas import Input, PostingInput


class ManualDocumentCreate(Input):
    key: UUID
    posting: PostingInput


class ManualDocumentEdit(ManualDocumentCreate):
    expected_version: int = Field(gt=0, strict=True)


class ManualDocumentPost(Input):
    key: UUID
    expected_version: int = Field(gt=0, strict=True)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ManualDocumentVoidInput(Input):
    key: UUID
    expected_version: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=1000)


def require_manual(posting: PostingInput, role: str):
    if posting.operation != "manual" or posting.opening or posting.rule_version != "manual-v1":
        raise HTTPException(422, "Only ordinary manual accounting documents may be saved here")
    if posting.correction_of is not None and role != "chief":
        raise HTTPException(403, "Chief accountant access required for a correction")


async def verify_analytic_references(session, posting: PostingInput):
    """New saves cannot carry a free-text or stale counterparty reference."""
    checked = set()
    for line in posting.lines:
        dimensions = line.dimensions
        if not {"counterparty", "counterparty_id", "counterparty_unp", "counterparty_revision"} & dimensions.keys():
            continue
        snapshot = tuple(dimensions.get(key, "") for key in
                         ("counterparty_id", "counterparty", "counterparty_unp", "counterparty_revision"))
        if snapshot not in checked:
            await verified_counterparty(session, dimensions)
            checked.add(snapshot)


async def verify_new_manual_references(session, org_id: int, posting: PostingInput):
    """Preserve exact historical replay while requiring IDs for new manual facts."""
    if posting.operation != "manual":
        return
    existing = await session.scalar(select(Entry.id).where(
        Entry.organization_id == org_id, Entry.source == posting.source,
        Entry.source_version == posting.source_version, Entry.operation == "manual",
    ))
    if existing is None:
        await verify_analytic_references(session, posting)


async def invalidate_closing_review(session, org_id: int, affected_date):
    periods = (await session.scalars(select(Period).where(
        Period.organization_id == org_id,
        Period.month >= affected_date.strftime("%Y-%m"),
    ).execution_options(populate_existing=True))).all()
    for period in periods:
        period.generation += 1
        period.evidence = {}
    organization = await session.get(Organization, org_id)
    organization.generation += 1


async def latest(session, row: ManualDocument):
    revision = await session.scalar(select(ManualDocumentRevision).where(
        ManualDocumentRevision.document_id == row.id,
        ManualDocumentRevision.version == row.version,
    ))
    if revision is None:
        raise service.AccountingError("Manual document has no matching saved revision")
    return revision


def revision_result(row: ManualDocumentRevision):
    return {"version": row.version, "request_key": row.request_key,
            "actor": row.actor, "created_at": row.created_at,
            "digest": row.digest, "posting": row.posting}


def document_result(row: ManualDocument, revisions: list[ManualDocumentRevision], void: ManualDocumentVoid | None):
    return {"id": row.id, "organization_id": row.organization_id,
            "number": f"БС-{row.id}", "source": row.source,
            "posting_date": row.posting_date, "version": row.version,
            "status": "posted" if row.entry_id is not None else "voided" if void else "draft",
            "entry_id": row.entry_id, "created_at": row.created_at,
            "updated_at": row.updated_at,
            "void": ({"reason": void.reason, "actor": void.actor,
                      "created_at": void.created_at} if void else None),
            "revisions": [revision_result(item) for item in revisions]}


async def detail(session, org_id: int, document_id: int):
    row = await session.scalar(select(ManualDocument).where(
        ManualDocument.id == document_id, ManualDocument.organization_id == org_id,
    ))
    if row is None:
        raise HTTPException(404, "Manual accounting document not found in this organization")
    revisions = (await session.scalars(select(ManualDocumentRevision).where(
        ManualDocumentRevision.document_id == row.id,
    ).order_by(ManualDocumentRevision.version))).all()
    if len(revisions) != row.version:
        raise service.AccountingError("Manual document revision history is incomplete")
    void = await session.scalar(select(ManualDocumentVoid).where(ManualDocumentVoid.document_id == row.id))
    return document_result(row, revisions, void)


async def list_documents(session, org_id: int, before_id: int | None = None):
    query = select(ManualDocument).where(ManualDocument.organization_id == org_id)
    if before_id is not None:
        query = query.where(ManualDocument.id < before_id)
    rows = (await session.scalars(query.order_by(ManualDocument.id.desc()).limit(101))).all()
    void_ids = set((await session.scalars(select(ManualDocumentVoid.document_id).where(
        ManualDocumentVoid.document_id.in_([row.id for row in rows]),
    ))).all()) if rows else set()
    return {"organization_id": org_id,
            "items": [{"id": row.id, "number": f"БС-{row.id}", "source": row.source,
                       "posting_date": row.posting_date, "version": row.version,
                       "status": "posted" if row.entry_id is not None else "voided" if row.id in void_ids else "draft",
                       "entry_id": row.entry_id, "updated_at": row.updated_at}
                      for row in rows[:100]],
            "next_before_id": rows[99].id if len(rows) > 100 else None}


async def create(session, org_id: int, data: ManualDocumentCreate, actor: str, role: str):
    require_manual(data.posting, role)
    await service.lock_organization(session, org_id)
    snapshot = data.posting.model_dump(mode="json")
    checksum = service.digest(data.posting)
    existing = await session.scalar(select(ManualDocument).where(
        ManualDocument.organization_id == org_id,
        ManualDocument.create_key == str(data.key),
    ).with_for_update())
    if existing is not None:
        revision = await latest(session, existing)
        if existing.version == 1 and revision.digest == checksum and revision.posting == snapshot:
            return await detail(session, org_id, existing.id)
        raise HTTPException(409, "Manual document creation key identifies different facts")
    posted = await session.scalar(select(Entry.id).where(
        Entry.organization_id == org_id, Entry.source == data.posting.source,
        Entry.source_version == data.posting.source_version, Entry.operation == "manual",
    ))
    if posted is not None:
        raise HTTPException(409, "This manual document source is already posted")
    await verify_analytic_references(session, data.posting)
    await service.preview_posting(session, org_id, data.posting)
    row = ManualDocument(organization_id=org_id, source=data.posting.source,
                         posting_date=data.posting.posting_date, version=1,
                         create_key=str(data.key))
    session.add(row)
    await session.flush()
    session.add(ManualDocumentRevision(document_id=row.id, version=1,
                                       request_key=str(data.key), posting=snapshot,
                                       digest=checksum, actor=actor))
    await session.flush()
    await invalidate_closing_review(session, org_id, row.posting_date)
    service.audit(session, org_id, actor, "manual_document_created",
                  {"document_id": row.id, "version": 1, "digest": checksum})
    return await detail(session, org_id, row.id)


async def edit(session, org_id: int, document_id: int, data: ManualDocumentEdit,
               actor: str, role: str):
    require_manual(data.posting, role)
    await service.lock_organization(session, org_id)
    row = await session.scalar(select(ManualDocument).where(
        ManualDocument.organization_id == org_id, ManualDocument.id == document_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(404, "Manual accounting document not found in this organization")
    snapshot = data.posting.model_dump(mode="json")
    checksum = service.digest(data.posting)
    duplicate = await session.scalar(select(ManualDocumentRevision).where(
        ManualDocumentRevision.document_id == row.id,
        ManualDocumentRevision.request_key == str(data.key),
    ))
    if duplicate is not None:
        if (row.entry_id is None and duplicate.version == row.version
                and duplicate.digest == checksum and duplicate.posting == snapshot
                and data.expected_version == duplicate.version - 1):
            return await detail(session, org_id, row.id)
        raise HTTPException(409, "Manual document edit key identifies another revision")
    if row.entry_id is not None:
        raise HTTPException(409, "Posted manual document cannot be edited")
    if await session.scalar(select(ManualDocumentVoid.id).where(ManualDocumentVoid.document_id == row.id)):
        raise HTTPException(409, "Cancelled manual document cannot be edited")
    if row.version != data.expected_version:
        raise HTTPException(409, "Manual document changed; reload its latest revision")
    posted = await session.scalar(select(Entry.id).where(
        Entry.organization_id == org_id, Entry.source == data.posting.source,
        Entry.source_version == data.posting.source_version, Entry.operation == "manual",
    ))
    if posted is not None:
        raise HTTPException(409, "This manual document source is already posted")
    await verify_analytic_references(session, data.posting)
    await service.preview_posting(session, org_id, data.posting)
    version = row.version + 1
    session.add(ManualDocumentRevision(document_id=row.id, version=version,
                                       request_key=str(data.key), posting=snapshot,
                                       digest=checksum, actor=actor))
    await session.flush()
    old_posting_date = row.posting_date
    row.version = version
    row.source = data.posting.source
    row.posting_date = data.posting.posting_date
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    await invalidate_closing_review(session, org_id, min(old_posting_date, row.posting_date))
    service.audit(session, org_id, actor, "manual_document_edited",
                  {"document_id": row.id, "version": version, "digest": checksum})
    return await detail(session, org_id, row.id)


async def post(session, org_id: int, document_id: int, data: ManualDocumentPost,
               actor: str, role: str, event_bus=None):
    await service.lock_organization(session, org_id)
    row = await session.scalar(select(ManualDocument).where(
        ManualDocument.organization_id == org_id, ManualDocument.id == document_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(404, "Manual accounting document not found in this organization")
    if row.version != data.expected_version:
        raise HTTPException(409, "Manual document changed; review the latest revision")
    revision = await latest(session, row)
    if revision.digest != data.digest:
        raise HTTPException(409, "Manual document differs from the reviewed posting")
    posting = PostingInput.model_validate(revision.posting)
    require_manual(posting, role)
    if row.entry_id is not None:
        if row.post_key == str(data.key) and row.post_digest == data.digest:
            return {"document_id": row.id, "document_version": row.version,
                    "entry_id": row.entry_id, "digest": data.digest}
        raise HTTPException(409, "Manual document was already posted with another command")
    if await session.scalar(select(ManualDocumentVoid.id).where(ManualDocumentVoid.document_id == row.id)):
        raise HTTPException(409, "Cancelled manual document cannot be posted")
    posted = await session.scalar(select(Entry.id).where(
        Entry.organization_id == org_id, Entry.source == posting.source,
        Entry.source_version == posting.source_version, Entry.operation == "manual",
    ))
    if posted is not None:
        raise HTTPException(409, "This manual document source was posted by another document")
    await verify_analytic_references(session, posting)
    entry = await service.post(session, org_id, posting, actor, event_bus)
    row.entry_id = entry.id
    row.post_key = str(data.key)
    row.post_digest = data.digest
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    service.audit(session, org_id, actor, "manual_document_posted",
                  {"document_id": row.id, "version": row.version,
                   "entry_id": entry.id, "digest": data.digest})
    return {"document_id": row.id, "document_version": row.version,
            "entry_id": entry.id, "digest": data.digest}


async def void_document(session, org_id: int, document_id: int,
                        data: ManualDocumentVoidInput, actor: str):
    await service.lock_organization(session, org_id)
    row = await session.scalar(select(ManualDocument).where(
        ManualDocument.organization_id == org_id, ManualDocument.id == document_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(404, "Manual accounting document not found in this organization")
    reason = data.reason.strip()
    if not reason:
        raise HTTPException(422, "Cancellation reason is required")
    previous = await session.scalar(select(ManualDocumentVoid).where(ManualDocumentVoid.document_id == row.id))
    if previous is not None:
        if (previous.request_key == str(data.key) and row.version == data.expected_version
                and previous.reason == reason):
            return await detail(session, org_id, row.id)
        raise HTTPException(409, "Manual document was already cancelled")
    if row.entry_id is not None:
        raise HTTPException(409, "Posted manual document cannot be cancelled")
    if row.version != data.expected_version:
        raise HTTPException(409, "Manual document changed; review the latest revision")
    session.add(ManualDocumentVoid(organization_id=org_id, document_id=row.id,
                                   request_key=str(data.key), reason=reason, actor=actor))
    await session.flush()
    await invalidate_closing_review(session, org_id, row.posting_date)
    service.audit(session, org_id, actor, "manual_document_voided",
                  {"document_id": row.id, "version": row.version, "reason": reason})
    return await detail(session, org_id, row.id)
