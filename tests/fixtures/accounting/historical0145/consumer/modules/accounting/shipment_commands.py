"""Atomic whole-act posting shared by the authorized HTTP confirmation endpoint.

Caller supplies an authorized, verified WMS act_result and owns commit/rollback.
No caller-supplied warehouse receipt is accepted by a public endpoint.
"""

import hashlib
import json

from sqlalchemy import or_, select

from modules.accounting import service, shipment_preview
from modules.accounting.models import Entry, Line, ShipmentAccountingReceipt, SourceControl
from modules.accounting.schemas import LineInput, PostingInput


async def verify_saved(session, saved):
    """Replay checks recorded pages without re-costing already consumed stock."""
    basis = {
        "act_digest": saved.act_digest,
        "inputs": saved.command,
        "costs": saved.snapshot["costs"],
        "mapping": saved.snapshot["mapping"],
        "commercial": saved.snapshot["commercial"],
    }
    checksum = hashlib.sha256(shipment_preview.canonical(basis).encode()).hexdigest()
    if checksum != saved.basis_digest or saved.snapshot["act"]["digest"] != saved.act_digest:
        raise service.AccountingError("Shipment receipt calculation evidence changed")
    pages = saved.snapshot["pages"]
    if not pages or pages[0]["entry_id"] != saved.anchor_entry_id:
        raise service.AccountingError("Shipment receipt has no matching anchor")
    ids = (
        await session.scalars(
            select(Entry.id).where(
                Entry.organization_id == saved.organization_id,
                or_(Entry.source == saved.source, Entry.source.startswith(saved.source + ":part:")),
            )
        )
    ).all()
    if len(ids) != len(pages) or set(ids) != {page["entry_id"] for page in pages}:
        raise service.AccountingError("Shipment receipt has incomplete or extra pages")
    for index, page in enumerate(pages):
        entry = await session.get(Entry, page["entry_id"])
        expected_source = saved.source if index == 0 else f"{saved.source}:part:{index + 1}"
        if (
            entry is None
            or entry.organization_id != saved.organization_id
            or entry.source != expected_source
            or entry.digest != page["digest"]
        ):
            raise service.AccountingError("Shipment receipt entry identity changed")
        lines = (
            await session.scalars(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))
        ).all()
        actual = PostingInput(
            **{name: getattr(entry, name) for name in PostingInput.model_fields if name != "lines"},
            lines=[
                LineInput(
                    account=line.account_code,
                    **{
                        name: getattr(line, name)
                        for name in LineInput.model_fields
                        if name != "account"
                    },
                )
                for line in lines
            ],
        )
        expected = PostingInput(**page["posting"])
        # SQL NUMERIC pads trailing zeros; Decimal comparison preserves exact values.
        if (
            actual.model_dump() != expected.model_dump()
            or service.digest(expected) != page["digest"]
        ):
            raise service.AccountingError("Shipment receipt posting content changed")
    control = await session.scalar(
        select(SourceControl).where(
            SourceControl.organization_id == saved.organization_id,
            SourceControl.source == saved.source,
        )
    )
    if control is None or control.version != 1 or control.entry_id != saved.anchor_entry_id:
        raise service.AccountingError("Shipment receipt completeness link changed")
    return saved


async def confirm(session, org_id, receipt, data, expected_basis_digest, actor, event_bus=None, *, procurement=None):
    """Post a verified act; the authorized caller owns the transaction boundary."""
    await service.lock_organization(session, org_id)
    source = f"wms:physical-shipment:{org_id}:{receipt['source_key']}"
    if (
        receipt["snapshot"]["organization_id"] != org_id
        or receipt["digest"] != data.expected_act_digest
    ):
        raise service.AccountingError("Physical shipment identity changed")
    command = data.model_dump(mode="json")
    saved = await session.scalar(
        select(ShipmentAccountingReceipt).where(
            ShipmentAccountingReceipt.organization_id == org_id,
            ShipmentAccountingReceipt.source == source,
        )
    )
    if saved is not None:
        if (
            saved.command != command
            or saved.basis_digest != expected_basis_digest
            or saved.act_digest != receipt["digest"]
        ):
            raise service.AccountingError("Shipment already posted with different content")
        return await verify_saved(session, saved)
    plan = await shipment_preview.prepare(session, org_id, receipt, data, procurement=procurement)
    if plan["basis_digest"] != expected_basis_digest:
        raise service.AccountingError("Shipment cost basis changed; preview again")
    # Reject orphan pages rather than adopting earlier, partially posted operations.
    if await session.scalar(
        select(Entry.id).where(
            Entry.organization_id == org_id,
            or_(Entry.source == source, Entry.source.startswith(source + ":part:")),
        )
    ):
        raise service.AccountingError("Shipment already has entries without a complete receipt")
    pages = []
    for page in plan["postings"]:
        entry = await service.post(
            session, org_id, PostingInput(**page["posting"]), actor, event_bus, inventory_sale=True
        )
        pages.append({**page, "entry_id": entry.id})
    saved = ShipmentAccountingReceipt(
        organization_id=org_id,
        source=source,
        act_digest=receipt["digest"],
        command=command,
        basis_digest=expected_basis_digest,
        actor=actor,
        anchor_entry_id=pages[0]["entry_id"],
        snapshot=json.loads(
            json.dumps(
                {
                    "act": receipt,
                    "mapping": plan["mapping"],
                    "costs": plan["costs"],
                    "commercial": plan["commercial"],
                    "pages": pages,
                },
                default=str,
            )
        ),
    )
    session.add(saved)
    control = await session.scalar(
        select(SourceControl).where(
            SourceControl.organization_id == org_id, SourceControl.source == source
        )
    )
    control.entry_id = saved.anchor_entry_id
    service.audit(
        session,
        org_id,
        actor,
        "shipment_posted",
        {
            "source": source,
            "basis_digest": expected_basis_digest,
            "entry_ids": [page["entry_id"] for page in pages],
        },
    )
    await session.flush()
    return saved
