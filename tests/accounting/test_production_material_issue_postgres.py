"""PostgreSQL evidence for the reviewed material-to-WIP posting."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.services.auth import CurrentUser
from modules.accounting import service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import Account, Entry, InventoryIssueReceipt, Line, Policy
from modules.accounting.production_material_cost import (
    ProductionMaterialIssuePostingConfirmInput,
    ProductionMaterialIssuePostingInput,
    confirm_material_issue_posting,
    prepare_material_issue_posting,
)
from modules.accounting.schemas import LineInput, PostingInput
from modules.production.accounting_ownership import OwnershipCommand, assign_order, order_snapshot
from modules.production.models import ProductionOrder
from modules.wms.models import StockMovement
from modules.wms.production_material_issues import (
    ProductionMaterialIssueCommand,
    record_material_issue,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

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


async def seed_book(factory, pg_book):
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
            reference="Synthetic material issue policy", inventory_method="specific",
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
