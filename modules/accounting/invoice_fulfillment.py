"""Ledger evidence for invoice cancellation; never an external-coverage claim."""
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import or_, select

from modules.accounting.models import Entry, Inbox, Line, SourceControl


async def snapshot(session, organization_id, document_id):
    """Caller authorizes and holds the organization lock through final commit.

    Discover all exact source/settlement matches, including manual entries and
    both directions of correction chains. A zero net balance cannot erase them.
    Consumers must separately establish legacy coverage and classify evidence;
    this function cannot issue a no-shipment certificate.
    """
    if type(document_id) is not int or document_id <= 0:
        raise HTTPException(422, "An exact positive invoice ID is required")
    target = f"sales:document:{document_id}"
    matched = select(Line.entry_id).where(
        Line.dimensions["settlement_document"].as_string() == target,
    )
    rows = (await session.scalars(select(Entry).where(
        Entry.organization_id == organization_id,
        or_(Entry.source == target, Entry.id.in_(matched)),
    ).order_by(Entry.id).execution_options(populate_existing=True))).all()
    entries = {row.id: row for row in rows}
    missing = set()
    frontier = set(entries)
    while frontier:
        parents = {entries[key].correction_of for key in frontier
                   if entries[key].correction_of is not None} - entries.keys()
        related = (await session.scalars(select(Entry).where(
            Entry.organization_id == organization_id,
            or_(Entry.id.in_(parents), Entry.correction_of.in_(frontier)),
        ).order_by(Entry.id).execution_options(populate_existing=True))).all()
        missing.update(parents - {row.id for row in related})
        frontier = {row.id for row in related} - entries.keys()
        entries.update({row.id: row for row in related})
    lines = (await session.scalars(select(Line).where(
        Line.entry_id.in_(entries),
    ).order_by(Line.entry_id, Line.id).execution_options(populate_existing=True))).all() if entries else []
    # Preserve actual persisted fields, not just the stored posting hash: this
    # also invalidates a review if legacy SQL changed an analytical dimension.
    def fields(row):
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    controls = (await session.scalars(select(SourceControl).where(
        SourceControl.organization_id == organization_id,
        or_(SourceControl.source == target, SourceControl.entry_id.in_(entries)),
    ).order_by(SourceControl.id).execution_options(populate_existing=True))).all()
    queued = (await session.scalars(select(Inbox).where(
        Inbox.organization_id == organization_id,
    ).order_by(Inbox.id).execution_options(populate_existing=True))).all()

    def relevant_queue(row):
        if row.entry_id in entries:
            return True
        payload = row.payload
        if not isinstance(payload, dict):
            return False
        if payload.get("source") == target:
            return True
        correction = payload.get("correction_of")
        if type(correction) is int and correction > 0 and correction in entries:
            return True
        items = payload.get("lines")
        return isinstance(items, list) and any(
            isinstance(item, dict) and isinstance(item.get("dimensions"), dict)
            and item["dimensions"].get("settlement_document") == target for item in items
        )

    facts = {"organization_id": organization_id, "document_id": document_id,
             "scope": "accounting_issue", "coverage_complete": False,
             "coverage_basis": "exact_local_ledger_references",
             "missing_correction_ids": sorted(missing),
             "source_controls": [fields(row) for row in controls],
             "inbox": [fields(row) for row in queued if relevant_queue(row)],
             "entries": [fields(entries[key]) for key in sorted(entries)],
             "lines": [fields(line) for line in lines]}
    encoded = json.dumps(facts, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str)
    return {"facts": json.loads(encoded),
            "digest": hashlib.sha256(encoded.encode()).hexdigest()}
