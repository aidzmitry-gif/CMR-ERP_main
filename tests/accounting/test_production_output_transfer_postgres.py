"""PostgreSQL evidence for the reviewed WIP-to-finished-goods transfer."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

import asyncio
import runpy
from datetime import date
from decimal import Decimal

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from modules.accounting.models import (
    Account,
    Entry,
    Policy,
    ProductionOutputTransferReceipt,
)
from modules.accounting.production_output_transfer import (
    ProductionOutputTransferConfirmInput,
    ProductionOutputTransferInput,
    confirm_output_transfer,
    output_transfer_source_state,
    prepare_output_transfer,
    validate_output_transfers_for_close,
)
from modules.accounting.schemas import LineInput, PostingInput
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def _upgrade_group_guard(session):
    def upgrade(connection):
        migration = runpy.run_path("migrations/versions/0138_production_output_transfer_guard_groups.py")
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()

    connection = await session.connection()
    await connection.run_sync(upgrade)


class SyntheticProduction:
    """Stable reviewed physical facts; accounting still reads the real ledger."""

    async def cost_orders(self, _session, _organization_id, order_ids):
        return [{"order_id": order_ids[0], "product": "Synthetic widget", "quantity": "2.00"}]

    async def output_reconciliation(self, _session, _organization_id, _order_id, _warehouse):
        return {
            "planned_quantity": "2.00",
            "confirmed_quantity": "2.00",
            "accepted_quantity": "2.00",
            "rejected_quantity": "0.00",
            "pending_quantity": "0.00",
            "sku_code": "SYN-WIDGET",
            "unit": "шт",
            "lot": "LOT-1",
            "documents": [{"document_id": 101, "operation_date": "2026-10-10"}],
        }


def transfer_input(policy_id: int) -> ProductionOutputTransferInput:
    return ProductionOutputTransferInput.model_validate({
        "policy_id": policy_id,
        "order_id": 42,
        "analytical_order": "ORDER-42",
        "department": "SHOP",
        "warehouse": "Main",
        "posting_date": "2026-10-31",
        "output_document_ids": [101],
    })


async def _seed_production_book(factory, pg_book, method="specific"):
    """Add only synthetic production accounts and a versioned policy."""
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
            Account(organization_id=pg_book[0], code="25", title="Synthetic overhead",
                    category="expense", valid_from=date(2026, 1, 1),
                    required_dimensions=["department"], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="20", title="Synthetic WIP",
                    category="asset", valid_from=date(2026, 1, 1),
                    required_dimensions=["department", "order"], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="43", title="Synthetic finished goods",
                    category="asset", valid_from=date(2026, 1, 1),
                    required_dimensions=["warehouse", "sku", "lot"], currency_tracking=False,
                    quantity_tracking=True, cash=False, normative_ref="Synthetic"),
        ])
        await session.flush()
        policy = Policy(
            organization_id=pg_book[0], effective_from=date(2026, 10, 1),
            reference="Synthetic production transfer policy", inventory_method=method,
            allocation_basis="direct_cost", depreciation_method="straight_line",
            normative_reference="Synthetic only", normative_verified=False, approved_by="tester",
            production_costing={
                "overhead_accounts": ["25"], "wip_account": "20",
                "finished_goods_account": "43", "pool_dimensions": ["department"],
                "order_dimension": "order", "rounding": "largest_remainder_cent",
                "reference": "Synthetic reviewed production transfer",
            },
        )
        session.add(policy)
        await session.flush()
        await session.commit()
        return policy.id


async def _seed_wip(factory, pg_book, policy_id, groups=None):
    groups = groups or [("SHOP", "ORDER-42", "100.00")]
    async with factory() as session:
        wip_lines = [
            LineInput(account="20", side="debit", amount=amount,
                      dimensions={"department": department, "order": order})
            for department, order, amount in groups
        ]
        posting = PostingInput(
            source="production:wip:42", source_version=1, operation="manual",
            document_date="2026-10-10", operation_date="2026-10-10",
            posting_date="2026-10-10", policy_id=policy_id, rule_version="synthetic-wip-v1",
            explanation="Synthetic reviewed WIP cost", lines=[
                *wip_lines,
                LineInput(account="60", side="credit", amount=str(sum((Decimal(amount) for _, _, amount in groups), Decimal("0"))), dimensions={}),
            ],
        )
        entry = await service.post(session, pg_book[0], posting, "tester")
        await session.commit()
        return entry.id


async def test_reviewed_output_transfer_is_atomic_replayable_and_immutable(pg_factory, pg_book):
    policy_id = await _seed_production_book(pg_factory, pg_book)
    wip_entry_id = await _seed_wip(pg_factory, pg_book, policy_id, [
        ("SHOP-A", "ORDER-42", "70.00"), ("SHOP-B", "ORDER-42", "30.00"),
        ("SHOP-A", "OTHER", "50.00"),
    ])
    production = SyntheticProduction()
    command = transfer_input(policy_id)

    async with pg_factory() as session:
        preview = await prepare_output_transfer(
            session, pg_book[0], "2026-10", command, production, object()
        )
        assert preview["status"] == "ready_for_transfer_review"
        assert preview["candidate_transfer_byn"] == "100.00"
        assert preview["final_cost_certified"] is False
        confirmed = ProductionOutputTransferConfirmInput.model_validate({
            **command.model_dump(mode="json"),
            "basis_digest": preview["basis_digest"],
            "digest": preview["digest"],
        })
        await _upgrade_group_guard(session)
        await session.commit()

    async def confirm_once():
        async with pg_factory() as session:
            entry = await confirm_output_transfer(
                session, pg_book[0], "2026-10", confirmed, "tester",
                production=production, warehouse_gateway=object(),
            )
            await session.commit()
            return entry.id

    first, second = await asyncio.gather(confirm_once(), confirm_once())
    assert first == second

    async with pg_factory() as session:
        receipt = await session.get(ProductionOutputTransferReceipt, first)
        assert receipt is not None
        assert receipt.organization_id == pg_book[0]
        assert receipt.order_id == command.order_id
        entry = await session.get(Entry, first)
        assert entry is not None
        assert entry.source == f"production:output-transfer:{pg_book[0]}:42"
        assert entry.operation == "production_output_transfer"
        lines = (await session.execute(text(
            "SELECT account_code, side, amount, dimensions, quantity "
            "FROM accounting.line WHERE entry_id=:entry ORDER BY side, dimensions->>'department'"
        ), {"entry": first})).all()
        assert [(row[0], row[1], str(row[2]),
                  str(row[4]) if row[4] is not None else None) for row in lines] == [
            ("20", "credit", "70.00", None),
            ("20", "credit", "30.00", None),
            ("43", "debit", "100.00", "2.000000"),
        ]
        wip_lines = (await session.execute(text(
            "SELECT line.side, line.amount, line.dimensions FROM accounting.line line "
            "WHERE line.entry_id IN (:wip, :transfer) AND line.account_code='20'"
        ), {"wip": wip_entry_id, "transfer": first})).all()
        balances = {}
        for side, amount, dimensions in wip_lines:
            key = (dimensions["department"], dimensions["order"])
            balances[key] = balances.get(key, 0) + (amount if side == "debit" else -amount)
        assert {key: str(value) for key, value in balances.items()} == {
            ("SHOP-A", "ORDER-42"): "0.00", ("SHOP-B", "ORDER-42"): "0.00",
            ("SHOP-A", "OTHER"): "50.00",
        }
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.operation == "production_output_transfer")) == 1
        assert await session.scalar(select(func.count()).select_from(ProductionOutputTransferReceipt)) == 1
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.id == wip_entry_id)) == 1

        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "UPDATE accounting.production_output_transfer_receipt "
                "SET actor='forged' WHERE entry_id=:entry"
            ), {"entry": first})
        await session.rollback()

    async with pg_factory() as session:
        forged_posting = PostingInput(
            source=f"production:output-transfer:{pg_book[0]}:99", source_version=1,
            operation="production_output_transfer", document_date="2026-10-10",
            operation_date="2026-10-10", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="production-output-transfer-v1", explanation="Forged package",
            lines=[
                LineInput(account="43", side="debit", amount="1.00",
                          dimensions={"warehouse": "Main", "sku": "SYN-WIDGET", "lot": "LOT-1"}, quantity="1.00"),
                LineInput(account="20", side="credit", amount="1.00",
                          dimensions={"department": "SHOP", "order": "ORDER-42"}),
            ],
        )
        forged_entry = await service.post(
            session, pg_book[0], forged_posting, "tester", production_output_transfer=True
        )
        session.add(ProductionOutputTransferReceipt(
            entry_id=forged_entry.id, organization_id=pg_book[0], order_id=99, month="2026-10",
            command={"order_id": 99, "basis_digest": "b" * 64, "digest": "0" * 64},
            basis={}, posting=forged_posting.model_dump(mode="json"),
            basis_digest="b" * 64, digest="0" * 64, actor="tester",
        ))
        with pytest.raises(DBAPIError, match="does not match"):
            await session.flush()
        await session.rollback()

    async with pg_factory() as session:
        mismatched_posting = PostingInput(
            source=f"production:output-transfer:{pg_book[0]}:100", source_version=1,
            operation="production_output_transfer", document_date="2026-10-10",
            operation_date="2026-10-10", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="production-output-transfer-v1", explanation="Forged group package",
            lines=[
                LineInput(account="43", side="debit", amount="100.00",
                          dimensions={"warehouse": "Main", "sku": "SYN-WIDGET", "lot": "LOT-1"}, quantity="2.00"),
                LineInput(account="20", side="credit", amount="70.00",
                          dimensions={"department": "SHOP-A", "order": "ORDER-42"}),
                LineInput(account="20", side="credit", amount="30.00",
                          dimensions={"department": "SHOP-X", "order": "ORDER-42"}),
            ],
        )
        mismatched_entry = await service.post(
            session, pg_book[0], mismatched_posting, "tester", production_output_transfer=True
        )
        mismatched_digest = service.digest(mismatched_posting)
        session.add(ProductionOutputTransferReceipt(
            entry_id=mismatched_entry.id, organization_id=pg_book[0], order_id=100, month="2026-10",
            command={"order_id": 100, "basis_digest": "c" * 64, "digest": mismatched_digest},
            basis={"organization_id": pg_book[0], "month": "2026-10", "policy_id": policy_id,
                   "target": {"finished_goods_account": "43"}, "candidate_transfer_byn": "100.00",
                   "output": {"accepted_quantity": "2.00"}, "wip": {"account": "20", "groups": [
                       {"dimensions": {"department": "SHOP-A", "order": "ORDER-42"}, "balance_byn": "70.00"},
                       {"dimensions": {"department": "SHOP-B", "order": "ORDER-42"}, "balance_byn": "30.00"},
                   ]}},
            posting=mismatched_posting.model_dump(mode="json"), basis_digest="c" * 64,
            digest=mismatched_digest, actor="tester",
        ))
        with pytest.raises(DBAPIError, match="WIP credits differ"):
            await session.flush()
        await session.rollback()


async def test_output_transfer_basis_becomes_stale_only_when_its_later_source_enters_closing_month(pg_factory, pg_book):
    policy_id = await _seed_production_book(pg_factory, pg_book)
    await _seed_wip(pg_factory, pg_book, policy_id)
    production = SyntheticProduction()
    command = transfer_input(policy_id)
    async with pg_factory() as session:
        preview = await prepare_output_transfer(session, pg_book[0], "2026-10", command, production, object())
        confirmed = ProductionOutputTransferConfirmInput.model_validate({
            **command.model_dump(mode="json"), "basis_digest": preview["basis_digest"], "digest": preview["digest"],
        })
        await _upgrade_group_guard(session)
        await session.commit()
    async with pg_factory() as session:
        entry = await confirm_output_transfer(session, pg_book[0], "2026-10", confirmed, "tester",
                                              production=production, warehouse_gateway=object())
        await session.commit()
        receipt = await session.get(ProductionOutputTransferReceipt, entry.id)
        assert await output_transfer_source_state(session, receipt, "2026-10") == "unchanged"
        future_cost = PostingInput(
            source="production:late-cost:42", source_version=1, operation="manual",
            document_date="2026-11-01", operation_date="2026-11-01", posting_date="2026-11-01",
            policy_id=policy_id, rule_version="synthetic-late-cost-v1", explanation="Synthetic later production cost",
            lines=[
                LineInput(account="20", side="debit", amount="10.00", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="10.00", dimensions={}),
            ],
        )
        await service.post(session, pg_book[0], future_cost, "tester")
        await session.commit()
    async with pg_factory() as session:
        receipt = await session.get(ProductionOutputTransferReceipt, entry.id)
        assert await output_transfer_source_state(session, receipt, "2026-10") == "unchanged"
        assert await output_transfer_source_state(session, receipt, "2026-11") == "changed"
        with pytest.raises(service.AccountingError, match="source basis is changed.*order 42"):
            await validate_output_transfers_for_close(session, pg_book[0], "2026-11")
