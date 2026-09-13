import asyncio

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.runtime.app import create_app
from modules.wms.models import Receipt, StockMovement
from modules.wms.primary_receipts import PrimaryReceiptBinding
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401
from tests.test_wms_primary_receipts import command, setup


async def test_concurrent_partial_receipts_serialize_limit_and_exact_replay(issuance_pg, monkeypatch):  # noqa: F811
    api, factory = issuance_pg
    services = create_app().state.core.services
    async with factory() as session:
        org, source, _, _, _ = await setup(api, session, services)
    # A damaged gateway projection must fail on the FIRST binding, independently
    # of duplicate keys or comparison with an earlier saved binding.
    from modules.procurement.source_gateway import ProcurementSourceService

    original_source = ProcurementSourceService.warehouse_receipt_source

    async def damaged_projection(self, *args, **kwargs):
        result = await original_source(self, *args, **kwargs)
        result["lines"][0]["quantity"] = "999.00"
        return result

    with monkeypatch.context() as patch:
        patch.setattr(ProcurementSourceService, "warehouse_receipt_source", damaged_projection)
        refused = await api.post(f"/wms/organizations/{org}/primary-receipts/{source}",
                                 json=command().model_dump(mode="json"))
        assert refused.status_code == 409, refused.text
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(PrimaryReceiptBinding)) == 0
        assert await session.scalar(select(func.count()).select_from(Receipt)) == 0
    first, second = command(), command()

    async def prepare(cmd):
        response = await api.post(f"/wms/organizations/{org}/primary-receipts/{source}",
                                  json=cmd.model_dump(mode="json"))
        assert response.status_code in {201, 409}, response.text
        return response.json()["receipt_id"] if response.status_code == 201 else response.json()["detail"]

    results = await asyncio.gather(prepare(first), prepare(second))
    assert sum(type(result) is int for result in results) == 1
    assert "Physical receipts exceed the primary line quantity" in results
    winner = first if type(results[0]) is int else second
    replay = await asyncio.gather(prepare(winner), prepare(winner))
    assert replay[0] == replay[1] and type(replay[0]) is int
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(PrimaryReceiptBinding)) == 1
        assert await session.scalar(select(func.count()).select_from(Receipt)) == 1
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 0
        for statement in (
            "UPDATE wms.primary_receipt_binding SET actor = 'changed'",
            "DELETE FROM wms.primary_receipt_binding",
            "TRUNCATE wms.primary_receipt_binding",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                async with session.begin_nested():
                    await session.execute(text(statement))
        assert await session.scalar(select(func.count()).select_from(PrimaryReceiptBinding)) == 1
        # BEFORE INSERT must validate source facts even when bypassing the command.
        for snapshot, owner, reason in (
            ("jsonb_set(source_snapshot::jsonb, '{document,invoice_reference}', '\"forged\"'::jsonb)", "organization_id", "snapshot or command mismatch"),
            ("source_snapshot", "organization_id + 100000", "organization does not exist"),
            ("jsonb_set(source_snapshot::jsonb, '{lines,0,quantity}', '\"999.00\"'::jsonb)", "organization_id", "source projection mismatch"),
            ("jsonb_set(source_snapshot::jsonb, '{lines,0,unit}', '\"forged\"'::jsonb)", "organization_id", "source projection mismatch"),
            ("jsonb_set(source_snapshot::jsonb, '{lines,0,source_line}', '\"forged\"'::jsonb)", "organization_id", "source projection mismatch"),
            ("jsonb_set(source_snapshot::jsonb, '{lines,0,position}', '2'::jsonb)", "organization_id", "source projection mismatch"),
            ("jsonb_set(source_snapshot::jsonb, '{lines}', '[]'::jsonb)", "organization_id", "source projection mismatch"),
        ):
            with pytest.raises(DBAPIError, match=reason):
                async with session.begin_nested():
                    await session.execute(text(f"""
                        INSERT INTO wms.primary_receipt_binding
                        (receipt_id, organization_id, request_key, source_receipt_id, source_version,
                         command, source_snapshot, line_bindings, actor)
                        SELECT receipt_id, {owner}, request_key, source_receipt_id, source_version,
                               command, {snapshot}, line_bindings, actor
                        FROM wms.primary_receipt_binding
                    """))
        for statement, reason in (
            ("UPDATE wms.receipt_line SET expected_qty = 2", "immutable"),
            ("UPDATE wms.receipt_line SET batch_ref = 'forged'", "immutable"),
            ("DELETE FROM wms.receipt_line", "immutable"),
            # production_arrival references receipt_line; PostgreSQL may reject
            # the truncate at the FK before the immutable guard is reached.
            ("TRUNCATE wms.receipt_line", "immutable|referenced"),
            ("UPDATE wms.receipt SET warehouse = 'forged'", "immutable"),
            ("DELETE FROM wms.receipt", "immutable"),
            ("INSERT INTO wms.receipt_line (receipt_id, sku_code, expected_qty) SELECT id, 'WAREHOUSE-SKU', 1 FROM wms.receipt", "immutable"),
        ):
            with pytest.raises(DBAPIError, match=reason):
                async with session.begin_nested():
                    await session.execute(text(statement))
        # QC quantities remain editable until acceptance.
        with pytest.raises(DBAPIError, match="complete explicit QC"):
            async with session.begin_nested():
                await session.execute(text("UPDATE wms.receipt SET status = 'accepted'"))
                await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await session.execute(text("UPDATE wms.receipt_line SET accepted_qty = 1.00, rejected_qty = 0.25, reject_reason = 'Synthetic defect'"))
        await session.commit()
        with pytest.raises(DBAPIError, match="arrival movements do not match"):
            async with session.begin_nested():
                await session.execute(text("UPDATE wms.receipt SET status = 'accepted'"))
                await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await session.rollback()
    accepted = await api.post(f"/wms/receipts/{replay[0]}/accept")
    assert accepted.status_code == 200, accepted.text
    assert (await api.post(f"/wms/receipts/{replay[0]}/accept")).status_code == 200
    report = await api.get(f"/accounting/organizations/{org}/receipts/{source}/warehouse-reconciliation",
                           headers={"X-User-Roles": "finance"})
    assert report.status_code == 200, report.text
    assert report.headers["cache-control"] == "private, no-store"
    assert report.json()["rows"][0]["accepted"] == "1.00"
    assert report.json()["rows"][0]["rejected"] == "0.25"
    assert report.json()["rows"][0]["unallocated"] == "0.75"
    async with factory() as session:
        for statement in (
            "UPDATE wms.receipt_line SET accepted_qty = 0.50",
            "UPDATE wms.receipt_line SET location_id = NULL",
            "UPDATE wms.receipt SET status = 'pending_qc'",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                async with session.begin_nested():
                    await session.execute(text(statement))
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 1
        assert str(await session.scalar(select(StockMovement.qty))) == "1.00"
        for statement in (
            "UPDATE wms.stock_movement SET qty = 0.50",
            "DELETE FROM wms.stock_movement",
            "UPDATE wms.stock_movement SET doc_ref = 'unlinked'",
        ):
            with pytest.raises(DBAPIError, match="arrival movements do not match"):
                async with session.begin_nested():
                    await session.execute(text(statement))
                    await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert str(await session.scalar(select(StockMovement.qty))) == "1.00"
