# ruff: noqa: F811 -- imported pytest fixtures
import pytest

from modules.accounting import service, shipment_commands, shipment_preview
from modules.accounting.late_cost_sources import verified_shipment_entries
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


async def test_late_cost_uses_verified_whole_shipment_package(physical_pg):
    factory, org, act, data = await prepare_accounting(physical_pg, full=True)
    async with factory() as session:
        plan = await shipment_preview.prepare(session, org, act, data)
        saved = await shipment_commands.confirm(session, org, act, data, plan["basis_digest"], "allocator")
        await session.commit()
        ids = {page["entry_id"] for page in saved.snapshot["pages"]}
    async with factory() as session:
        result = await verified_shipment_entries(session, org, ids)
        assert set(result) == ids
        assert all(posting.operation == "inventory_sale" for posting in result.values())
        assert any(line.quantity is not None and line.side == "credit" for posting in result.values() for line in posting.lines)
        with pytest.raises(service.AccountingError, match="no verified shipment package"):
            await verified_shipment_entries(session, org, ids | {99999999})
