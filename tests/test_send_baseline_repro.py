"""Regression for the baseline false-positive send; historical result saved in evidence."""

from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.sales.models import Deal, DealDocument, Message


async def test_legacy_action_cannot_report_sent_without_recipient_or_transport(
    api, session, monkeypatch
):
    import smtplib

    def forbidden(*args, **kwargs):
        raise AssertionError("No SMTP call is expected in the historical implementation")

    monkeypatch.setattr(smtplib, "SMTP", forbidden)
    deal = Deal(number="SEND-BASELINE", title="Synthetic", counterparty="Test only")
    session.add(deal)
    await session.flush()
    session.add_all(
        [
            DealDocument(deal_id=deal.id, kind="invoice", number="INV-BASE", status="posted"),
            DealDocument(deal_id=deal.id, kind="contract", number="CON-BASE", status="posted"),
        ]
    )
    await session.commit()
    response = await api.post(f"/sales/deals/{deal.id}/send-package")
    assert response.status_code == 409, response.text
    assert (await session.scalars(select(Message))).first() is None
    assert (await session.scalars(select(OutboxEvent))).first() is None
