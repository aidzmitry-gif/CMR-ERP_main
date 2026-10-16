"""PostgreSQL evidence for paid and warranty repair accounting packages."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import repair_accounting
from modules.accounting.models import Account, Entry, Line, RepairAccountingReceipt
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def seed_repair_accounts(factory, pg_book):
    async with factory() as session:
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.account','id'), "
            "(SELECT max(id) FROM accounting.account))"
        ))
        session.add_all([
            Account(organization_id=pg_book[0], code="10.1", title="Synthetic repair materials",
                    category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic repair evidence"),
            Account(organization_id=pg_book[0], code="20", title="Synthetic warranty repair cost",
                    category="expense", valid_from=date(2026, 1, 1), required_dimensions=[],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic repair evidence"),
            Account(organization_id=pg_book[0], code="90.2", title="Synthetic repair cost",
                    category="expense", valid_from=date(2026, 1, 1), required_dimensions=[],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic repair evidence"),
        ])
        await session.commit()


def paid_command(request_key: str = "00000000-0000-0000-0000-000000000201"):
    return repair_accounting.RepairAccountingInput.model_validate({
        "request_key": request_key, "service_request_id": 42,
        "source_document": "service-request:42", "source_version": 1,
        "source_digest": "a" * 64, "serial_number": "SN-100",
        "owner_type": "customer", "owner_reference": "customer-7", "coverage": "paid",
        "counterparty_reference": "customer-7", "policy_id": 1, "posting_date": "2026-10-31",
        "service_amount_byn": "150.00", "settlement_account": "62", "revenue_account": "90.1",
        "source_evidence": "Акт ремонта, серийный номер и подтверждение клиента проверены бухгалтером",
        "lines": [
            {"source_line_id": "part-1", "kind": "material", "material_owner": "own",
             "description": "Запчасть", "amount_byn": "50.00", "debit_account": "90.2",
             "credit_account": "10.1", "dimensions": {},
             "evidence": "Накладная на запчасть и акт установки проверены"},
            {"source_line_id": "customer-part", "kind": "material", "material_owner": "customer",
             "description": "Деталь клиента", "amount_byn": "0.00", "dimensions": {},
             "evidence": "Акт передачи имущества клиента без оприходования проверен"},
        ],
    })


async def test_paid_repair_is_atomic_replayable_and_customer_property_is_off_balance(pg_factory, pg_book):
    await seed_repair_accounts(pg_factory, pg_book)
    data = paid_command()
    async with pg_factory() as session:
        preview = await repair_accounting.prepare_repair(session, pg_book[0], "2026-10", data)
        assert preview["status"] == "reviewed_repair"
        assert preview["financial_result"] == {
            "service_amount_byn": "150.00", "cost_amount_byn": "50.00",
            "gross_result_byn": "100.00", "customer_material_lines": ["customer-part"],
        }
        confirmed = repair_accounting.RepairAccountingConfirmInput.model_validate({
            **data.model_dump(mode="json"), "digest": preview["digest"],
        })

    async def confirm_once():
        async with pg_factory() as session:
            try:
                entry = await repair_accounting.confirm_repair(
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
        receipt = await session.get(RepairAccountingReceipt, first)
        entry = await session.get(Entry, first)
        assert receipt is not None and entry is not None
        assert receipt.coverage == "paid" and receipt.owner_type == "customer"
        assert receipt.source["customer_material_lines"] == ["customer-part"]
        lines = (await session.scalars(select(Line).where(Line.entry_id == first).order_by(Line.id))).all()
        assert [(line.account_code, line.side, str(line.amount), line.dimensions) for line in lines] == [
            ("90.2", "debit", "50.00", {"owner": "customer:customer-7", "serial": "SN-100", "order": "42", "counterparty": "customer-7"}),
            ("10.1", "credit", "50.00", {"owner": "customer:customer-7", "serial": "SN-100", "order": "42", "counterparty": "customer-7"}),
            ("62", "debit", "150.00", {"owner": "customer:customer-7", "serial": "SN-100", "order": "42", "counterparty": "customer-7"}),
            ("90.1", "credit", "150.00", {"owner": "customer:customer-7", "serial": "SN-100", "order": "42", "counterparty": "customer-7"}),
        ]
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.operation == "repair_service")) == 1
        assert await session.scalar(select(func.count()).select_from(RepairAccountingReceipt)) == 1
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "UPDATE accounting.repair_accounting_receipt SET actor='forged' WHERE entry_id=:entry"
            ), {"entry": first})
        await session.rollback()

    async with pg_factory() as session:
        forged = RepairAccountingReceipt(
            entry_id=first, organization_id=pg_book[0], service_request_id=42, month="2026-10",
            request_key=str(uuid4()), source_version=1, source_digest="b" * 64,
            serial_number="SN-100", owner_type="customer", owner_reference="customer-7",
            coverage="paid", command={"request_key": str(uuid4()), "service_request_id": 42,
                                      "source_version": 1, "source_digest": "b" * 64,
                                      "serial_number": "SN-100", "owner_type": "customer",
                                      "owner_reference": "customer-7", "coverage": "paid", "lines": []},
            source={"scope": "repair_accounting", "service_request_id": 42, "source_digest": "b" * 64,
                    "serial_number": "SN-100", "owner_type": "customer", "owner_reference": "customer-7",
                    "coverage": "paid"},
            posting={}, financial_result={}, digest="0" * 64, actor="tester",
        )
        session.add(forged)
        with pytest.raises(DBAPIError, match="does not match"):
            await session.flush()
        await session.rollback()


async def test_warranty_repair_posts_cost_without_revenue(pg_factory, pg_book):
    await seed_repair_accounts(pg_factory, pg_book)
    data = repair_accounting.RepairAccountingInput.model_validate({
        **paid_command("00000000-0000-0000-0000-000000000202").model_dump(mode="json"),
        "service_request_id": 43, "source_document": "service-request:43", "source_digest": "c" * 64,
        "coverage": "warranty", "counterparty_reference": None, "service_amount_byn": "0.00",
        "settlement_account": None, "revenue_account": None,
        "lines": [{"source_line_id": "labor-1", "kind": "labor", "material_owner": "own",
                    "description": "Гарантийная работа", "amount_byn": "80.00", "debit_account": "20",
                    "credit_account": "60", "dimensions": {},
                    "evidence": "Наряд гарантийного ремонта проверен бухгалтером"}],
    })
    async with pg_factory() as session:
        preview = await repair_accounting.prepare_repair(session, pg_book[0], "2026-10", data)
        confirmed = repair_accounting.RepairAccountingConfirmInput.model_validate({
            **data.model_dump(mode="json"), "digest": preview["digest"],
        })
        entry = await repair_accounting.confirm_repair(
            session, pg_book[0], "2026-10", confirmed, "tester"
        )
        await session.commit()
        assert entry.operation == "repair_service"
        rows = (await session.scalars(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))).all()
        assert [(line.account_code, line.side, str(line.amount)) for line in rows] == [
            ("20", "debit", "80.00"), ("60", "credit", "80.00"),
        ]
        assert await session.scalar(select(RepairAccountingReceipt.coverage).where(
            RepairAccountingReceipt.entry_id == entry.id)) == "warranty"
