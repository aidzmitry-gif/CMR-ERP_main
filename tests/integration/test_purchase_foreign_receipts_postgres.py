"""Native FX ledger and physical receipt boundaries on migrated disposable PG."""

import asyncio
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.reference import Currency
from core.runtime.app import create_app
from core.services.auth import CurrentUser
from modules.accounting import models, purchases, service
from modules.accounting.closing_commands import actual_posting
from modules.procurement.receipt_documents import ReceiptConfirm, ReceiptPosting
from modules.wms.models import Receipt, ReceiptLine, StockMovement
from modules.wms.primary_receipts import PrimaryReceiptBinding
from tests.accounting.conftest import book, db  # noqa: F401
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_procurement_receipt_drafts import ensure_receipt_catalog_sku
from tests.accounting.test_purchase_foreign_receipts import foreign_source
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


@pytest_asyncio.fixture
async def foreign_pg(issuance_pg, pg_book):  # noqa: F811 — pytest fixture injection
    api, factory = issuance_pg
    api.headers.update({"X-User": "tester", "X-User-Roles": "director"})
    org, policy = pg_book
    async with factory() as session:
        await ensure_receipt_catalog_sku(session)
        session.add(Currency(code="USD", title="Synthetic USD"))
        for code, title, quantity in (("41.1", "Synthetic owned goods", True),
                                      ("18", "Synthetic input VAT", False)):
            session.add(models.Account(
                organization_id=org, code=code, title=title, category="asset",
                valid_from=date(2026, 1, 1), required_dimensions=[],
                currency_tracking=False, quantity_tracking=quantity, cash=False,
                normative_ref="Synthetic test only",
            ))
        await session.commit()
    return api, factory, org, policy


async def prepare(foreign_pg, key):
    api, factory, org, policy = foreign_pg
    base = f"/procurement/organizations/{org}/receipt-documents"
    source = await api.post(base, json={"key": key, "document": foreign_source()})
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]
    path = f"{base}/{source_id}"
    options = {"expected_version": 1, "posting_date": "2026-09-03", "policy_id": policy,
               "settlement_account": "60", "vat_account": "18", "inventory_accounts": ["41.1"]}
    preview = await api.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    return source_id, path, {**options, "digest": preview.json()["digest"]}


async def test_pg_fx_native_replay_frozen_reconstruction_and_guards(foreign_pg):
    api, factory, org, _ = foreign_pg
    source_id, path, command = await prepare(foreign_pg, "pg-fx-concurrent")
    assert (await api.post(path + "/confirm", json={**command, "digest": "0" * 64})).status_code == 409
    assert (await api.post(path + "/confirm", json=command, headers={"X-User-Roles": "sales"})).status_code == 403
    assert (await api.post(f"/procurement/organizations/{org+999}/receipt-documents/{source_id}/confirm",
                           json=command)).status_code == 403
    first, second = await asyncio.gather(
        api.post(path + "/confirm", json=command), api.post(path + "/confirm", json=command))
    assert first.status_code == second.status_code == 201, (first.text, second.text)
    entry_id = first.json()["entry_id"]
    assert second.json()["entry_id"] == entry_id
    assert (await api.post(path + "/confirm", json=command)).json()["entry_id"] == entry_id
    assert (await api.post(path + "/confirm", json={**command, "expected_version": 2})).status_code == 409

    source = create_app().state.core.services.procurement_source
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(models.Entry)) == 1
        basis = await source.posted_receipt_basis(session, org, source_id, 1)
        assert service.digest(purchases.purchase_from_receipt_basis(basis)[1]) == command["digest"]
        lines = (await session.scalars(select(models.Line).order_by(models.Line.id))).all()
        assert len(lines) == 3
        inventory, vat, supplier = lines
        assert (inventory.amount, inventory.quantity, inventory.currency) == (Decimal("100"), Decimal("2"), "BYN")
        assert (vat.amount, vat.currency) == (Decimal("20"), "BYN")
        assert inventory.original_amount is None and vat.original_amount is None
        assert (supplier.amount, supplier.currency, supplier.original_amount) == (Decimal("120"), "USD", Decimal("48"))
        assert supplier.rate == Decimal("2.5") and supplier.rate_scale == 1
        assert supplier.rate_date == date(2026, 9, 2)
        assert supplier.rate_source == foreign_source()["foreign_exchange"]["rate_source"]
        assert supplier.dimensions["fx_valuation_basis"] == foreign_source()["foreign_exchange"]["valuation_basis"]
        assert (await session.get(ReceiptPosting, source_id)).digest == command["digest"]
        for statement in (
            "UPDATE procurement.receipt_revision SET document=jsonb_set(document::jsonb, '{foreign_exchange,rate}', '\"9\"'::jsonb)::json",
            "DELETE FROM procurement.receipt_revision",
            "UPDATE procurement.receipt_posting SET digest=repeat('0',64)",
            "DELETE FROM procurement.receipt_posting",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                async with session.begin_nested():
                    await session.execute(text(statement))
        assert await session.scalar(select(func.count()).select_from(models.Entry)) == 1
    # A new session must reconstruct the same frozen valuation after failed SQL.
    async with factory() as session:
        basis = await source.posted_receipt_basis(session, org, source_id, 1)
        rebuilt = purchases.purchase_from_receipt_basis(basis)[1]
        assert basis["entry_id"] == entry_id
        entry = await session.get(models.Entry, entry_id)
        assert (entry.organization_id, entry.source, entry.source_version, entry.actor, entry.digest) == (
            org, f"procurement:receipt:{source_id}", 1, "tester", command["digest"],
        )
        assert (await actual_posting(session, entry)).model_dump() == rebuilt.model_dump()
        marker = await session.get(ReceiptPosting, source_id)
        assert (marker.entry_id, marker.version, marker.digest) == (entry_id, 1, command["digest"])


async def test_pg_fx_late_marker_failure_is_atomic_and_retry_recovers(foreign_pg):
    api, factory, org, _ = foreign_pg
    source_id, path, command = await prepare(foreign_pg, "pg-fx-rollback")
    services = create_app().state.core.services
    async with factory() as session:
        def fail_marker(sync_session, flush_context, instances):
            if any(isinstance(row, ReceiptPosting) and row.receipt_id == source_id for row in sync_session.new):
                raise RuntimeError("Synthetic FX late marker failure")

        event.listen(session.sync_session, "before_flush", fail_marker)
        try:
            with pytest.raises(RuntimeError, match="late marker"):
                async with session.begin_nested():
                    await services.procurement_source.confirm_receipt(
                        session, org, source_id, ReceiptConfirm.model_validate(command),
                        CurrentUser("tester", ["director"]), services.accounting, None,
                    )
        finally:
            event.remove(session.sync_session, "before_flush", fail_marker)
        for model in (models.Entry, models.Line, ReceiptPosting):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        control = await session.scalar(select(models.SourceControl).where(
            models.SourceControl.source == f"procurement:receipt:{source_id}"))
        assert control is not None and control.entry_id is None
        await session.commit()
    confirmed = await api.post(path + "/confirm", json=command)
    assert confirmed.status_code == 201, confirmed.text
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(models.Entry)) == 1
        assert await session.scalar(select(func.count()).select_from(ReceiptPosting)) == 1


