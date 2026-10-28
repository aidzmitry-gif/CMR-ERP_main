"""Actual module wiring and role middleware for the accountant source viewer."""
# ruff: noqa: F811
import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from modules.accounting.models import AccessGrant, Entry, Period
from modules.procurement.receipt_documents import (
    ReceiptContent,
    ReceiptDocument,
    ReceiptPosting,
    ReceiptRevision,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_procurement_receipt_drafts import (
    document,
    ensure_receipt_catalog_sku,
    source_options,
)
from tests.accounting.test_zero_value_output_cost_postgres import run_migration
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


async def test_receipt_save_replays_exact_create_and_edit_postgres(issuance_pg, pg_book):
    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    api.headers["X-User-Roles"] = "director"
    async with factory() as session:
        await ensure_receipt_catalog_sku(session)
        await session.commit()

    path = f"/procurement/organizations/{pg_book[0]}/receipt-documents"
    create = {"key": "pg-durable-create", "document": document()}
    first = await api.post(path, json=create)
    replay = await api.post(path, json=create)
    assert first.status_code == replay.status_code == 201, first.text
    assert replay.json() == first.json()
    assert first.json()["organization_id"] == pg_book[0]

    changed = {**document(), "invoice_reference": "INV1 corrected after unknown response"}
    edit = {"key": "pg-durable-edit", "expected_version": 1, "document": changed}
    edit_path = path + f"/{first.json()['id']}"
    second = await api.put(edit_path, json=edit)
    edit_replay = await api.put(edit_path, json=edit)
    assert second.status_code == edit_replay.status_code == 200, second.text
    assert edit_replay.json() == second.json()
    assert second.json()["organization_id"] == pg_book[0]
    assert second.json()["version"] == 2
    assert second.json()["revisions"][-1]["request_key"] == edit["key"]
    assert second.json()["revisions"][-1]["document"] == ReceiptContent.model_validate(changed).model_dump(mode="json")
    assert (await api.put(edit_path, json={**edit, "document": document()})).status_code == 409

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ReceiptDocument)) == 1
        assert await session.scalar(select(func.count()).select_from(ReceiptRevision)) == 2


async def test_pg_receipt_warehouse_binding_rejects_stale_snapshot_and_keeps_replay(issuance_pg, pg_book):
    from modules.wms.models import WarehouseDirectory

    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    api.headers["X-User-Roles"] = "director"
    async with factory() as session:
        await ensure_receipt_catalog_sku(session)
        warehouse = await session.scalar(select(WarehouseDirectory).where(
            WarehouseDirectory.organization_id == pg_book[0],
            WarehouseDirectory.name == "warehouse1",
        ))
        assert warehouse is not None
        warehouse_id = warehouse.id
        await session.commit()

    base = f"/procurement/organizations/{pg_book[0]}"
    options = await api.get(base + "/receipt-warehouse-options", params={"q": "warehouse1"})
    assert options.status_code == 200, options.text
    assert options.json()["items"] == [{"id": warehouse_id, "name": "warehouse1",
                                        "title": "Synthetic warehouse", "is_active": True}]
    path = base + "/receipt-documents"
    facts = document()
    unbound = {key: value for key, value in facts.items()
               if key not in {"warehouse_id", "warehouse_title"}}
    rejected = await api.post(path, json={"key": "pg-warehouse-unbound", "document": unbound})
    assert rejected.status_code == 422 and "warehouse" in rejected.text.lower()

    create = {"key": "pg-warehouse-bound", "document": facts}
    created = await api.post(path, json=create)
    assert created.status_code == 201, created.text
    receipt_id = created.json()["id"]
    snapshot = created.json()["revisions"][0]["document"]
    assert (snapshot["warehouse_id"], snapshot["warehouse"], snapshot["warehouse_title"]) == (
        warehouse_id, "warehouse1", "Synthetic warehouse",
    )

    async with factory() as session:
        warehouse = await session.get(WarehouseDirectory, warehouse_id)
        warehouse.title = "Renamed warehouse"
        await session.commit()
    replay = await api.post(path, json=create)
    assert replay.status_code == 201 and replay.json()["id"] == receipt_id
    assert replay.json()["revisions"][0]["document"] == snapshot

    preview = await api.post(f"{path}/{receipt_id}/preview", json={
        "expected_version": 1, "posting_date": "2026-09-03", "policy_id": pg_book[1],
        "settlement_account": "60", "vat_account": None, "inventory_accounts": ["41"],
    })
    assert preview.status_code == 409 and "Warehouse directory record changed" in preview.text
    wms_source = await api.get(f"/wms/organizations/{pg_book[0]}/primary-receipts/{receipt_id}/source",
                               params={"expected_version": 1})
    assert wms_source.status_code == 409 and "Warehouse directory record changed" in wms_source.text

    stale_edit = await api.put(f"{path}/{receipt_id}", json={
        "key": "pg-warehouse-stale-edit", "expected_version": 1,
        "document": {**facts, "explanation": "Still using the old warehouse title"},
    })
    assert stale_edit.status_code == 409, stale_edit.text
    rebound = await api.put(f"{path}/{receipt_id}", json={
        "key": "pg-warehouse-rebind", "expected_version": 1,
        "document": {**facts, "warehouse_title": "Renamed warehouse",
                     "explanation": "Rebound to current warehouse revision"},
    })
    assert rebound.status_code == 200, rebound.text
    assert rebound.json()["version"] == 2
    assert rebound.json()["revisions"][1]["document"]["warehouse_id"] == warehouse_id
    assert rebound.json()["revisions"][1]["document"]["warehouse_title"] == "Renamed warehouse"

    async with factory() as session:
        revisions = (await session.scalars(select(ReceiptRevision).where(
            ReceiptRevision.receipt_id == receipt_id,
        ).order_by(ReceiptRevision.version))).all()
        assert [revision.document["warehouse_title"] for revision in revisions] == [
            "Synthetic warehouse", "Renamed warehouse",
        ]
        assert await session.scalar(select(func.count()).select_from(ReceiptPosting).where(
            ReceiptPosting.receipt_id == receipt_id,
        )) == 0


