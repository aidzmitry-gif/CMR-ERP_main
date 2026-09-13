"""PostgreSQL evidence for explicit input/output VAT register packages."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import input_vat_register, output_vat_register, service
from modules.accounting.models import Account, InputVatRegisterEntry, Line, OutputVatRegisterEntry
from modules.accounting.schemas import PostingInput
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def seed_vat_accounts(factory, pg_book):
    async with factory() as session:
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.account','id'), "
            "(SELECT max(id) FROM accounting.account))"
        ))
        session.add_all([
            Account(organization_id=pg_book[0], code="18.1", title="Synthetic input VAT",
                    category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic VAT evidence"),
            Account(organization_id=pg_book[0], code="90.2", title="Synthetic accrued output VAT",
                    category="expense", valid_from=date(2026, 1, 1), required_dimensions=[],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic VAT evidence"),
            Account(organization_id=pg_book[0], code="68.2", title="Synthetic VAT payable",
                    category="liability", valid_from=date(2026, 1, 1), required_dimensions=[],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic VAT evidence"),
        ])
        await session.commit()


def input_posting(policy_id: int) -> PostingInput:
    return PostingInput.model_validate({
        "source": "vat:input:001", "source_version": 1, "operation": "manual",
        "document_date": "2026-10-01", "operation_date": "2026-10-01", "posting_date": "2026-10-01",
        "policy_id": policy_id, "rule_version": "synthetic-vat-v1", "explanation": "Synthetic input VAT",
        "lines": [
            {"account": "18.1", "side": "debit", "amount": "20.00"},
            {"account": "60", "side": "credit", "amount": "20.00"},
        ],
    })


def output_posting(policy_id: int) -> PostingInput:
    return PostingInput.model_validate({
        "source": "vat:output:001", "source_version": 1, "operation": "manual",
        "document_date": "2026-10-02", "operation_date": "2026-10-02", "posting_date": "2026-10-02",
        "policy_id": policy_id, "rule_version": "synthetic-vat-v1", "explanation": "Synthetic output VAT",
        "lines": [
            {"account": "90.2", "side": "debit", "amount": "20.00"},
            {"account": "68.2", "side": "credit", "amount": "20.00"},
        ],
    })


async def test_input_and_output_vat_registers_are_replayable_and_immutable(pg_factory, pg_book):
    await seed_vat_accounts(pg_factory, pg_book)
    async with pg_factory() as session:
        input_entry = await service.post(session, pg_book[0], input_posting(pg_book[1]), "tester")
        output_entry = await service.post(session, pg_book[0], output_posting(pg_book[1]), "tester")
        await session.commit()

    async with pg_factory() as session:
        input_line = await session.scalar(select(Line).where(
            Line.entry_id == input_entry.id, Line.account_code == "18.1", Line.side == "debit",
        ))
        output_line = await session.scalar(select(Line).where(
            Line.entry_id == output_entry.id, Line.account_code == "90.2", Line.side == "debit",
        ))
        output_credit_line = await session.scalar(select(Line).where(
            Line.entry_id == output_entry.id, Line.side == "credit",
        ))
        input_data = input_vat_register.InputVatRegisterInput.model_validate({
            "request_key": "00000000-0000-0000-0000-000000000301", "entry_id": input_entry.id,
            "line_id": input_line.id, "expected_entry_digest": input_entry.digest, "tax_period": "2026-10",
            "invoice_reference": "INV-IN-1", "eschf_identifier": "ЭСЧФ-IN-1",
            "deduction_status": "eligible", "eschf_status": "provided",
            "right_basis": "Проверены первичный документ и право на вычет по синтетической политике",
            "evidence": "Счёт-фактура и ЭСЧФ сверены бухгалтером",
        })
        output_data = output_vat_register.OutputVatRegisterInput.model_validate({
            "request_key": "00000000-0000-0000-0000-000000000302", "entry_id": output_entry.id,
            "line_id": output_line.id, "expected_entry_digest": output_entry.digest, "tax_period": "2026-10",
            "invoice_reference": "EXP-OUT-1", "tax_treatment": "zero_export",
            "eschf_identifier": None, "eschf_status": "pending",
            "treatment_basis": "Экспортная ставка требует подтверждённого пакета вывоза",
            "export_evidence": "Таможенная декларация и подтверждение вывоза сверены бухгалтером",
            "evidence": "Экспортные документы и основание ставки проверены бухгалтером",
        })
        input_preview = await input_vat_register.prepare_register(session, pg_book[0], input_data)
        output_preview = await output_vat_register.prepare_register(session, pg_book[0], output_data)
        input_confirmed = input_vat_register.InputVatRegisterConfirmInput.model_validate({
            **input_data.model_dump(mode="json"), "digest": input_preview["digest"],
        })
        output_confirmed = output_vat_register.OutputVatRegisterConfirmInput.model_validate({
            **output_data.model_dump(mode="json"), "digest": output_preview["digest"],
        })

    async def confirm_input():
        async with pg_factory() as session:
            try:
                row = await input_vat_register.confirm_register(session, pg_book[0], input_confirmed, "tester")
                await session.commit()
                return row.id
            except BaseException:
                await session.rollback()
                raise

    async def confirm_output():
        async with pg_factory() as session:
            try:
                row = await output_vat_register.confirm_register(session, pg_book[0], output_confirmed, "tester")
                await session.commit()
                return row.id
            except BaseException:
                await session.rollback()
                raise

    input_ids = await asyncio.gather(confirm_input(), confirm_input())
    output_ids = await asyncio.gather(confirm_output(), confirm_output())
    assert input_ids[0] == input_ids[1]
    assert output_ids[0] == output_ids[1]

    async with pg_factory() as session:
        input_row = await session.get(InputVatRegisterEntry, input_ids[0])
        output_row = await session.get(OutputVatRegisterEntry, output_ids[0])
        assert input_row is not None and input_row.deduction_status == "eligible"
        assert output_row is not None and output_row.tax_treatment == "zero_export"
        assert await session.scalar(select(func.count()).select_from(InputVatRegisterEntry)) == 1
        assert await session.scalar(select(func.count()).select_from(OutputVatRegisterEntry)) == 1
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "UPDATE accounting.input_vat_register_entry SET actor='forged' WHERE id=:id"
            ), {"id": input_ids[0]})
        await session.rollback()
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "DELETE FROM accounting.output_vat_register_entry WHERE id=:id"
            ), {"id": output_ids[0]})
        await session.rollback()

    async with pg_factory() as session:
        forged = OutputVatRegisterEntry(
            id=output_ids[0] + 1000, organization_id=pg_book[0], request_key=str(uuid4()),
            entry_id=output_entry.id, line_id=output_credit_line.id, source="vat:forged", source_version=1,
            entry_digest="0" * 64, posting_date=date(2026, 10, 2), tax_period="2026-10",
            amount="20.00", currency="BYN", side="credit", invoice_reference="FORGED",
            tax_treatment="standard", eschf_status="not_required", treatment_basis="Подделка основания для проверки guard",
            export_evidence=None, evidence="Подделанный пакет ЭСЧФ отклонён проверкой",
            command={"request_key": str(uuid4()), "entry_id": output_entry.id, "line_id": output_line.id,
                     "source_digest": "0" * 64, "tax_treatment": "standard", "eschf_status": "not_required"},
            digest="0" * 64, actor="tester",
        )
        session.add(forged)
        with pytest.raises(DBAPIError, match="does not match"):
            await session.commit()
        await session.rollback()
