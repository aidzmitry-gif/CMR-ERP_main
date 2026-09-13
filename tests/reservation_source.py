"""Real owned invoice setup for warehouse event integration tests."""
from datetime import datetime
from types import SimpleNamespace

from core.services.eventbus import EventContext
from modules.accounting.gateway import AccountingService
from modules.accounting.models import Organization
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.documents import digest
from modules.sales.models import Deal, DealDocument
from modules.sales.reservation_source import SalesReservationSource


def event_context(session):
    return EventContext(session, SimpleNamespace(sales_source=SalesReservationSource(), accounting=AccountingService()))


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
