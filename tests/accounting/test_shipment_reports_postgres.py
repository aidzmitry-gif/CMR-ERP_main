"""Shipment recognition reconciles ledger reports without pretending month acceptance."""
# ruff: noqa: F811
from decimal import Decimal

import pytest
from sqlalchemy import select

from modules.accounting import models, reports, service, shipment_commands, shipment_preview
from modules.accounting.schemas import CloseInput
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


async def test_acquisition_is_stock_and_shipment_recognizes_expense_with_balanced_reports(physical_pg):
    factory, org, act, data = await prepare_accounting(physical_pg)
    start = data.posting_date.replace(day=1)
    month = data.posting_date.strftime("%Y-%m")
    evidence = {key: "Synthetic fixture check, not accountant acceptance" for key in service.CLOSE_STEPS}
    async with factory() as session:
        before = await reports.report(session, org, start, data.posting_date)
        assert before["pnl"] == {"income": "0.00", "expenses": "0.00", "profit": "0.00"}
        assert before["balance"]["assets"] == "10.00"
        assert before["pending_documents"] == 1
        period = await service.period_for(session, org, month)
        with pytest.raises(service.AccountingError, match="Unposted primary documents"):
            await service.close_period(session, org, month, CloseInput(expected_generation=period.generation, evidence=evidence), "allocator")
        await session.rollback()

    # Internal confirmation deliberately remains separate from any public API.
    async with factory() as session:
        plan = await shipment_preview.prepare(session, org, act, data)
        saved = await shipment_commands.confirm(session, org, act, data, plan["basis_digest"], "allocator")
        anchor = saved.anchor_entry_id
        await session.commit()

    async with factory() as session:
        after = await reports.report(session, org, start, data.posting_date)
        assert after["pnl"] == {"income": "20.00", "expenses": "3.33", "profit": "16.67"}
        assert after["balance"] == {"assets": "30.67", "liabilities": "14.00", "equity": "0.00", "current_result": "16.67", "difference": "0.00"}
        assert after["cashflow"]["closing"] == "0.00"
        assert after["pending_documents"] == 0
        assert after["status"] == "preliminary" and after["statutory_certified"] is False
        stock = [row for row in after["trial_balance"] if row["account"] == "41.2"]
        assert len(stock) == 1
        assert stock[0]["closing"] == "6.67" and stock[0]["quantity_closing"] == "2.000000"
        assert sum(Decimal(row["debit"]) for row in after["trial_balance"]) == sum(Decimal(row["credit"]) for row in after["trial_balance"])
        control = await session.scalar(select(models.SourceControl).where(models.SourceControl.source == plan["source"]))
        assert control.entry_id == anchor
        period = await service.period_for(session, org, month)
        with pytest.raises(service.AccountingError, match="Normative basis must be verified"):
            await service.close_period(session, org, month, CloseInput(expected_generation=period.generation, evidence=evidence), "allocator")
        await session.rollback()

    # Exact replay cannot consume stock or increase profit again.
    async with factory() as session:
        repeated = await shipment_commands.confirm(session, org, act, data, plan["basis_digest"], "allocator")
        assert repeated.anchor_entry_id == anchor
        await session.commit()
    async with factory() as session:
        assert await reports.report(session, org, start, data.posting_date) == after