async def test_pg_posted_receipt_correction_draft_keeps_exact_source_and_blocks_posting(issuance_pg, pg_book):
    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    api.headers["X-User-Roles"] = "director"
    async with factory() as session:
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.account', 'id'), "
            "(SELECT max(id) FROM accounting.account))"))
        path, options = await source_options(api, session, pg_book)
    preview = await api.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    confirmed = await api.post(path + "/confirm", json={**options, "digest": preview.json()["digest"]})
    assert confirmed.status_code == 201, confirmed.text
    original_id = int(path.rsplit("/", 1)[1])
    correction_path = path + "/correction-drafts"
    command = {"key": str(uuid4()), "expected_version": 1,
               "expected_entry_id": confirmed.json()["entry_id"]}
    created, concurrent = await asyncio.gather(
        api.post(correction_path, json=command), api.post(correction_path, json=command))
    assert created.status_code == concurrent.status_code == 201, (created.text, concurrent.text)
    initial = created.json()
    assert concurrent.json() == initial
    assert initial["correction_of"] == {"receipt_id": original_id, "version": 1,
                                        "entry_id": confirmed.json()["entry_id"]}
    assert (await api.post(correction_path, json=command)).json() == initial

    second_source = await api.post(path.rsplit("/", 1)[0], json={"key": "pg-second-source", "document": document()})
    assert second_source.status_code == 201, second_source.text
    collision = await api.post(
        f"/procurement/organizations/{pg_book[0]}/receipt-documents/{second_source.json()['id']}/correction-drafts",
        json=command)
    assert collision.status_code == 409

    edited = await api.put(f"/procurement/organizations/{pg_book[0]}/receipt-documents/{initial['id']}", json={
        "key": str(uuid4()), "expected_version": 1,
        "document": {**initial["revisions"][0]["document"], "explanation": "Synthetic correction review"},
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2 and edited.json()["correction_of"] == initial["correction_of"]
    assert (await api.post(correction_path, json=command)).json() == edited.json()
    assert (await api.post(f"/procurement/organizations/{pg_book[0]}/receipt-documents/{initial['id']}/preview",
                           json={**options, "expected_version": 2})).status_code == 409
    wms = await api.get(f"/wms/organizations/{pg_book[0]}/primary-receipts/{initial['id']}/source",
                        params={"expected_version": 2})
    assert wms.status_code == 409 and "Correction draft" in wms.text

    async with factory() as session:
        revision = await session.scalar(select(ReceiptRevision).where(
            ReceiptRevision.receipt_id == initial["id"], ReceiptRevision.version == 1))
        original_revision = await session.scalar(select(ReceiptRevision).where(
            ReceiptRevision.receipt_id == original_id, ReceiptRevision.version == 1))
        assert revision.document == original_revision.document
        with pytest.raises(DBAPIError, match="exact posted source revision"):
            async with session.begin_nested():
                future_id = await session.scalar(text(
                    "SELECT nextval(pg_get_serial_sequence('procurement.receipt_document', 'id'))"
                ))
                session.add(Entry(
                    organization_id=pg_book[0], source=f"procurement:receipt:{future_id}",
                    source_version=1, operation="manual", document_date=date(2026, 9, 3),
                    operation_date=date(2026, 9, 3), posting_date=date(2026, 9, 3),
                    policy_id=pg_book[1], rule_version="manual-v1",
                    explanation="Entry inserted before a future correction draft",
                    opening=False, correction_of=None, digest="c" * 64, actor="tester",
                ))
                await session.flush()
                session.add(ReceiptDocument(
                    id=future_id, organization_id=pg_book[0], source_key=str(uuid4()),
                    current_version=1, status="draft", created_by="tester",
                    correction_of_receipt_id=original_id, correction_of_version=1,
                    correction_of_entry_id=confirmed.json()["entry_id"],
                ))
                await session.flush()
                session.add(ReceiptRevision(
                    receipt_id=future_id, version=1, request_key=None,
                    document=original_revision.document, actor="tester",
                ))
                await session.flush()
                await session.execute(text(
                    "SET CONSTRAINTS procurement.receipt_correction_exact_revision IMMEDIATE"
                ))
        with pytest.raises(DBAPIError, match="separately approved correction workflow"):
            async with session.begin_nested():
                session.add(Entry(
                    organization_id=pg_book[0], source=f"procurement:receipt:{initial['id']}",
                    source_version=1, operation="manual", document_date=date(2026, 9, 3),
                    operation_date=date(2026, 9, 3), posting_date=date(2026, 9, 3),
                    policy_id=pg_book[1], rule_version="manual-v1", explanation="Direct SQL bypass",
                    opening=False, correction_of=None, digest="b" * 64, actor="tester",
                ))
                await session.flush()
        with pytest.raises(DBAPIError, match="separately approved correction workflow"):
            async with session.begin_nested():
                await session.execute(text("""
                    INSERT INTO procurement.receipt_posting
                    (receipt_id, version, entry_id, options, digest, actor)
                    VALUES (:receipt_id, 2, :entry_id, '{}'::json, :digest, 'tester')
                """), {"receipt_id": initial["id"], "entry_id": confirmed.json()["entry_id"],
                      "digest": "a" * 64})
        with pytest.raises(DBAPIError, match="Correction draft cannot be prepared"):
            async with session.begin_nested():
                await session.execute(text("""
                    INSERT INTO wms.primary_receipt_binding
                    (receipt_id, organization_id, request_key, source_receipt_id, source_version,
                     command, source_snapshot, line_bindings, actor)
                    VALUES (999999, :org_id, :request_key, :source_id, 2, '{}'::json,
                            '{}'::json, '[]'::json, 'tester')
                """), {"org_id": pg_book[0], "request_key": str(uuid4()), "source_id": initial["id"]})
        assert await session.scalar(select(func.count()).select_from(ReceiptPosting)) == 1
        assert await session.scalar(select(func.count()).select_from(Entry)) == 1
        with pytest.raises(DBAPIError, match="Cannot downgrade while receipt correction drafts exist"):
            await run_migration(session, "0190_procurement_receipt_correction_drafts.py", "downgrade")
        await session.rollback()


@pytest.mark.parametrize("accounting_pg_revision", ["0190"], indirect=True)
async def test_pg_receipt_correction_migration_empty_roundtrip(pg_factory):
    async with pg_factory() as session:
        assert await session.scalar(text(
            "SELECT to_regprocedure('accounting.reject_correction_receipt_entry()') IS NOT NULL"
        ))
        await run_migration(session, "0190_procurement_receipt_correction_drafts.py", "downgrade")
        assert not await session.scalar(text(
            "SELECT to_regprocedure('accounting.reject_correction_receipt_entry()') IS NOT NULL"
        ))
        assert await session.scalar(text("""
            SELECT count(*) FROM information_schema.columns
            WHERE table_schema='procurement' AND table_name='receipt_document'
              AND column_name LIKE 'correction_of_%'
        """)) == 0
        await run_migration(session, "0190_procurement_receipt_correction_drafts.py", "upgrade")
        assert await session.scalar(text(
            "SELECT to_regprocedure('accounting.reject_correction_receipt_entry()') IS NOT NULL"
        ))
        await session.commit()


async def test_finance_reads_posted_primary_without_procurement_access(issuance_pg, pg_book):
    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    async with factory() as session:
        # pg_book copies explicit IDs from SQLite; advance only this test DB sequence.
        await session.execute(text("SELECT setval(pg_get_serial_sequence('accounting.account', 'id'), (SELECT max(id) FROM accounting.account))"))
        path, options = await source_options(api, session, pg_book, unit="кг")
    receipt_id = int(path.rsplit("/", 1)[1])
    preview = await api.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    api.headers["X-User-Roles"] = "finance"
    preview_url = f"/accounting/organizations/{pg_book[0]}/receipts/{receipt_id}/preview"
    prepared = await api.post(preview_url, json=options)
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["lines"] == preview.json()["lines"]
    assert prepared.json()["digest"] == preview.json()["digest"]
    assert prepared.json()["posted"] is False
    assert prepared.json()["source_version"] == options["expected_version"]
    assert (await api.post(preview_url, json={**options, "expected_version": 999})).status_code == 409
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == 0
        assert await session.scalar(select(func.count()).select_from(ReceiptPosting)) == 0
    confirmation_url = preview_url.removesuffix("/preview") + "/confirm"
    command = {**options, "digest": preview.json()["digest"]}
    rejected = await api.post(confirmation_url, json={**command, "digest": "0" * 64})
    assert rejected.status_code == 409
    async with factory() as session:
        period = await session.scalar(select(Period).where(Period.organization_id == pg_book[0], Period.month == "2026-09"))
        generation_before = period.generation
    close_url = f"/accounting/organizations/{pg_book[0]}/periods/2026-09/close"
    closing = {"expected_generation": generation_before, "evidence": {key: "Synthetic checks only" for key in service.CLOSE_STEPS}}
    blocked_close = await api.post(close_url, json=closing)
    assert blocked_close.status_code == 422 and "Unposted primary documents" in blocked_close.text
    confirmed, concurrent, racing_close = await asyncio.gather(
        api.post(confirmation_url, json=command), api.post(confirmation_url, json=command), api.post(close_url, json=closing))
    assert confirmed.status_code == 201, confirmed.text
    assert concurrent.status_code == 201, concurrent.text
    assert concurrent.json() == confirmed.json()
    assert racing_close.status_code == 422
    assert "Unposted primary documents" in racing_close.text or "Data changed after review" in racing_close.text
    assert (await api.post(confirmation_url, json=command)).json() == confirmed.json()
    assert (await api.post(confirmation_url, json={**command, "posting_date": "2026-09-04"})).status_code == 409
    entry_id = confirmed.json()["entry_id"]
    source_url = f"/accounting/organizations/{pg_book[0]}/receipts/{receipt_id}/source"
    posted_source = await api.get(source_url)
    assert posted_source.status_code == 200, posted_source.text
    assert posted_source.json()["document"]["items"][0]["unit"] == "кг"
    assert posted_source.json()["document"]["items"][0]["quantity"] == "2.000001"
    async with factory() as session:
        period = await session.scalar(select(Period).where(Period.organization_id == pg_book[0], Period.month == "2026-09"))
        assert not period.closed and period.generation > generation_before
        closing["expected_generation"] = period.generation
    closed = await api.post(close_url, json=closing)
    assert closed.status_code == 200, closed.text
    # A new primary cannot enter an already closed month; historical source stays readable.
    api.headers["X-User-Roles"] = "director"
    late = await api.post(path.rsplit("/", 1)[0], json={"key": "late-closed-month", "document": document()})
    assert late.status_code in {409, 422}, late.text
    assert "closed" in late.text.lower()

    async with factory() as session:
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == pg_book[0]).values(role="accountant"))
        await session.commit()
        counts = [await session.scalar(select(func.count()).select_from(model))
                  for model in (Entry, ReceiptDocument, ReceiptRevision, ReceiptPosting)]
        assert counts == [1, 1, 1, 1]
        revision = await session.scalar(select(ReceiptRevision).where(ReceiptRevision.receipt_id == receipt_id))
        expected_document = revision.document

    api.headers["X-User-Roles"] = "finance"
    assert (await api.get(path.rsplit("/", 1)[0])).status_code == 403
    response = await api.get(source_url)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["document"] == expected_document
    assert response.json()["status"] == "posted"
    assert response.json()["entry_id"] == entry_id
    assert (await api.get(source_url.replace(f"/organizations/{pg_book[0]}/", "/organizations/999999/"))).status_code == 403
    assert (await api.get(source_url.replace(f"/receipts/{receipt_id}/", "/receipts/999999/"))).status_code == 404

    async with factory() as session:
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == pg_book[0]).values(role="reader"))
        await session.commit()
    assert (await api.get(source_url)).status_code == 200
    assert (await api.post(preview_url, json=options)).status_code == 403
    assert (await api.post(confirmation_url, json=command)).status_code == 403
    assert (await api.post(f"/accounting/organizations/{pg_book[0]}/entries", json={})).status_code == 403
    api.headers["X-User"] = "unassigned"
    assert (await api.get(source_url)).status_code == 403
    async with factory() as session:
        assert [await session.scalar(select(func.count()).select_from(model))
                for model in (Entry, ReceiptDocument, ReceiptRevision, ReceiptPosting)] == counts
