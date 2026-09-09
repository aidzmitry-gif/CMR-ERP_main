from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from core.domain.models import AuditLog, OutboxEvent
from core.services import nbrb
from core.services.eventbus import EventContext, OutboxEventBus
from modules.finance.events import on_freight_cost, on_landed_cost
from modules.finance.models import Payment

DAY = date(2026, 9, 1)


def response(code="RUB", rate="3.1234", scale=100):
    return {"Cur_Abbreviation": code, "Date": DAY.isoformat() + "T00:00:00",
            "Cur_OfficialRate": rate, "Cur_Scale": scale}


async def seed(session, code="USD", rate="3.1234", scale=1):
    value = nbrb.parse_quote(response(code, rate, scale), code, DAY)
    session.add(AuditLog(actor="nbrb", action=nbrb.ACTION,
                         entity_ref=f"nbrb:{code}:{DAY}", detail=value))
    await session.flush()


async def test_nominal_cache_and_decimal(session):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.params["ondate"] == str(DAY)
        return httpx.Response(200, json=response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await nbrb.quote(session, "rub", DAY, client=client)
        assert result["rate"] == "0.031234"
        assert await nbrb.quote(session, "RUB", DAY, client=client) == result
    assert len(calls) == 1
    amount, _ = await nbrb.convert(session, "10000", "RUB", DAY)
    assert amount == Decimal("312.34")


@pytest.mark.parametrize("field,value", [("Cur_Scale", 0), ("Cur_Scale", -1),
    ("Cur_Scale", 1.5), ("Cur_OfficialRate", None), ("Cur_OfficialRate", "NaN"),
    ("Cur_OfficialRate", "Infinity"), ("Cur_Abbreviation", "USD"), ("Date", "2026-08-31")])
def test_reject_malformed(field, value):
    data = response()
    data[field] = value
    with pytest.raises(nbrb.RateUnavailable):
        nbrb.parse_quote(data, "RUB", DAY)


async def test_outage_does_not_cache(session):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(503)
    )) as client:
        with pytest.raises(nbrb.RateUnavailable):
            await nbrb.quote(session, "USD", DAY, client=client)
    assert not (await session.execute(select(AuditLog))).scalars().all()


async def test_payment_api_preserves_original_and_quote(api, session):
    await seed(session)
    result = await api.post("/finance/payments", json={
        "ref": "test", "amount": "100", "currency": "USD", "operation_date": str(DAY)
    })
    assert result.status_code == 201, result.text
    assert result.json()["amount"] == "312.34"
    assert result.json()["amount_orig"] == "100.00"
    assert result.json()["currency"] == "USD"
    audit = (await session.execute(select(AuditLog).where(
        AuditLog.action == "finance.fx.applied"
    ))).scalar_one()
    assert audit.detail["quote"]["date"] == str(DAY)


async def test_foreign_payment_requires_date(api):
    result = await api.post("/finance/payments", json={"ref": "test", "amount": "1", "currency": "USD"})
    assert result.status_code == 422


async def test_relay_uses_event_creation_date(session):
    await seed(session)
    bus = OutboxEventBus()
    bus.subscribe("test.freight", on_freight_cost)
    session.add(OutboxEvent(event_type="test.freight", created_at=datetime(2026, 9, 1, 8),
                            payload={"amount": "100", "currency": "USD", "ref": "old"}))
    await session.commit()
    await bus.relay_once(session, EventContext(session, SimpleNamespace(event_bus=bus)))
    payment = (await session.execute(select(Payment))).scalar_one()
    assert payment.amount == Decimal("312.34")


async def test_missing_event_date_does_not_silently_drop(session):
    with pytest.raises(nbrb.RateUnavailable):
        await on_freight_cost({"amount": "1", "currency": "USD"},
                              EventContext(session, SimpleNamespace()))
    assert not (await session.execute(select(Payment))).scalars().all()


async def test_byn_landed_is_never_converted_twice(session):
    await on_landed_cost({"total_landed_byn": "100", "currency": "USD"},
                         EventContext(session, SimpleNamespace()))
    payment = (await session.execute(select(Payment))).scalar_one()
    assert payment.amount == 100 and payment.currency == "BYN"


async def test_cross_module_api(api, session):
    await seed(session)
    result = await api.post("/system/fx/convert", json={"amount": "100", "currency": "USD", "on": str(DAY)})
    assert result.status_code == 200, result.text
    assert result.json()["amount_byn"] == "312.34"