async def test_pg_fx_partial_wms_qc_replay_and_reconciliation(foreign_pg):
    api, factory, org, _ = foreign_pg
    source_id, path, posting = await prepare(foreign_pg, "pg-fx-physical")
    confirmed = await api.post(path + "/confirm", json=posting)
    assert confirmed.status_code == 201, confirmed.text
    command = {"request_key": str(uuid4()), "expected_version": 1,
               "warehouse_id": 1, "warehouse": "warehouse1",
               "evidence": "Synthetic explicit source-SKU/warehouse correspondence",
               "lines": [{"position": 1, "sku_code": "sku1", "quantity": "1.25"}]}
    physical_path = f"/wms/organizations/{org}/primary-receipts/{source_id}"
    created = await api.post(physical_path, json=command)
    assert created.status_code == 201, created.text
    receipt_id = created.json()["receipt_id"]
    assert (await api.post(physical_path, json=command)).json()["receipt_id"] == receipt_id
    excess = await api.post(physical_path, json={**command, "request_key": str(uuid4())})
    assert excess.status_code == 409, excess.text
    incomplete = await api.post(f"/wms/receipts/{receipt_id}/accept")
    assert incomplete.status_code in {409, 422} and "QC" in incomplete.text
    async with factory() as session:
        binding = await session.scalar(select(PrimaryReceiptBinding))
        assert binding.source_snapshot["document"]["foreign_exchange"] == foreign_source()["foreign_exchange"]
        assert binding.source_snapshot["document"]["items"][0]["foreign_amounts"] == {"net_amount": "40.00", "vat_amount": "8.00"}
    detail = await api.get(f"/wms/receipts/{receipt_id}")
    assert detail.status_code == 200, detail.text
    qc = await api.post(f"/wms/receipts/{receipt_id}/qc", json={
        "expected_revision": detail.json()["qc_revision"],
        "decisions": [{"line_id": detail.json()["lines"][0]["id"], "accepted_qty": "1.00",
                       "rejected_qty": "0.25", "reject_reason": "Synthetic defect"}],
    })
    assert qc.status_code == 200, qc.text
    accepted = await api.post(f"/wms/receipts/{receipt_id}/accept")
    assert accepted.status_code == 200, accepted.text
    assert (await api.post(f"/wms/receipts/{receipt_id}/accept")).status_code == 200
    report = await api.get(f"/accounting/organizations/{org}/receipts/{source_id}/warehouse-reconciliation")
    assert report.status_code == 200, report.text
    assert report.headers["cache-control"] == "private, no-store"
    row = report.json()["rows"][0]
    assert (row["accepted"], row["rejected"], row["unallocated"]) == ("1.00", "0.25", "0.75")
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 1
        movement = await session.scalar(select(StockMovement))
        receipt = await session.get(Receipt, receipt_id)
        line = await session.scalar(select(ReceiptLine).where(ReceiptLine.receipt_id == receipt_id))
        assert (movement.organization_id, movement.sku_code, movement.warehouse, movement.kind,
                movement.reason, movement.doc_ref, movement.qty, movement.batch_ref, movement.location_id) == (
            org, "sku1", "warehouse1", "in", "receipt", receipt.number, Decimal("1"), line.batch_ref, line.location_id,
        )
        assert await session.scalar(select(func.count()).select_from(models.Entry)) == 1
        with pytest.raises(DBAPIError, match="immutable"):
            async with session.begin_nested():
                await session.execute(text("UPDATE wms.primary_receipt_binding SET source_snapshot='{}'::json"))
        with pytest.raises(DBAPIError, match="immutable"):
            async with session.begin_nested():
                await session.execute(text("UPDATE wms.receipt_line SET accepted_qty=0.5"))
        basis = await create_app().state.core.services.procurement_source.posted_receipt_basis(session, org, source_id, 1)
        assert service.digest(purchases.purchase_from_receipt_basis(basis)[1]) == posting["digest"]
