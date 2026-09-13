"""Adversarial perturbations of real WMS/PostgreSQL receipt acceptance tests."""

# ruff: noqa: F811
from sqlalchemy import text

from modules.accounting import shipment_commands, shipment_preview
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import (
    test_late_inventory_change_in_same_transaction_invalidates_receipt as late_inventory_case,
)
from tests.accounting.test_shipment_receipt_postgres import (
    test_self_consistent_forged_manifest_rejected_by_sql as forged_manifest_case,
)
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


async def test_null_commercial_values_cannot_hide_missing_revenue(physical_pg, monkeypatch):
    original_dump = shipment_preview.ShipmentPlanInput.model_dump

    def malformed_dump(self, *args, **kwargs):
        result = original_dump(self, *args, **kwargs)
        for line in result["commercial_lines"]:
            line["net_amount"] = None
            line["vat_rate"] = None
        return result

    # Simulate a faulty serializer after application validation; SQL must reject
    # the self-consistent cost-only package even when JSON contains nulls.
    monkeypatch.setattr(shipment_preview.ShipmentPlanInput, "model_dump", malformed_dump)
    await forged_manifest_case(physical_pg, monkeypatch, "commercial_omission")


async def test_early_constraint_check_cannot_exhaust_late_cost_protection(physical_pg, monkeypatch):
    original_confirm = shipment_commands.confirm

    async def check_early(session, *args, **kwargs):
        result = await original_confirm(session, *args, **kwargs)
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        return result

    monkeypatch.setattr(shipment_commands, "confirm", check_early)
    await late_inventory_case(physical_pg)
