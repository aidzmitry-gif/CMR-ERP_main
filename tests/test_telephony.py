"""Телефония (SALES-50 + коннектор zruchna): парсер событий, нормализация номера,
резолв продавца, идемпотентность журнала, webhook и эндпоинты действий."""
from types import SimpleNamespace

import pytest

from modules.integrations.telephony import (
    normalize_e164,
    originate_params,
    parse_event,
)


# --- Нормализация номера в E.164 (РБ по умолчанию) --------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("375291234567", "+375291234567"),
        ("+375291234567", "+375291234567"),
        ("80291234567", "+375291234567"),  # домашний набор 8 0XX …
        ("8 (029) 123-45-67", "+375291234567"),
        ("00375291234567", "+375291234567"),  # международный префикс 00 → +
        ("291234567", "+375291234567"),  # 9 цифр без кода страны
        ("", None),
        (None, None),
    ],
)
def test_normalize_e164(raw, expected):
    assert normalize_e164(raw) == expected


# --- Маппинг событий zruchna ------------------------------------------------------
def test_parse_incoming():
    out = parse_event({"type": "in", "direct": "in", "uniqueid": "U1", "phone": "375291234567", "did": "375171234567"})
    assert out["event_type"] == "telephony.call.incoming"
    p = out["payload"]
    assert p["call_id"] == "U1"
    assert p["direction"] == "in"
    assert p["phone_e164"] == "+375291234567"
    assert p["did"] == "375171234567"
    assert p["entity_ref"] == "call:U1"


def test_parse_hangup_answered():
    out = parse_event({
        "type": "hangup", "direct": "in", "uniqueid": "U1", "status": "ANSWERED",
        "hold": "120", "duration": "95", "path": "/rec/u1.wav", "phone": "375291234567", "code": "101",
    })
    assert out["event_type"] == "telephony.call.ended"
    p = out["payload"]
    assert p["status"] == "answered"
    assert p["hold_sec"] == 120
    assert p["duration_sec"] == 95
    assert p["recording_url"] == "/rec/u1.wav"
    assert p["agent_ext"] == "101"


def test_parse_misscall():
    out = parse_event({"type": "misscall", "direct": "in", "uniqueid": "U2", "status": "NO ANSWERED", "phone": "375291234567"})
    assert out["event_type"] == "telephony.call.ended"
    assert out["payload"]["event"] == "misscall"
    assert out["payload"]["status"] == "no_answer"


def test_parse_transfer_and_outbound():
    tr = parse_event({"type": "transfer", "direct": "in", "uniqueid": "U3", "code": "101", "totransfer": "102", "phone": "375291234567"})
    assert tr["event_type"] == "telephony.call.transfer"
    assert tr["payload"]["to_ext"] == "102"

    out = parse_event({"type": "dial", "direct": "out", "uniqueid": "U4", "phone": "375291234567", "code": "101"})
    assert out["event_type"] == "telephony.call.incoming"
    assert out["payload"]["direction"] == "out"


def test_parse_ignored():
    assert parse_event({"type": "weird", "uniqueid": "U5"}) is None  # неизвестный тип
    assert parse_event({"type": "in", "uniqueid": ""}) is None  # без uniqueid не склеить


def test_parse_duration_garbage_no_crash():
    # мусор в длительности не должен уронить вебхук: inf → OverflowError, "-5" → отрицательное
    out = parse_event({"type": "hangup", "direct": "in", "uniqueid": "U6", "duration": "inf", "hold": "-5"})
    assert out["payload"]["duration_sec"] is None
    assert out["payload"]["hold_sec"] is None


def test_originate_params():
    assert originate_params("101", "375291234567") == {"vnut": "101", "number": "+375291234567"}
    assert originate_params("1234", "291234567")["vnut"] == "123"  # внутренний — не больше 3 цифр


# --- Резолв продавца по номеру (A.2) ----------------------------------------------
async def test_resolve_owner_by_active_deal(session):
    from modules.sales.calls import resolve_owner
    from modules.sales.models import Deal

    from core.domain.models import Contact, Counterparty

    cp = Counterparty(name="ООО Резолв", unp="190000777")
    session.add(cp)
    await session.flush()
    session.add(Contact(counterparty_id=cp.id, full_name="Клиент", phone="+375291112233", is_primary=True))
    session.add(Deal(number="RSLV-1", title="t", counterparty="ООО Резолв", owner="Иванов И.И.", stage="new"))
    await session.commit()

    res = await resolve_owner(session, "+375291112233")
    assert res["owner"] == "Иванов И.И."
    assert res["counterparty_id"] == cp.id
    assert res["contact_id"] is not None


