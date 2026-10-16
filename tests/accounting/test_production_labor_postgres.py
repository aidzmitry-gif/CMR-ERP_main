"""PostgreSQL evidence for the reviewed verified-payroll production import."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from modules.accounting.models import Account, Entry, Line, Policy, ProductionLaborReceipt
from modules.accounting.production_labor_cost import (
    ProductionLaborConfirmInput,
    ProductionLaborInput,
    confirm_labor_import,
    prepare_labor_import,
)
from modules.accounting.schemas import LineInput, PostingInput
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


class SyntheticProduction:
    async def cost_orders(self, _session, _organization_id, order_ids):
        return [
            {"order_id": order_id, "product": "Synthetic widget", "quantity": "2.00"}
            for order_id in order_ids
        ]


def labor_input(policy_id: int) -> ProductionLaborInput:
    return ProductionLaborInput.model_validate({
        "request_key": "00000000-0000-0000-0000-000000000001",
        "source_document": "payroll:2026-10:batch-1",
        "source_version": 1,
        "source_digest": "a" * 64,
        "verified_by": "chief@example.test",
        "source_evidence": "Проверенная ведомость и расчёт начислений за период",
        "policy_id": policy_id,
        "posting_date": "2026-10-31",
        "payroll_account": "70",
        "lines": [
            {"source_line_id": "line-1", "employee": "E-1", "order_id": 42,
             "order_analytics": "ORDER-42", "department": "SHOP", "cost_account": "20",
             "role": "direct", "amount_byn": "100.00",
             "evidence": "Табель и расчёт по работнику E-1"},
            {"source_line_id": "line-2", "employee": "E-2", "order_id": 43,
             "order_analytics": "ORDER-43", "department": "SHOP", "cost_account": "25",
             "role": "overhead", "amount_byn": "50.00",
             "evidence": "Табель и расчёт по работнику E-2"},
        ],
    })


async def seed_labor_book(factory, pg_book):
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
            Account(organization_id=pg_book[0], code="20", title="Synthetic WIP",
                    category="asset", valid_from=date(2026, 1, 1),
                    required_dimensions=["department", "order"], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="25", title="Synthetic overhead",
                    category="expense", valid_from=date(2026, 1, 1),
                    required_dimensions=["department"], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="70", title="Synthetic payroll payable",
                    category="liability", valid_from=date(2026, 1, 1),
                    required_dimensions=["employee"], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
        ])
        await session.flush()
        policy = Policy(
            organization_id=pg_book[0], effective_from=date(2026, 10, 1),
            reference="Synthetic verified payroll policy", inventory_method="specific",
            allocation_basis="direct_cost", depreciation_method="straight_line",
            normative_reference="Synthetic only", normative_verified=False, approved_by="tester",
            production_costing={
                "overhead_accounts": ["25"], "wip_account": "20",
                "pool_dimensions": ["department"], "order_dimension": "order",
                "rounding": "largest_remainder_cent", "reference": "Synthetic verified payroll",
            },
        )
        session.add(policy)
        await session.commit()
        return policy.id


async def test_verified_payroll_import_is_atomic_replayable_and_immutable(pg_factory, pg_book):
    policy_id = await seed_labor_book(pg_factory, pg_book)
    data = labor_input(policy_id)
    production = SyntheticProduction()

    async with pg_factory() as session:
        preview = await prepare_labor_import(session, pg_book[0], "2026-10", data, production)
        assert preview["status"] == "reviewed_verified_payroll"
        assert preview["posting_available"] is True
        assert preview["final_cost_certified"] is False
        assert preview["source"]["scope"] == "verified_payroll_import"
        assert preview["posting_document"]["source"] == f"production:labor:{pg_book[0]}:{data.source_document}"
        confirmed = ProductionLaborConfirmInput.model_validate({
            **data.model_dump(mode="json"), "digest": preview["digest"],
        })

    async def confirm_once():
        async with pg_factory() as session:
            try:
                entry = await confirm_labor_import(
                    session, pg_book[0], "2026-10", confirmed, "tester", production=production
                )
                await session.commit()
                return entry.id
            except BaseException:
                await session.rollback()
                raise

    first, second = await asyncio.gather(confirm_once(), confirm_once())
    assert first == second

    async with pg_factory() as session:
        receipt = await session.get(ProductionLaborReceipt, first)
        entry = await session.get(Entry, first)
        assert receipt is not None and entry is not None
        assert receipt.source_document == data.source_document
        assert receipt.source_digest == data.source_digest
        assert receipt.digest == confirmed.digest
        assert entry.source == f"production:labor:{pg_book[0]}:{data.source_document}"
        assert entry.operation == "production_labor_import"
        lines = (await session.scalars(
            select(Line).where(Line.entry_id == first).order_by(Line.id)
        )).all()
        assert [(line.account_code, line.side, str(line.amount), line.dimensions) for line in lines] == [
            ("20", "debit", "100.00", {"department": "SHOP", "order": "ORDER-42"}),
            ("70", "credit", "100.00", {"employee": "E-1"}),
            ("25", "debit", "50.00", {"department": "SHOP"}),
            ("70", "credit", "50.00", {"employee": "E-2"}),
        ]
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.operation == "production_labor_import")) == 1
        assert await session.scalar(select(func.count()).select_from(ProductionLaborReceipt)) == 1
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "UPDATE accounting.production_labor_receipt SET actor='forged' WHERE entry_id=:entry"
            ), {"entry": first})
        await session.rollback()

    async with pg_factory() as session:
        forged = PostingInput(
            source=f"production:labor:{pg_book[0]}:payroll:forged",
            source_version=1, operation="production_labor_import", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="verified-payroll-import-v1:" + "a" * 64,
            explanation="Forged payroll package", lines=[
                LineInput(account="20", side="debit", amount="1.00",
                          dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="70", side="credit", amount="1.00",
                          dimensions={"employee": "E-1"}),
            ],
        )
        forged_entry = await service.post(
            session, pg_book[0], forged, "tester", production_labor_import=True
        )
        session.add(ProductionLaborReceipt(
            entry_id=forged_entry.id, organization_id=pg_book[0], month="2026-10",
            request_key=str(UUID("00000000-0000-0000-0000-000000000002")),
            source_document="payroll:forged", source_version=1, source_digest="b" * 64,
            command={"request_key": "00000000-0000-0000-0000-000000000002", "source_document": "payroll:forged",
                     "source_version": 1, "source_digest": "b" * 64},
            source={"source_document": "payroll:forged", "source_version": 1, "source_digest": "b" * 64},
            posting=forged.model_dump(mode="json"), digest="0" * 64, actor="tester",
        ))
        with pytest.raises(DBAPIError, match="does not match"):
            await session.flush()
        await session.rollback()
