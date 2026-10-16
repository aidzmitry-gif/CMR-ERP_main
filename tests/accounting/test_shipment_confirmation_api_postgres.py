"""Public posting with real WMS acts and committed PostgreSQL receipts."""
# ruff: noqa: F811
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import User
from modules.accounting.models import AccessGrant, Entry, ShipmentAccountingReceipt, SourceControl
from modules.wms.models import StockMovement
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


async def test_accountant_posts_and_replays_without_warehouse_write(physical_pg):
    api = physical_pg[0]
    factory = physical_pg[1]
    from tests.accounting.test_zero_value_output_cost_postgres import run_migration

    async with factory() as session:
        if not await session.scalar(text(
            "SELECT to_regclass('accounting.inventory_zero_value_disposal_receipt') IS NOT NULL"
        )):
            await run_migration(session, "0140_zero_value_disposals.py", "upgrade")
        await session.commit()
    factory, org, act, data = await prepare_accounting(physical_pg)
    root = f"/accounting/organizations/{org}/shipments/{act['source_key']}"
    async with factory() as session:
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == org).values(role="accountant"))
        session.add(User(
            username="allocator",
            full_name="Synthetic finance accountant",
            role="finance",
            status="active",
        ))
        entries = await session.scalar(select(func.count()).select_from(Entry))
        stock = await session.scalar(select(func.count()).select_from(StockMovement))
        await session.commit()
    api.headers["X-User-Roles"] = "finance"
    preview = await api.post(root + "/preview", json=data.model_dump(mode="json"))
    assert preview.status_code == 200, preview.text
    body = {**data.model_dump(mode="json"), "expected_basis_digest": preview.json()["basis_digest"]}
    created = await api.post(root + "/confirm", json=body)
    assert created.status_code == 201, created.text
    assert created.json()["posted"] is True
    assert created.headers["cache-control"] == "private, no-store"
    repeated = await api.post(root + "/confirm", json=body)
    assert repeated.status_code == 201 and repeated.json() == created.json()
    changed = await api.post(root + "/confirm", json={**body, "explanation": "Changed decision"})
    assert changed.status_code == 409
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == entries + 1
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == stock
        assert await session.scalar(select(func.count()).select_from(ShipmentAccountingReceipt)) == 1
        assert await session.scalar(select(SourceControl.entry_id).where(
            SourceControl.source == created.json()["source"])) == created.json()["anchor_entry_id"]
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == org).values(role="reader"))
        await session.commit()
    assert (await api.post(root + "/confirm", json=body)).status_code == 403
    assert (await api.post(root.replace(f"/{org}/", "/999999/") + "/confirm", json=body)).status_code == 403


async def test_stale_preview_and_client_act_do_not_post(physical_pg):
    api = physical_pg[0]
    factory, org, act, data = await prepare_accounting(physical_pg)
    root = f"/accounting/organizations/{org}/shipments/{act['source_key']}"
    body = {**data.model_dump(mode="json"), "expected_basis_digest": "0" * 64}
    response = await api.post(root + "/confirm", json=body)
    assert response.status_code == 409, response.text
    assert (await api.post(root + "/confirm", json={**body, "receipt": act})).status_code == 422
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ShipmentAccountingReceipt)) == 0
        assert await session.scalar(select(SourceControl.entry_id)) is None


async def test_concurrent_public_confirmation_creates_one_package(physical_pg):
    import asyncio

    api = physical_pg[0]
    factory, org, act, data = await prepare_accounting(physical_pg)
    root = f"/accounting/organizations/{org}/shipments/{act['source_key']}"
    preview = await api.post(root + "/preview", json=data.model_dump(mode="json"))
    assert preview.status_code == 200, preview.text
    body = {**data.model_dump(mode="json"), "expected_basis_digest": preview.json()["basis_digest"]}
    async with factory() as session:
        entries = await session.scalar(select(func.count()).select_from(Entry))
        stock = await session.scalar(select(func.count()).select_from(StockMovement))
    first, second = await asyncio.gather(
        api.post(root + "/confirm", json=body),
        api.post(root + "/confirm", json=body),
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json() == second.json()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == entries + 1
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == stock
        assert await session.scalar(select(func.count()).select_from(ShipmentAccountingReceipt)) == 1
        assert await session.scalar(select(SourceControl.entry_id)) == first.json()["anchor_entry_id"]


async def test_commit_failure_returns_error_and_rolls_back_package(physical_pg, monkeypatch):
    from modules.accounting import shipment_commands

    api = physical_pg[0]
    factory, org, act, data = await prepare_accounting(physical_pg)
    root = f"/accounting/organizations/{org}/shipments/{act['source_key']}"
    preview = await api.post(root + "/preview", json=data.model_dump(mode="json"))
    body = {**data.model_dump(mode="json"), "expected_basis_digest": preview.json()["basis_digest"]}
    original_confirm, original_commit = shipment_commands.confirm, AsyncSession.commit

    async def mark_transaction(session, *args, **kwargs):
        receipt = await original_confirm(session, *args, **kwargs)
        session.info["simulate_commit_failure"] = True
        return receipt

    async def fail_commit(session):
        if session.info.pop("simulate_commit_failure", False):
            raise ValueError("Synthetic commit rejection")
        return await original_commit(session)

    monkeypatch.setattr(shipment_commands, "confirm", mark_transaction)
    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    response = await api.post(root + "/confirm", json=body)
    assert response.status_code == 422, response.text
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ShipmentAccountingReceipt)) == 0
        assert await session.scalar(select(SourceControl.entry_id)) is None
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.source == f"wms:physical-shipment:{org}:{act['source_key']}")) == 0


async def test_pending_blocks_close_and_exact_replay_survives_valid_close(physical_pg):
    import pytest

    from modules.accounting import service
    from modules.accounting.schemas import CloseInput

    api = physical_pg[0]
    # Only this synthetic policy is certified for exercising closing guards.
    factory, org, act, data = await prepare_accounting(physical_pg, normative_verified=True)
    month = data.posting_date.strftime("%Y-%m")
    root = f"/accounting/organizations/{org}/shipments/{act['source_key']}"
    evidence = {step: "Synthetic checked control" for step in service.CLOSE_STEPS}
    async with factory() as session:
        period = await service.period_for(session, org, month)
        with pytest.raises(service.AccountingError, match="Unposted primary documents"):
            await service.close_period(session, org, month, CloseInput(
                expected_generation=period.generation, evidence=evidence), "allocator")
        await session.rollback()
    preview = await api.post(root + "/preview", json=data.model_dump(mode="json"))
    assert preview.status_code == 200, preview.text
    body = {**data.model_dump(mode="json"), "expected_basis_digest": preview.json()["basis_digest"]}
    posted = await api.post(root + "/confirm", json=body)
    assert posted.status_code == 201, posted.text
    async with factory() as session:
        period = await service.period_for(session, org, month)
        await service.close_period(session, org, month, CloseInput(
            expected_generation=period.generation, evidence=evidence), "allocator")
        await session.commit()
        entries = await session.scalar(select(func.count()).select_from(Entry))
    replay = await api.post(root + "/confirm", json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json() == posted.json()
    changed = await api.post(root + "/confirm", json={**body, "explanation": "Changed after close"})
    assert changed.status_code == 409
    async with factory() as session:
        assert (await service.period_for(session, org, month)).closed is True
        assert await session.scalar(select(func.count()).select_from(Entry)) == entries
