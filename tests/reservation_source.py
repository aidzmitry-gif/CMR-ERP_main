"""Real owned invoice setup for warehouse event integration tests."""
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select

from core.services.eventbus import EventContext
from modules.accounting.gateway import AccountingService
from modules.accounting.models import Organization
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.documents import digest
from modules.sales.models import Deal, DealDocument
from modules.sales.reservation_source import SalesReservationSource
from modules.wms.models import WarehouseDirectory


def event_context(session):
    return EventContext(session, SimpleNamespace(sales_source=SalesReservationSource(), accounting=AccountingService()))


async def issued_invoice_for_shipments(api, session, *, wms_enabled=False):
    """Use the trusted issuance flow when the caller verifies the immutable buyer."""
    from tests.test_invoice_issuance import command, create, seed

    ids, base = await seed(api, session, qty="5")
    if wms_enabled:
        warehouse = await session.scalar(select(WarehouseDirectory).where(
            WarehouseDirectory.organization_id == ids["org"],
            WarehouseDirectory.name == "W", WarehouseDirectory.is_active.is_(True),
        ))
        assert warehouse is not None and warehouse.prohibit_negative_stock is True
        warehouse.wms_enabled = True
        await session.commit()
    payload, _ = await command(api, ids, base)
    response = await create(api, ids, payload)
    assert response.status_code == 201, response.text
    facts = await SalesReservationSource().invoice_reservation(
        session, response.json()["document"]["id"],
    )
    return ids["org"], facts


async def invoice(session, document_id, items, organization_id=777, *, released=False):
    if await session.get(Organization, organization_id) is None:
        session.add(Organization(id=organization_id, name=f"Synthetic book {organization_id}",
                                 unp=f"{organization_id:09d}"))
        await session.flush()
    deal = Deal(number=f"SYN-RES-{document_id}", title="Synthetic", counterparty="Synthetic")
    session.add(deal)
    await session.flush()
    doc = DealDocument(id=document_id, deal_id=deal.id, kind="invoice", number=f"SYN-{document_id}",
                       amount="100", status="posted", content_sha256=digest("Synthetic"), original_html="Synthetic",
                       issued_at=datetime(2026, 9, 1), reserve_status="released" if released else "reserved",
                       snapshot_json={"items": items})
    session.add_all([doc, DealOwnership(deal_id=deal.id, organization_id=organization_id,
                                       snapshot={}, evidence="Synthetic", actor="tester")])
    await session.flush()
    return doc
