"""Priority intake relay runs before the regular outbox consumer."""
import asyncio
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.domain.models import AuditLog, IntakeIdentity, IntakeReceipt, OutboxEvent
from core.runtime import app as runtime_app
from modules.leads.models import Lead


class _FakeSession:
    def __init__(self, name: str, order: list[str]) -> None:
        self.name = name
        self.order = order
        self.rollback_count = 0
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def rollback(self):
        self.rollback_count += 1
        self.order.append(f"rollback:{self.name}")

    async def commit(self):
        self.commit_count += 1
        self.order.append(f"commit:{self.name}")


class _FakeFactory:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.sessions: list[_FakeSession] = []

    def __call__(self):
        session = _FakeSession(str(len(self.sessions)), self.order)
        self.sessions.append(session)
        return session


class _PriorityFailingBus:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.calls: list[tuple[_FakeSession, tuple[str, ...] | None]] = []

    async def relay_once(self, session, ctx, *, event_types=None):
        self.calls.append((session, event_types))
        self.order.append("priority" if event_types is not None else "general")
        if event_types is not None:
            raise RuntimeError("priority poison")
        return 0


class _Approvals:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    async def escalate_once(self, session):
        self.order.append("approvals")


async def test_background_priority_failure_rolls_back_and_general_still_runs(monkeypatch, caplog):
    order: list[str] = []
    factory = _FakeFactory(order)
    bus = _PriorityFailingBus(order)
    services = SimpleNamespace(
        db=SimpleNamespace(session_factory=factory),
        event_bus=bus,
        approvals=_Approvals(order),
    )

    async def hook(session, services):
        order.append("hook")

    sleeps = 0

    async def one_tick(delay):
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(runtime_app.asyncio, "sleep", one_tick)
    with caplog.at_level(logging.ERROR, logger="aios.app"):
        with pytest.raises(asyncio.CancelledError):
            await runtime_app._background_loop(services, (hook,))

    assert len(factory.sessions) == 4
    assert factory.sessions[0] is not factory.sessions[1]
    assert factory.sessions[0].rollback_count == 1
    assert [event_types for _, event_types in bus.calls] == [
        ("intake.lead.received",), None,
    ]
    assert order[:4] == ["priority", "rollback:0", "general", "approvals"]
    assert "hook" in order
    assert any(record.getMessage() == "priority intake relay error" for record in caplog.records)


async def test_background_priority_cancellation_propagates(monkeypatch):
    order: list[str] = []
    factory = _FakeFactory(order)

    class _CancellingBus:
        async def relay_once(self, session, ctx, *, event_types=None):
            assert event_types == ("intake.lead.received",)
            raise asyncio.CancelledError

    services = SimpleNamespace(
        db=SimpleNamespace(session_factory=factory),
        event_bus=_CancellingBus(),
        approvals=_Approvals(order),
    )

    async def one_tick(delay):
        return None

    monkeypatch.setattr(runtime_app.asyncio, "sleep", one_tick)
    with pytest.raises(asyncio.CancelledError):
        await runtime_app._background_loop(services)
    assert len(factory.sessions) == 1


async def test_priority_intake_precedes_telephony_poison_and_is_idempotent(
    session, services, monkeypatch, caplog
):
    """The priority pass delivers intake while a poison general event stays pending."""
    identity = IntakeIdentity(namespace="microchips.by", source_id="form:3:result:2302")
    session.add(identity)
    await session.flush()
    receipt = IntakeReceipt(
        id="r" * 32,
        identity_id=identity.id,
        namespace=identity.namespace,
        delivery_id="form:3:result:2302",
        payload_sha256="0" * 64,
        payload={
            "lead": {
                "name": "Покупатель",
                "company": "ООО Тест",
                "phone": "+375291234567",
                "email": "buyer@example.invalid",
                "region": "Минск",
                "product": "Микросхема",
                "message": "Нужна цена",
            },
            "files": [],
        },
        files=[],
        status="queued",
    )
    session.add_all([
        receipt,
        OutboxEvent(
            event_type="telephony.agent.received",
            payload={"entity_ref": "telephony:poison"},
        ),
        OutboxEvent(
            event_type="intake.lead.received",
            payload={"receipt_id": receipt.id},
        ),
    ])
    await session.commit()

    async def poison(payload, ctx):
        ctx.session.add(AuditLog(action="test.telephony.partial", detail=payload))
        await ctx.session.flush()
        raise RuntimeError("telephony agent_ext is invalid")

    services.event_bus.subscribe("telephony.agent.received", poison)
    services.db.session_factory = async_sessionmaker(session.bind, expire_on_commit=False)

    sleeps = 0

    async def two_ticks(delay):
        nonlocal sleeps
        sleeps += 1
        if sleeps > 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(runtime_app.asyncio, "sleep", two_ticks)
    with caplog.at_level(logging.ERROR, logger="aios.app"):
        with pytest.raises(asyncio.CancelledError):
            await runtime_app._background_loop(services)

    assert any(record.getMessage() == "background loop error" for record in caplog.records)
    async with services.db.session_factory() as check:
        saved_receipt = await check.get(IntakeReceipt, receipt.id)
        leads = (await check.execute(select(Lead))).scalars().all()
        telephony = (await check.execute(select(OutboxEvent).where(
            OutboxEvent.event_type == "telephony.agent.received",
        ))).scalar_one()
        partial_audit = await check.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "test.telephony.partial",
        ))
        intake_audits = await check.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "intake.lead.received",
        ))

    assert saved_receipt is not None and saved_receipt.status == "delivered"
    assert len(leads) == 1 and leads[0].email == "buyer@example.invalid"
    assert telephony.processed_at is None
    assert partial_audit == 0
    assert intake_audits == 1
