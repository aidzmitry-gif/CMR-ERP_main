"""Draft concurrency and immutable versions on the proposed PostgreSQL schema."""
# ruff: noqa: F811
import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service, shipment_drafts
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_drafts import payload
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


async def test_concurrent_draft_writers_preserve_versions_and_sql_prevents_changes(physical_pg):
    factory, org, act, _ = await prepare_accounting(physical_pg)
    source = f"wms:physical-shipment:{org}:{act['source_key']}"

    async def write():
        async with factory() as session:
            await service.lock_organization(session, org)
            try:
                row = await shipment_drafts.save(session, org, source, shipment_drafts.DraftInput(
                    request_key=uuid4(), expected_revision=0, payload=payload()), "allocator")
                revision = row.revision
                await session.commit()
                return revision
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code

    assert sorted(await asyncio.gather(write(), write())) == [1, 409]
    for statement in ["UPDATE accounting.shipment_preparation_draft SET payload='{}'",
                      "DELETE FROM accounting.shipment_preparation_draft",
                      "TRUNCATE accounting.shipment_preparation_draft"]:
        async with factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement))
            await session.rollback()
