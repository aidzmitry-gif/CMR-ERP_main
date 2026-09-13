from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401
from tests.test_invoice_late_reservation import late_reservation_flow


async def test_pg_later_reservation(issuance_pg):  # noqa: F811
    api, factory = issuance_pg
    async with factory() as session:
        ids, doc_id, digest = await late_reservation_flow(api, session, concurrent=True)
    from sqlalchemy import func, select

    from core.services.eventbus import OutboxEventBus
    from modules.wms.events import on_stock_reserved
    from modules.wms.models import ReservationVersion, StockMovement, Task

    bus = OutboxEventBus()
    bus.subscribe("sales.stock.reserved", on_stock_reserved)
    services = api._transport.app.state.core.services
    assert await bus.relay_pending(factory, services, event_types=("sales.stock.reserved",)) == 1
    assert await bus.relay_pending(factory, services, event_types=("sales.stock.reserved",)) == 0
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Task)) == 1
        assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 1
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 1
    from datetime import date
    from uuid import uuid4

    from modules.wms.invoice_reservations import invoice_availability
    from modules.wms.invoice_shipments import PhysicalShipmentAct

    endpoint = f"/wms/organizations/{ids['org']}/invoices/{doc_id}/physical-shipments"
    identity = {"expected_version": 1, "expected_content_sha256": digest}
    for remaining in ("1.00", "0.00"):
        response = await api.post(endpoint + "/preview", json=identity)
        assert response.status_code == 200, response.text
        basis = response.json()
        body = {**identity, "source_key": str(uuid4()), "operation_date": date.today().isoformat(),
                "expected_reservation_digest": basis["reservation_digest"],
                "expected_remaining_digest": basis["remaining_digest"],
                "expected_physical_digest": basis["physical_digest"],
                "evidence": "Synthetic partial on-order shipment",
                "lines": [{"line_no": 1, "warehouse": "W", "qty": "1.00"}]}
        created = await api.post(endpoint, json=body)
        assert created.status_code == 201, created.text
        replay = await api.post(endpoint, json=body)
        assert replay.status_code == 201 and replay.json() == created.json(), replay.text
        async with factory() as session:
            from core.services.auth import CurrentUser
            await services.accounting.source_member(session, ids["org"], CurrentUser("issuer", ["director"]))
            available = await invoice_availability(session, ids["org"], [ids["code"]])
            row = next(r for r in available["rows"] if r["warehouse"] == "W")
            assert row["physical"] == remaining and row["reserved"] == remaining and row["free"] == "0.00"
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(PhysicalShipmentAct)) == 2
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == 3
