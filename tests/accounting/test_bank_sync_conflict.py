from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from core.domain.models import OutboxEvent
from modules.finance import bank_ingest
from modules.finance.models import BankTransaction, Payment, PaymentAllocation
from modules.finance.routes import bank_sync


@pytest.mark.parametrize("failure", ["ingest", "commit", "identity"])
async def test_unconfirmed_bank_channel_refuses_before_armed_conflicts(monkeypatch, failure):
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    sync = AsyncMock(return_value={"imported": 1})
    conflict = IntegrityError("synthetic", {}, ValueError("synthetic constraint"))
    if failure == "commit":
        session.commit.side_effect = conflict
    else:
        sync.side_effect = bank_ingest.BankSourceIdentityConflict("Existing source") if failure == "identity" else conflict
    monkeypatch.setattr(bank_ingest, "sync_incoming", sync)
    bank = SimpleNamespace(fetch_incoming=AsyncMock())
    core = SimpleNamespace(services=SimpleNamespace(bank=bank), event_bus=None)
    with pytest.raises(HTTPException) as raised:
        await bank_sync(core, session, organization_id=1)
    assert raised.value.status_code == 503
    assert "принадлежность канала выписки ещё не подтверждена" in raised.value.detail
    sync.assert_not_awaited()
    bank.fetch_incoming.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


async def test_legacy_source_collision_rolls_back_preceding_incoming_row(session):
    original = BankTransaction(ext_id="SYN-FULL-ROW", amount=Decimal("10.00"), currency="BYN",
                               source_provider="synthetic", source_external_id="SYN-COLLISION")
    payment = Payment(ref="SYN-UNCHANGED", amount=Decimal("10.00"), status="pending")
    session.add_all([original, payment])
    await session.commit()
    bank = SimpleNamespace(fetch_incoming=AsyncMock(return_value=[
        {"ext_id": "SYN-NEW", "amount": "5.00", "currency": "BYN"},
        {"ext_id": "SYN-COLLISION", "amount": "10.00", "currency": "BYN"},
    ]))
    bus = SimpleNamespace(publish=AsyncMock())
    with pytest.raises(bank_ingest.BankSourceIdentityConflict, match="полной выписки"):
        await bank_ingest.sync_incoming(session, bank, bus)
    await session.rollback()
    bank.fetch_incoming.assert_awaited_once()
    bus.publish.assert_not_awaited()
    rows = (await session.execute(select(BankTransaction))).scalars().all()
    assert [(row.ext_id, row.source_provider, row.source_external_id, row.amount) for row in rows] == [
        ("SYN-FULL-ROW", "synthetic", "SYN-COLLISION", Decimal("10.00")),
    ]
    payments = (await session.execute(select(Payment))).scalars().all()
    assert [(row.ref, row.amount, row.status) for row in payments] == [
        ("SYN-UNCHANGED", Decimal("10.00"), "pending"),
    ]
    assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
