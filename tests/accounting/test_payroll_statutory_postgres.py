# ruff: noqa: F811 -- pytest fixtures are imported for registration.
"""PostgreSQL evidence for reviewed payroll deductions/contributions."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from modules.accounting.models import Account, Entry, Line, PayrollStatutoryReceipt
from modules.accounting.payroll_statutory import (
    PayrollStatutoryConfirmInput,
    PayrollStatutoryInput,
    confirm_payroll_statutory,
    prepare_payroll_statutory,
)
from modules.accounting.schemas import LineInput, PostingInput
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


def statutory_input(policy_id: int) -> PayrollStatutoryInput:
    return PayrollStatutoryInput.model_validate({
        "request_key": "00000000-0000-0000-0000-000000000011",
        "source_document": "payroll:2026-10:statutory-1",
        "source_version": 1,
        "source_digest": "b" * 64,
        "verified_by": "chief@example.test",
        "source_evidence": "Проверенный расчёт удержаний и взносов за период",
        "policy_id": policy_id,
        "posting_date": "2026-10-31",
        "payroll_account": "70",
        "lines": [
            {"source_line_id": "deduction-1", "employee": "E-1", "department": "SALES",
             "kind": "employee_deduction", "liability_account": "68.1", "amount_byn": "13.00",
             "dimensions": {"contract": "STAFF"},
             "evidence": "Проверенный расчёт удержания по работнику E-1"},
            {"source_line_id": "contribution-1", "employee": "E-1", "department": "SALES",
             "kind": "employer_contribution", "liability_account": "69", "cost_account": "26",
             "amount_byn": "34.00", "dimensions": {"contract": "STAFF"},
             "evidence": "Проверенный расчёт взноса по работнику E-1"},
        ],
    })


async def seed_statutory_book(factory, pg_book):
    async with factory() as session:
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.account','id'), "
            "(SELECT max(id) FROM accounting.account))"
        ))
        session.add_all([
            Account(organization_id=pg_book[0], code="26", title="Synthetic contribution cost",
                    category="expense", valid_from=date(2026, 1, 1),
                    required_dimensions=["employee", "department"],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="68.1", title="Synthetic withholding payable",
                    category="liability", valid_from=date(2026, 1, 1),
                    required_dimensions=["employee", "department"],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="69", title="Synthetic contribution payable",
                    category="liability", valid_from=date(2026, 1, 1),
                    required_dimensions=["employee", "department"],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic"),
            Account(organization_id=pg_book[0], code="70", title="Synthetic payroll payable",
                    category="liability", valid_from=date(2026, 1, 1),
                    required_dimensions=["employee", "department"],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic"),
        ])
        await session.commit()


async def test_statutory_import_is_atomic_replayable_and_immutable(pg_factory, pg_book):
    await seed_statutory_book(pg_factory, pg_book)
    data = statutory_input(pg_book[1])

    async with pg_factory() as session:
        preview = await prepare_payroll_statutory(session, pg_book[0], "2026-10", data)
        assert preview["status"] == "reviewed_verified_payroll_statutory"
        assert preview["statutory_payroll_certified"] is False
        assert preview["deductions_and_contributions_available"] is True
        confirmed = PayrollStatutoryConfirmInput.model_validate({
            **data.model_dump(mode="json"), "digest": preview["digest"],
        })

    async def confirm_once():
        async with pg_factory() as session:
            try:
                entry = await confirm_payroll_statutory(
                    session, pg_book[0], "2026-10", confirmed, "tester"
                )
                await session.commit()
                return entry.id
            except BaseException:
                await session.rollback()
                raise

    first, second = await asyncio.gather(confirm_once(), confirm_once())
    assert first == second

    async with pg_factory() as session:
        receipt = await session.get(PayrollStatutoryReceipt, first)
        entry = await session.get(Entry, first)
        assert receipt is not None and entry is not None
        assert receipt.source_document == data.source_document
        assert receipt.source_digest == data.source_digest
        assert receipt.digest == confirmed.digest
        assert entry.source == f"payroll:statutory:{pg_book[0]}:{data.source_document}"
        assert entry.operation == "payroll_statutory_import"
        lines = (await session.scalars(select(Line).where(Line.entry_id == first).order_by(Line.id))).all()
        assert [(line.account_code, line.side, str(line.amount)) for line in lines] == [
            ("70", "debit", "13.00"), ("68.1", "credit", "13.00"),
            ("26", "debit", "34.00"), ("69", "credit", "34.00"),
        ]
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.operation == "payroll_statutory_import")) == 1
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "UPDATE accounting.payroll_statutory_receipt SET actor='forged' WHERE entry_id=:entry"
            ), {"entry": first})
        await session.rollback()


async def test_statutory_entry_requires_receipt_at_transaction_end(pg_factory, pg_book):
    await seed_statutory_book(pg_factory, pg_book)
    async with pg_factory() as session:
        forged = PostingInput(
            source=f"payroll:statutory:{pg_book[0]}:missing-receipt", source_version=1,
            operation="payroll_statutory_import", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=pg_book[1],
            rule_version="verified-payroll-statutory-v1:" + "c" * 64,
            explanation="Missing statutory receipt", lines=[
                LineInput(account="70", side="debit", amount="1.00",
                          dimensions={"employee": "E-1", "department": "SALES"}),
                LineInput(account="68.1", side="credit", amount="1.00",
                          dimensions={"employee": "E-1", "department": "SALES"}),
            ],
        )
        await service.post(session, pg_book[0], forged, "tester", payroll_statutory_import=True)
        with pytest.raises(DBAPIError, match="requires its complete source receipt"):
            await session.commit()
        await session.rollback()