async def test_bank_preserves_original_and_allocates_byn(session):
    from modules.finance.bank_ingest import sync_incoming
    from modules.finance.models import BankTransaction, PaymentAllocation

    await seed(session)
    session.add(Payment(ref="INV-77", amount=Decimal("312.34"), status="pending", kind="receivable"))
    await session.commit()

    class Bank:
        async def fetch_incoming(self, since):
            return [{"ext_id": "fx-77", "amount": "100", "currency": "USD",
                     "date": str(DAY), "purpose": "INV-77"}]

    result = await sync_incoming(session, Bank(), OutboxEventBus())
    await session.commit()
    assert result["matched"] == 1
    assert (await session.execute(select(PaymentAllocation))).scalar_one().amount == Decimal("312.34")
    tx = (await session.execute(select(BankTransaction))).scalar_one()
    assert tx.amount == 100 and tx.currency == "USD"
    assert (await sync_incoming(session, Bank(), OutboxEventBus()))["new"] == 0


async def test_sync_is_idempotent_and_keeps_history(session):
    from core.domain.reference import CurrencyRate
    from core.services.nbrb_sync import sync_currency

    await seed(session)
    session.add(CurrencyRate(currency_code="USD", rate=3, start_date=date(2026, 8, 1)))
    await session.commit()
    await sync_currency(session, "USD", DAY)
    await session.commit()
    await sync_currency(session, "USD", DAY)
    await session.commit()
    rows = (await session.execute(select(CurrencyRate).order_by(CurrencyRate.start_date))).scalars().all()
    assert len(rows) == 2 and rows[0].end_date == DAY and rows[1].end_date is None
    events = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "reference.ref_currency_rate.changed"
    ))).scalars().all()
    assert len(events) == 1


async def test_sync_refuses_conflicting_manual_rate(session):
    from core.domain.reference import CurrencyRate
    from core.services.nbrb_sync import sync_currency

    await seed(session)
    session.add(CurrencyRate(currency_code="USD", rate=9, start_date=DAY))
    await session.flush()
    with pytest.raises(nbrb.RateUnavailable):
        await sync_currency(session, "USD", DAY)


async def test_guest_cannot_trigger_fetch(api):
    result = await api.get(f"/system/fx/USD?on={DAY}", headers={"X-User-Roles": "guest"})
    assert result.status_code == 403


async def test_valid_employee_can_read_shared_quote(api, session):
    await seed(session)
    result = await api.get(f"/system/fx/USD?on={DAY}", headers={"X-User-Roles": "sales_manager"})
    assert result.status_code == 200, result.text


async def test_manual_foreign_allocation(api, session):
    await seed(session)
    created = await api.post("/finance/payments", json={"ref": "allocation", "amount": "312.34"})
    pid = created.json()["id"]
    result = await api.post(f"/finance/payments/{pid}/allocations", json={
        "amount": "100", "currency": "USD", "operation_date": str(DAY)
    })
    assert result.status_code == 201, result.text
    assert result.json()["amount"] == "312.34"


async def test_foreign_opening_balance_is_byn_in_cashflow(session):
    from modules.finance.cashflow import _opening_balance
    from modules.finance.models import BankAccount

    await seed(session)
    account = BankAccount(code="FX", title="FX", currency="USD", opening_balance=100, opening_at=DAY)
    session.add(account)
    await session.flush()
    assert await _opening_balance(session, account.id) == Decimal("312.34")


async def test_refresh_continues_after_one_currency_failure(session, monkeypatch):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.domain.reference import CurrencyRate
    from core.services import nbrb_sync

    async def fake_quote(s, code, on):
        if code == "EUR":
            raise nbrb.RateUnavailable("offline")
        return {"currency": code, "date": str(on), "rate": "1"}

    async def stop(delay):
        assert delay == 3600
        raise asyncio.CancelledError

    monkeypatch.setattr(nbrb, "quote", fake_quote)
    monkeypatch.setattr(nbrb_sync.asyncio, "sleep", stop)
    services = SimpleNamespace(db=SimpleNamespace(session_factory=async_sessionmaker(session.bind)))
    with pytest.raises(asyncio.CancelledError):
        await nbrb_sync.run(services)
    codes = set((await session.execute(select(CurrencyRate.currency_code))).scalars())
    assert codes == {"BYN", "USD", "RUB", "CNY", "PLN"}


async def test_real_client_path_without_network(api, monkeypatch):
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response("USD", "3.30", 1)))
    monkeypatch.setattr(nbrb.httpx, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs))
    result = await api.get(f"/system/fx/USD?on={DAY}")
    assert result.status_code == 200 and result.json()["rate"] == "3.30"


async def test_api_rejects_missing_quote_and_invalid_dates(api):
    result = await api.get("/system/fx/USD?on=2010-01-01")
    assert result.status_code == 503
    result = await api.post("/system/fx/convert", json={"amount": "10", "currency": "USD", "on": "2099-01-01"})
    assert result.status_code == 503


async def test_nonfinite_amount_is_rejected(session):
    with pytest.raises(nbrb.RateUnavailable):
        await nbrb.convert(session, "NaN", "BYN", DAY)


async def test_empty_api_response_is_not_a_zero_rate(session):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))) as client:
        with pytest.raises(nbrb.RateUnavailable):
            await nbrb.quote(session, "USD", DAY, client=client)
