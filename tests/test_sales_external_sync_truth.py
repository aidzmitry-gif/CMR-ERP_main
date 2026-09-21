"""CRM document issuance never fabricates an external 1C success."""
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock

from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.sales.models import Deal, DealDocument
from modules.sales.routes import _post_document_to_1c


class VerifiedOutboundGateway:
    outbound_document_source_available = True
    outbound_document_source_reason = "verified test gateway"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def post_document(self, doc_type: str, payload: dict) -> dict:
        self.calls.append((doc_type, payload))
        return {"posted": True, "ref": "external-verified-42"}


async def _document(session, number: str) -> DealDocument:
    deal = Deal(number=number, title="External truth", counterparty="Buyer")
    session.add(deal)
    await session.flush()
    doc = DealDocument(
        deal_id=deal.id,
        kind="order",
        number=f"ЗК-{number}",
        amount=Decimal("42.00"),
        status="draft",
        issued_at=datetime(2026, 9, 21, 12, 0),
        snapshot_json={
            "seller": {"unp": "190000001", "account": "BY00TEST"},
            "buyer": {"unp": "190000002", "name": "Buyer"},
        },
    )
    session.add(doc)
    await session.flush()
    return doc


async def test_default_gateway_records_unavailable_without_calling_outbound(api, session, monkeypatch):
    core = api._transport.app.state.core
    gateway = core.services.onec
    post_document = AsyncMock(wraps=gateway.post_document)
    monkeypatch.setattr(gateway, "post_document", post_document)
    doc = await _document(session, "OUT-LOCAL")

    await _post_document_to_1c(core, session, doc, "Buyer")

    post_document.assert_not_awaited()
    assert doc.status == "posted" and doc.onec_ref is None
    event = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "sales.document.posted")
    )).scalars().one()
    assert event.payload["onec_ref"] is None
    assert event.payload["onec_sync_state"] == "unavailable"
    assert event.payload["onec_sync_reason"] == gateway.outbound_document_source_reason


async def test_verified_outbound_gateway_is_the_only_source_of_external_reference(api, session):
    core = api._transport.app.state.core
    gateway = VerifiedOutboundGateway()
    core.services.onec = gateway
    doc = await _document(session, "OUT-TRUTH")

    await _post_document_to_1c(core, session, doc, "Buyer")

    assert gateway.calls == [("order", {"number": "ЗК-OUT-TRUTH", "counterparty": "Buyer", "amount": "42.00"})]
    assert doc.status == "posted"
    assert doc.onec_ref == "external-verified-42"
    event = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "sales.document.posted")
    )).scalars().one()
    assert event.payload["onec_ref"] == "external-verified-42"
    assert event.payload["onec_sync_state"] == "synced"
    assert event.payload["onec_sync_reason"] is None
