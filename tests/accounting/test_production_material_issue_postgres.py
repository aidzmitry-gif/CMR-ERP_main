"""PostgreSQL evidence for the reviewed material-to-WIP posting."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.services.auth import CurrentUser
from modules.accounting import service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import (
    Account,
    Entry,
    InventoryIssueReceipt,
    Line,
    Policy,
    ZeroValueInventoryDisposalReceipt,
)
from modules.accounting.production_material_cost import (
    ProductionMaterialIssuePostingConfirmInput,
    ProductionMaterialIssuePostingInput,
    confirm_material_issue_posting,
    confirm_material_zero_issue,
    prepare_material_issue_posting,
    prepare_material_zero_issue,
)
from modules.accounting.schemas import LineInput, PostingInput
from modules.accounting.zero_value_disposals import ProductionMaterialZeroValueDisposalCommand
from modules.production.accounting_ownership import OwnershipCommand, assign_order, order_snapshot
from modules.production.models import ProductionOrder
from modules.wms.models import StockMovement
from modules.wms.production_material_issues import (
    ProductionMaterialIssueCommand,
    record_material_issue,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_zero_value_output_cost_postgres import run_migration

pytestmark = pytest.mark.integration


class SyntheticProduction:
    async def cost_orders(self, _session, _organization_id, order_ids):
        return [{"order_id": order_ids[0], "product": "Synthetic widget", "quantity": "2.00"}]


def posting_input(policy_id: int) -> ProductionMaterialIssuePostingInput:
    return ProductionMaterialIssuePostingInput.model_validate({
        "policy_id": policy_id,
        "order_id": 42,
        "order_analytics": "ORDER-42",
        "department": "SHOP",
        "wms_movement_id": 1,
        "posting_date": "2026-10-10",
        "account": "10.1",
        "warehouse": "Main",
        "sku": "MAT-1",
        "lot": "LOT-1",
        "quantity": "2.00",
    })


async def seed_book(factory, pg_book, method="specific"):
    async with factory() as session:
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.account','id'), "
            "(SELECT max(id) FROM accounting.account))"
        ))
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.policy','id'), "
            "(SELECT max(id) FROM accounting.policy))"
        ))
        session.add_all([
            Account(organization_id=pg_book[0], code="10.1", title="Synthetic raw material",
                    category="asset", valid_from=date(2026, 1, 1),
                    required_dimensions=["warehouse", "sku", "lot"], currency_tracking=False,
                    quantity_tracking=True, cash=False, normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="20", title="Synthetic WIP",
                    category="asset", valid_from=date(2026, 1, 1),
                    required_dimensions=["department", "order"], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="25", title="Synthetic overhead",
                    category="expense", valid_from=date(2026, 1, 1),
                    required_dimensions=["department"], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
        ])
        await session.flush()
        policy = Policy(
            organization_id=pg_book[0], effective_from=date(2026, 10, 1),
            reference="Synthetic material issue policy", inventory_method=method,
            allocation_basis="direct_cost", depreciation_method="straight_line",
            normative_reference="Synthetic only", normative_verified=False, approved_by="tester",
            production_costing={
                "overhead_accounts": ["25"], "wip_account": "20",
                "pool_dimensions": ["department"], "order_dimension": "order",
                "rounding": "largest_remainder_cent", "reference": "Synthetic reviewed material issue",
            },
        )
        session.add(policy)
        order = ProductionOrder(number="MATERIAL-42", product="Synthetic widget", qty=2)
        session.add(order)
        session.add(StockMovement(
            organization_id=pg_book[0], sku_code="MAT-1", warehouse="Main", kind="in",
            qty="5.00", reason="receipt", batch_ref="LOT-1", doc_ref="receipt:material-1",
            note="Synthetic inventory receipt",
        ))
        await session.flush()
        await assign_order(
            session, AccountingService(), pg_book[0], CurrentUser("tester", ["director"]),
            OwnershipCommand(order_id=order.id, expected_digest=order_snapshot(order)[1],
                             evidence="Synthetic reviewed production owner"),
        )
        await session.commit()
        return policy.id, order.id


async def seed_inventory_value(factory, pg_book, policy_id):
    async with factory() as session:
        data = PostingInput(
            source="inventory:receipt:material-1", source_version=1, operation="manual",
            document_date="2026-10-01", operation_date="2026-10-01", posting_date="2026-10-01",
            policy_id=policy_id, rule_version="synthetic-receipt-v1",
            explanation="Synthetic reviewed material receipt", lines=[
                LineInput(account="10.1", side="debit", amount="31.25", quantity="5.00",
                          dimensions={"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"}),
                LineInput(account="60", side="credit", amount="31.25", dimensions={}),
            ],
        )
        row = await service.post(session, pg_book[0], data, "tester")
        await session.commit()
        return row.id


async def seed_mixed_inventory_value(factory, pg_book, policy_id):
    async with factory() as session:
        for source, quantity, day in (("material-cent", "1.00", "2026-10-01"),
                                      ("material-fraction", "3.00", "2026-10-02")):
            await service.post(session, pg_book[0], PostingInput(
                source=f"inventory:receipt:{source}", source_version=1, operation="manual",
                document_date=day, operation_date=day, posting_date=day, policy_id=policy_id,
                rule_version="synthetic-receipt-v1", explanation="Synthetic material allocation origin", lines=[
                LineInput(account="10.1", side="debit", amount="0.01", quantity=quantity,
                              dimensions={"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"}),
                    LineInput(account="60", side="credit", amount="0.01", dimensions={}),
                ]), "tester")
        await session.commit()


async def seed_zero_rounding_inventory_value(factory, pg_book, policy_id):
    async with factory() as session:
        await service.post(session, pg_book[0], PostingInput(
            source="inventory:receipt:material-zero-rounding", source_version=1, operation="inventory_purchase",
            document_date="2026-10-01", operation_date="2026-10-01", posting_date="2026-10-01",
            policy_id=policy_id, rule_version="synthetic-receipt-v1", explanation="Synthetic zero material origin", lines=[
                LineInput(account="10.1", side="debit", amount="0.01", quantity="5.00",
                          dimensions={"warehouse": "Main", "sku": "MAT-1", "lot": "LOT-1"}),
                LineInput(account="60", side="credit", amount="0.01", dimensions={}),
            ]), "tester")
        await session.commit()


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
async def test_material_allocation_requires_migration(pg_factory, pg_book, method):
    policy_id, order_id = await seed_book(pg_factory, pg_book, method)
    await seed_inventory_value(pg_factory, pg_book, policy_id)
    _, movement_id, _ = await seed_physical_issue(pg_factory, pg_book, order_id)
    data = posting_input(policy_id).model_copy(update={"order_id": order_id, "wms_movement_id": movement_id})
    async with pg_factory() as session:
        await run_migration(session, "0140_zero_value_disposals.py", "upgrade")
        with pytest.raises(service.AccountingError, match="migration 0150"):
            await prepare_material_zero_issue(session, pg_book[0], "2026-10", data, SyntheticProduction())
        with pytest.raises(service.AccountingError, match="migration 0149"):
            await prepare_material_issue_posting(session, pg_book[0], "2026-10", data, SyntheticProduction())
        command = ProductionMaterialIssuePostingConfirmInput.model_validate({
            **data.model_dump(mode="json"), "basis_digest": "0" * 64, "digest": "0" * 64})
        with pytest.raises(service.AccountingError, match="migration 0149"):
            await confirm_material_issue_posting(session, pg_book[0], "2026-10", command, "tester")


async def seed_physical_issue(factory, pg_book, order_id):
    async with factory() as session:
        command = ProductionMaterialIssueCommand(
            request_id=uuid4(), order_id=order_id, expected_order_digest="0" * 64,
            operation_date="2026-10-10", sku_code="MAT-1", quantity="2.00", warehouse="Main",
            location_id=None, lot="LOT-1", evidence="Synthetic reviewed material issue",
        )
        order = await session.get(ProductionOrder, order_id)
        command = command.model_copy(update={"expected_order_digest": order_snapshot(order)[1]})
        row, movement = await record_material_issue(
            session, AccountingService(), pg_book[0], CurrentUser("tester", ["director"]), command
        )
        await session.commit()
        return row.id, movement.id, command


async def test_material_issue_posts_one_reviewed_wip_package(pg_factory, pg_book):
    policy_id, order_id = await seed_book(pg_factory, pg_book)
    await seed_inventory_value(pg_factory, pg_book, policy_id)
    _, movement_id, physical = await seed_physical_issue(pg_factory, pg_book, order_id)
    data = posting_input(policy_id).model_copy(update={"order_id": order_id, "wms_movement_id": movement_id})
    production = SyntheticProduction()

    async with pg_factory() as session:
        await run_migration(session, "0140_zero_value_disposals.py", "upgrade")
        await session.commit()
        preview = await prepare_material_issue_posting(
            session, pg_book[0], "2026-10", data, production
        )
        assert preview["status"] == "reviewed_material_cost"
        assert preview["inventory_cost"]["issue_cost_byn"] == "12.50"
        assert preview["posting_available"] is True
        confirmed = ProductionMaterialIssuePostingConfirmInput.model_validate({
            **data.model_dump(mode="json"),
            "basis_digest": preview["basis_digest"],
            "digest": preview["digest"],
        })

    async def confirm_once():
        async with pg_factory() as session:
            entry = await confirm_material_issue_posting(
                session, pg_book[0], "2026-10", confirmed, "tester"
            )
            await session.commit()
            return entry.id

    first, second = await asyncio.gather(confirm_once(), confirm_once())
    assert first == second

    async with pg_factory() as session:
        receipt = await session.get(InventoryIssueReceipt, first)
        entry = await session.get(Entry, first)
        movement = await session.get(StockMovement, movement_id)
        assert receipt is not None and entry is not None and movement is not None
        assert entry.source == f"production:material:{pg_book[0]}:{physical.request_id}"
        assert [(line.side, line.account_code, str(line.amount), line.quantity)
                for line in (await session.scalars(
                    select(Line).where(Line.entry_id == first).order_by(Line.id)
                )).all()] == [
            ("debit", "20", "12.50", None),
            ("credit", "10.1", "12.50", 2),
        ]
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.operation == "inventory_issue")) == 1
        assert await session.scalar(select(func.count()).select_from(InventoryIssueReceipt)) == 1
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "DELETE FROM accounting.inventory_issue_receipt WHERE entry_id=:entry"
            ), {"entry": first})
        await session.rollback()


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
async def test_material_issue_persists_complete_mixed_allocation(pg_factory, pg_book, method):
    policy_id, order_id = await seed_book(pg_factory, pg_book, method)
    await seed_mixed_inventory_value(pg_factory, pg_book, policy_id)
    _, movement_id, physical = await seed_physical_issue(pg_factory, pg_book, order_id)
    data = posting_input(policy_id).model_copy(update={"order_id": order_id, "wms_movement_id": movement_id})
    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py",
                         "0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py",
                         "0146_zero_value_allocation_basis.py", "0147_zero_value_allocation_runtime.py",
                         "0148_zero_value_allocated_sales.py", "0149_production_material_allocations.py"):
            await run_migration(session, revision, "upgrade")
        await session.commit()
        preview = await prepare_material_issue_posting(session, pg_book[0], "2026-10", data, SyntheticProduction())
        cost = preview["inventory_cost"]
        assert cost["source_allocation_version"] == 1
        assert len(cost["inventory_layers"]) == 2
        assert sum(Decimal(layer["quantity"]) for layer in cost["inventory_layers"]) == Decimal("2")
        assert [layer["amount_byn"] for layer in cost["inventory_layers"]] == ["0.01", "0.00"]
        assert preview["basis_digest"] == cost["basis_digest"]
        confirmed = ProductionMaterialIssuePostingConfirmInput.model_validate({
            **data.model_dump(mode="json"), "basis_digest": preview["basis_digest"], "digest": preview["digest"],
        })
        entry = await confirm_material_issue_posting(session, pg_book[0], "2026-10", confirmed, "tester")
        assert (await confirm_material_issue_posting(session, pg_book[0], "2026-10", confirmed, "tester")).id == entry.id
        receipt = await session.get(InventoryIssueReceipt, entry.id)
        assert receipt.cost["source_allocation_version"] == 1
        lines = (await session.scalars(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))).all()
        assert [(line.side, line.account_code, str(line.amount)) for line in lines] == [
            ("debit", "20", "0.01"), ("credit", "10.1", "0.01"),
        ]
        assert physical.lot == "LOT-1"
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        with pytest.raises(DBAPIError, match="Cannot downgrade complete material allocation history"):
            async with session.begin_nested():
                await run_migration(session, "0149_production_material_allocations.py", "downgrade")


async def test_second_reviewed_material_issue_accepts_prior_production_issue_movement(pg_factory, pg_book, monkeypatch):
    """A real prior production issue is physical history, not an unclassified movement."""
    from fastapi import HTTPException

    from modules.wms import routes as wms_routes

    policy_id, order_id = await seed_book(pg_factory, pg_book)
    await seed_inventory_value(pg_factory, pg_book, policy_id)
    _, _, first = await seed_physical_issue(pg_factory, pg_book, order_id)
    second = first.model_copy(update={"request_id": uuid4()})
    original_reasons = wms_routes._INVENTORY_PHYSICAL_REASONS

    monkeypatch.setattr(wms_routes, "_INVENTORY_PHYSICAL_REASONS",
                        original_reasons - {"production_issue"})
    async with pg_factory() as session:
        with pytest.raises(HTTPException, match="неразобранное движение"):
            await record_material_issue(
                session, AccountingService(), pg_book[0], CurrentUser("tester", ["director"]), second)
        await session.rollback()

    monkeypatch.setattr(wms_routes, "_INVENTORY_PHYSICAL_REASONS",
                        original_reasons)
    async with pg_factory() as session:
        binding, movement = await record_material_issue(
            session, AccountingService(), pg_book[0], CurrentUser("tester", ["director"]), second)
        replay, replay_movement = await record_material_issue(
            session, AccountingService(), pg_book[0], CurrentUser("tester", ["director"]), second)
        await session.commit()
        assert binding.request_key == str(second.request_id)
        assert movement.reason == "production_issue" and movement.kind == "out"
        assert replay.id == binding.id and replay_movement.id == movement.id


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
async def test_material_zero_rounding_receipt_is_entryless_and_retries(pg_factory, pg_book, method):
    policy_id, order_id = await seed_book(pg_factory, pg_book, method)
    await seed_zero_rounding_inventory_value(pg_factory, pg_book, policy_id)
    _, movement_id, _ = await seed_physical_issue(pg_factory, pg_book, order_id)
    data = posting_input(policy_id).model_copy(update={"order_id": order_id, "wms_movement_id": movement_id})
    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py",
                         "0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py",
                         "0146_zero_value_allocation_basis.py", "0147_zero_value_allocation_runtime.py",
                         "0148_zero_value_allocated_sales.py", "0149_production_material_allocations.py",
                         "0150_zero_material_allocations.py"):
            await run_migration(session, revision, "upgrade")
        await session.commit()
        prepared = await prepare_material_zero_issue(session, pg_book[0], "2026-10", data, SyntheticProduction())
        assert prepared["inventory_cost"]["issue_cost_byn"] == "0.00"
        command = prepared["zero_value_receipt"]
        assert command["command_version"] == 5 and len(command["inventory_layers"]) == 1
        import json
        for field, value in (("destination_account", "10.1"), ("operation_date", "2026-10-02")):
            forged = {**command, field: value}
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.scalar(text(
                        "SELECT accounting.zero_value_material_allocation_basis(:org, CAST(:command AS jsonb), 2147483647)"
                    ), {"org": pg_book[0], "command": json.dumps(forged)})
        for field, value in (("binding_id", str(command["material_binding"]["binding_id"])), ("quantity", 2)):
            forged = {**command, "material_binding": {**command["material_binding"], field: value}}
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.scalar(text(
                        "SELECT accounting.zero_value_material_allocation_basis(:org, CAST(:command AS jsonb), 2147483647)"
                    ), {"org": pg_book[0], "command": json.dumps(forged)})
        confirmed = ProductionMaterialIssuePostingConfirmInput.model_validate({
            **data.model_dump(mode="json"), "basis_digest": prepared["basis_digest"],
            "digest": service.digest(ProductionMaterialZeroValueDisposalCommand.model_validate(command)),
        })
        first = await confirm_material_zero_issue(session, pg_book[0], "2026-10", confirmed, "tester", SyntheticProduction())
        raw_command = json.dumps(command).replace(
            f'"binding_id": {command["material_binding"]["binding_id"]}',
            f'"binding_id": {command["material_binding"]["binding_id"]}e0',
        )
        with pytest.raises(DBAPIError, match="canonical JSON integer tokens"):
            async with session.begin_nested():
                await session.execute(text("""
                    INSERT INTO accounting.inventory_zero_value_disposal_receipt
                    (organization_id,source,source_version,operation,entry_id,posting_date,policy_id,
                     command,basis_digest,digest,actor)
                    SELECT organization_id,source,source_version,operation,entry_id,posting_date,policy_id,
                           CAST(:command AS json),basis_digest,digest,actor
                    FROM accounting.inventory_zero_value_disposal_receipt WHERE id=:id
                """), {"command": raw_command, "id": first["receipt_id"]})
        second = await confirm_material_zero_issue(session, pg_book[0], "2026-10", confirmed, "tester", SyntheticProduction())
        assert first["receipt_id"] == second["receipt_id"] and first["entry_id"] is None
        receipt = await session.get(ZeroValueInventoryDisposalReceipt, first["receipt_id"])
        assert receipt is not None and receipt.entry_id is None
        await session.commit()
        with pytest.raises(DBAPIError, match="Cannot downgrade V5"):
            async with session.begin_nested():
                await run_migration(session, "0150_zero_material_allocations.py", "downgrade")
        await session.rollback()
        from httpx import ASGITransport, AsyncClient

        from tests.accounting.test_inventory_allocation_api_postgres import application
        app = application(pg_factory)
        app.state.core.services.production_output = SyntheticProduction()
        base = f"/accounting/organizations/{pg_book[0]}/periods/2026-10"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(base + "/production-material-issue-confirm",
                json={**confirmed.model_dump(mode="json"), "zero_value": True})
            assert response.status_code == 201, response.text
            assert response.json()["receipt_id"] == first["receipt_id"]
            response = await client.get(base + f"/production-material-issue-posting-status/{movement_id}")
            assert response.status_code == 200, response.text
            assert response.json()["entry_id"] is None and response.json()["quantity_registered"] is True
            assert response.json()["digest"] == confirmed.digest
            assert response.json()["posted"] is False
