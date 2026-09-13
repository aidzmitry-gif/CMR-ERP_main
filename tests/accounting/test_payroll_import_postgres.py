"""PostgreSQL evidence for the verified gross-payroll accrual import."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from modules.accounting.models import Account, Entry, Line, PayrollAccrualReceipt, Policy
from modules.accounting.payroll_import import (
    PayrollAccrualConfirmInput,
    PayrollAccrualInput,
    confirm_payroll_accrual,
    prepare_payroll_accrual,
)
from modules.accounting.schemas import LineInput, PostingInput
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


def payroll_input(policy_id: int) -> PayrollAccrualInput:
    return PayrollAccrualInput.model_validate({
        "request_key": "00000000-0000-0000-0000-000000000001",
        "source_document": "payroll:2026-10:batch-1",
        "source_version": 1,
        "source_digest": "a" * 64,
        "verified_by": "chief@example.test",
        "source_evidence": "Проверенная ведомость начислений и табель за период",
        "policy_id": policy_id,
        "posting_date": "2026-10-31",
        "payroll_account": "70",
        "lines": [
            {"source_line_id": "line-1", "employee": "E-1", "department": "SALES",
             "debit_account": "26", "amount_byn": "100.00", "dimensions": {"contract": "STAFF"},
             "evidence": "Табель и расчёт по работнику E-1"},
            {"source_line_id": "line-2", "employee": "E-2", "department": "SHOP",
             "debit_account": "20", "amount_byn": "50.00", "dimensions": {"order": "ORDER-42"},
             "evidence": "Табель и расчёт по работнику E-2"},
        ],
    })


async def seed_payroll_book(factory, pg_book):
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
                    required_dimensions=["employee", "department", "order"],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="26", title="Synthetic payroll expense",
                    category="expense", valid_from=date(2026, 1, 1),
                    required_dimensions=["employee", "department"],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="70", title="Synthetic payroll payable",
                    category="liability", valid_from=date(2026, 1, 1),
                    required_dimensions=["employee"], currency_tracking=False,
                    quantity_tracking=False, cash=False, normative_ref="Synthetic"),
        ])
        policy = Policy(
            organization_id=pg_book[0], effective_from=date(2026, 10, 1),
            reference="Synthetic verified payroll policy", inventory_method="specific",
            allocation_basis="direct_cost", depreciation_method="straight_line",
            normative_reference="Synthetic only", normative_verified=False, approved_by="tester",
        )
        session.add(policy)
        await session.commit()
        return policy.id


async def test_verified_payroll_accrual_is_atomic_replayable_and_immutable(pg_factory, pg_book):
    policy_id = await seed_payroll_book(pg_factory, pg_book)
    data = payroll_input(policy_id)

    async with pg_factory() as session:
        preview = await prepare_payroll_accrual(session, pg_book[0], "2026-10", data)
        assert preview["status"] == "reviewed_verified_payroll"
        assert preview["statutory_payroll_certified"] is False
        assert preview["deductions_and_contributions_available"] is False
        confirmed = PayrollAccrualConfirmInput.model_validate({
            **data.model_dump(mode="json"), "digest": preview["digest"],
        })

    async def confirm_once():
        async with pg_factory() as session:
            try:
                entry = await confirm_payroll_accrual(session, pg_book[0], "2026-10", confirmed, "tester")
                await session.commit()
                return entry.id
            except BaseException:
                await session.rollback()
                raise

    first, second = await asyncio.gather(confirm_once(), confirm_once())
    assert first == second

    async with pg_factory() as session:
        receipt = await session.get(PayrollAccrualReceipt, first)
        entry = await session.get(Entry, first)
        assert receipt is not None and entry is not None
        assert receipt.source_document == data.source_document
        assert receipt.source_digest == data.source_digest
        assert receipt.digest == confirmed.digest
        assert entry.source == f"payroll:accrual:{pg_book[0]}:{data.source_document}"
        assert entry.operation == "payroll_accrual_import"
        lines = (await session.scalars(select(Line).where(Line.entry_id == first).order_by(Line.id))).all()
        assert [(line.account_code, line.side, str(line.amount), line.dimensions) for line in lines] == [
            ("26", "debit", "100.00", {"contract": "STAFF", "employee": "E-1", "department": "SALES"}),
            ("70", "credit", "100.00", {"employee": "E-1", "department": "SALES"}),
            ("20", "debit", "50.00", {"order": "ORDER-42", "employee": "E-2", "department": "SHOP"}),
            ("70", "credit", "50.00", {"employee": "E-2", "department": "SHOP"}),
        ]
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.operation == "payroll_accrual_import")) == 1
        assert await session.scalar(select(func.count()).select_from(PayrollAccrualReceipt)) == 1
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "UPDATE accounting.payroll_accrual_receipt SET actor='forged' WHERE entry_id=:entry"
            ), {"entry": first})
        await session.rollback()

    async with pg_factory() as session:
        forged = PostingInput(
            source=f"payroll:accrual:{pg_book[0]}:forged", source_version=1,
            operation="payroll_accrual_import", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="verified-payroll-accrual-import-v1:" + "b" * 64,
            explanation="Forged payroll package", lines=[
                LineInput(account="26", side="debit", amount="1.00",
                          dimensions={"employee": "E-1", "department": "SALES"}),
                LineInput(account="70", side="credit", amount="1.00",
                          dimensions={"employee": "E-1"}),
            ],
        )
        forged_entry = await service.post(
            session, pg_book[0], forged, "tester", payroll_accrual_import=True
        )
        session.add(PayrollAccrualReceipt(
            entry_id=forged_entry.id, organization_id=pg_book[0], month="2026-10",
            request_key="00000000-0000-0000-0000-000000000002",
            source_document="payroll:accrual:forged", source_version=1, source_digest="c" * 64,
            command={"request_key": "00000000-0000-0000-0000-000000000002",
                     "source_document": "payroll:accrual:forged", "source_version": 1,
                     "source_digest": "c" * 64},
            source={"source_document": "payroll:accrual:forged", "source_version": 1,
                    "source_digest": "c" * 64},
            posting=forged.model_dump(mode="json"), digest="0" * 64, actor="tester",
        ))
        with pytest.raises(DBAPIError, match="does not match"):
            await session.flush()
        await session.rollback()


async def test_payroll_entry_requires_receipt_at_transaction_end(pg_factory, pg_book):
    policy_id = await seed_payroll_book(pg_factory, pg_book)
    async with pg_factory() as session:
        forged = PostingInput(
            source=f"payroll:accrual:{pg_book[0]}:missing-receipt", source_version=1,
            operation="payroll_accrual_import", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="verified-payroll-accrual-import-v1:" + "d" * 64,
            explanation="Missing receipt", lines=[
                LineInput(account="26", side="debit", amount="1.00",
                          dimensions={"employee": "E-1", "department": "SALES"}),
                LineInput(account="70", side="credit", amount="1.00",
                          dimensions={"employee": "E-1"}),
            ],
        )
        await service.post(session, pg_book[0], forged, "tester", payroll_accrual_import=True)
        with pytest.raises(DBAPIError, match="requires its complete source receipt"):
            await session.commit()
        await session.rollback()