async def test_resolve_owner_lead_fallback(session):
    from modules.sales.calls import resolve_owner
    from modules.sales.models import Lead

    session.add(Lead(source="phone", phone="+375299998877", assigned_to="Петров П.П.", status="routed"))
    await session.commit()

    res = await resolve_owner(session, "375299998877")  # незнакомый контакт → лид
    assert res["owner"] == "Петров П.П."
    assert res["counterparty_id"] is None


async def test_resolve_owner_unknown_number(session):
    from modules.sales.calls import resolve_owner

    res = await resolve_owner(session, "+375290000000")
    assert res == {"owner": "", "owner_id": None, "counterparty_id": None, "contact_id": None}


# --- Обработчик: журнал + идемпотентность + push карточки -------------------------
def _ctx(session):
    from core.services.eventbus import EventContext, OutboxEventBus

    bus = OutboxEventBus()
    return EventContext(session=session, services=SimpleNamespace(event_bus=bus)), bus


async def test_incoming_logs_resolves_and_pushes(session):
    from modules.sales.models import CallLog, Deal
    from sqlalchemy import select

    from core.domain.models import Contact, Counterparty, OutboxEvent
    from modules.sales import calls as calls_mod

    cp = Counterparty(name="ООО Пуш", unp="190000888")
    session.add(cp)
    await session.flush()
    session.add(Contact(counterparty_id=cp.id, full_name="К", phone="+375291110000", is_primary=True))
    session.add(Deal(number="PUSH-1", title="t", counterparty="ООО Пуш", owner="Сидоров С.С.", stage="prop"))
    await session.commit()

    # продавец подписан на поток своих звонков
    queue = calls_mod.subscribe("Сидоров С.С.")
    ctx, _ = _ctx(session)
    payload = {"call_id": "CALL-1", "direction": "in", "phone_e164": "+375291110000", "did": "375171234567"}
    await calls_mod.on_incoming_call(payload, ctx)
    await session.commit()

    rows = (await session.execute(select(CallLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].owner == "Сидоров С.С."
    assert rows[0].status == "ringing"

    # карточка доставлена в очередь подписки продавца
    card = queue.get_nowait()
    assert card["call_id"] == "CALL-1"
    assert card["owner"] == "Сидоров С.С."
    calls_mod.unsubscribe("Сидоров С.С.", queue)

    # событие sales.call.logged ушло в шину
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "sales.call.logged" in types

    # идемпотентность: повторный incoming с тем же call_id не создаёт дубль
    await calls_mod.on_incoming_call(payload, ctx)
    await session.commit()
    assert len((await session.execute(select(CallLog))).scalars().all()) == 1


async def test_ended_updates_call(session):
    from modules.sales.models import CallLog
    from sqlalchemy import select

    from core.domain.models import OutboxEvent
    from modules.sales import calls as calls_mod

    ctx, _ = _ctx(session)
    await calls_mod.on_incoming_call({"call_id": "C-END", "direction": "in", "phone_e164": "+375291110001"}, ctx)
    await calls_mod.on_call_ended(
        {"call_id": "C-END", "event": "hangup", "status": "answered", "duration_sec": 42, "recording_url": "/r/c.wav"},
        ctx,
    )
    await session.commit()

    call = (await session.execute(select(CallLog).where(CallLog.call_id == "C-END"))).scalars().first()
    assert call.status == "ended"
    assert call.duration_sec == 42
    assert call.recording_url == "/r/c.wav"
    assert call.ended_at is not None

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "sales.call.ended" in types


async def test_missed_call_status(session):
    from modules.sales.models import CallLog
    from sqlalchemy import select

    from core.domain.models import OutboxEvent
    from modules.sales import calls as calls_mod

    ctx, _ = _ctx(session)
    await calls_mod.on_call_ended(
        {"call_id": "C-MISS", "direction": "in", "phone_e164": "+375291110002", "event": "misscall", "status": "no_answer"},
        ctx,
    )
    await session.commit()
    call = (await session.execute(select(CallLog).where(CallLog.call_id == "C-MISS"))).scalars().first()
    assert call.status == "missed"

    # пропущенный без предшествующего incoming должен всё равно залогироваться (audit/KPI)
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "sales.call.logged" in types


async def test_late_answer_keeps_terminal_status(session):
    """Внепорядковый answer после hangup не понижает терминальный статус обратно."""
    from modules.sales.models import CallLog
    from sqlalchemy import select

    from modules.sales import calls as calls_mod

    ctx, _ = _ctx(session)
    await calls_mod.on_call_ended(
        {"call_id": "C-OOO", "direction": "in", "phone_e164": "+375291110003", "event": "hangup", "status": "answered"},
        ctx,
    )
    await calls_mod.on_call_answered({"call_id": "C-OOO", "direction": "in"}, ctx)
    await session.commit()
    call = (await session.execute(select(CallLog).where(CallLog.call_id == "C-OOO"))).scalars().first()
    assert call.status == "ended"  # остался терминальным, не вернулся в "answered"
    assert call.answered_at is not None


# --- HTTP: webhook коннектора + токен ----------------------------------------------
async def test_webhook_emits_event(session, api):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent

    r = await api.get(
        "/integrations/telephony/zruchna",
        params={"type": "in", "direct": "in", "uniqueid": "WH-1", "phone": "375291234567", "did": "375171234567"},
    )
    assert r.status_code == 200
    assert r.json()["event"] == "telephony.call.incoming"

    rows = (await session.execute(select(OutboxEvent).where(OutboxEvent.event_type == "telephony.call.incoming"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].payload["call_id"] == "WH-1"
    assert rows[0].payload["phone_e164"] == "+375291234567"


async def test_webhook_ignores_unknown_type(session, api):
    r = await api.post("/integrations/telephony/zruchna", json={"type": "noise", "uniqueid": "X"})
    assert r.status_code == 200
    assert r.json()["ignored"] is True


async def test_webhook_token_enforced(session):
    from httpx import ASGITransport, AsyncClient

    from core.runtime.app import create_app
    from core.runtime.deps import get_session

    app = create_app()
    app.state.core.config.telephony_webhook_token = "s3cret"

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            bad = await client.get("/integrations/telephony/zruchna", params={"type": "in", "uniqueid": "T1", "phone": "375291234567"})
            assert bad.status_code == 403
            # non-ASCII токен не должен ронять вебхук в 500 (compare_digest на байтах)
            nonascii = await client.get(
                "/integrations/telephony/zruchna",
                params={"token": "Ключ", "type": "in", "uniqueid": "T1", "phone": "375291234567"},
            )
            assert nonascii.status_code == 403
            ok = await client.get(
                "/integrations/telephony/zruchna",
                params={"token": "s3cret", "type": "in", "uniqueid": "T1", "phone": "375291234567"},
            )
            assert ok.status_code == 200
    finally:
        app.state.core.config.telephony_webhook_token = ""  # не протекать в другие тесты


# --- HTTP: журнал и действия (через синхронный fallback /sales/telephony/incoming) -
async def test_calls_journal_and_actions(session, api):
    # синхронный приём (минуя relay): создаёт запись + резолв owner
    r = await api.post(
        "/sales/telephony/incoming",
        json={"event_type": "telephony.call.incoming", "call_id": "JR-1", "direction": "in", "phone_e164": "+375291230000"},
    )
    assert r.status_code == 200

    listing = (await api.get("/sales/calls")).json()
    assert any(c["call_id"] == "JR-1" for c in listing)
    cid = next(c["id"] for c in listing if c["call_id"] == "JR-1")

    # комментарий и итог
    assert (await api.post(f"/sales/calls/{cid}/comment", json={"comment": "Перезвонить в 15:00"})).json()["comment"] == "Перезвонить в 15:00"
    assert (await api.post(f"/sales/calls/{cid}/result", json={"result": "Договорились о счёте"})).json()["result"] == "Договорились о счёте"

    # создать сделку из звонка
    linked = await api.post(f"/sales/calls/{cid}/link-deal", json={"create": True})
    assert linked.status_code == 200
    assert linked.json()["deal_id"] is not None

    assert (await api.get("/sales/calls/999999")).status_code == 404


async def test_originate_not_configured(api):
    # originate_url пуст по умолчанию → телефония к исходящему не подключена
    r = await api.post("/integrations/telephony/originate", json={"vnut": "101", "number": "375291234567"})
    assert r.status_code == 503
