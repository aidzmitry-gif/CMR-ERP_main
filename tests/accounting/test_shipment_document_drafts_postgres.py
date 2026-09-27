"""TN/TTN drafts reuse the PostgreSQL append-only shipment preparation store."""

# ruff: noqa: F811
import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import Counterparty
from modules.accounting import service, shipment_document_draft, shipment_document_drafts
from modules.accounting.models import ShipmentPreparationDraft
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


async def test_concurrent_tn_ttn_saves_create_one_version_and_sql_blocks_mutation(physical_pg):
    factory, organization_id, act, _ = await prepare_accounting(physical_pg)
    package = shipment_document_draft.build(act, "ttn")
    source_key = act["source_key"]
    async with factory() as session:
        recipient = Counterparty(name="Synthetic TN/TTN recipient", unp=None)
        session.add(recipient)
        await session.flush()
        recipient_id = recipient.id
        await session.commit()

    async def write():
        async with factory() as session:
            await service.lock_organization(session, organization_id)
            try:
                data = shipment_document_drafts.ShipmentDocumentDraftInput(
                    kind="ttn",
                    request_key=uuid4(),
                    expected_revision=0,
                    source_digest=act["digest"],
                    fields={
                        "recipient_counterparty_id": recipient_id,
                        "recipient_counterparty_revision": 1,
                    },
                )
                row = await shipment_document_drafts.save(
                    session, organization_id, source_key, package, data, "allocator",
                )
                revision = row.revision
                await session.commit()
                return revision
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code

    assert sorted(await asyncio.gather(write(), write())) == [1, 409]
    source = shipment_document_drafts.source_name(organization_id, source_key, "ttn")
    async with factory() as session:
        rows = (await session.scalars(select(ShipmentPreparationDraft).where(
            ShipmentPreparationDraft.organization_id == organization_id,
            ShipmentPreparationDraft.source == source,
        ))).all()
        assert len(rows) == 1 and rows[0].revision == 1
        assert rows[0].payload["basis"]["can_issue"] is False

    for statement in [
        "UPDATE accounting.shipment_preparation_draft SET payload='{}'",
        "DELETE FROM accounting.shipment_preparation_draft",
        "TRUNCATE accounting.shipment_preparation_draft",
    ]:
        async with factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement))
                await session.commit()
            await session.rollback()
