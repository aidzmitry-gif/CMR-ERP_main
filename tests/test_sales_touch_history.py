"""SalesTouchHistory (M5) — фасад истории касаний для 360°-карточки контрагента.

Проверяем: агрегацию звонков/сообщений/сделок в один журнал (свежие сверху),
изоляцию по контрагенту (чужие касания не протекают), graceful для неизвестного
контрагента, и связь звонка через сделку (когда у звонка нет counterparty_id).
"""
from datetime import datetime

import pytest

from core.domain.models import Counterparty
from modules.sales.models import CallLog, Deal, Message
from modules.sales.touch_history import SalesTouchHistory

T_DEAL = datetime(2026, 7, 16, 10, 0, 0)
T_CALL = datetime(2026, 7, 16, 11, 0, 0)
T_MSG = datetime(2026, 7, 16, 12, 0, 0)


async def _seed_counterparty(session, name: str) -> Counterparty:
    cp = Counterparty(name=name)
    session.add(cp)
    await session.flush()
    return cp


async def _seed_deal(session, number: str, counterparty: str, ts: datetime) -> Deal:
    deal = Deal(number=number, title="Сделка", counterparty=counterparty, created_at=ts)
    session.add(deal)
    await session.flush()
    return deal


@pytest.mark.asyncio
async def test_touches_aggregates_and_orders(session):
    cp = await _seed_counterparty(session, "ООО Ромашка")
    deal = await _seed_deal(session, "D-1", "ООО Ромашка", T_DEAL)
    session.add(CallLog(call_id="c1", counterparty_id=cp.id, direction="in",
                        status="ended", result="дозвонились", started_at=T_CALL))
    session.add(Message(deal_id=deal.id, channel="telegram", direction="in",
                        text="Здравствуйте, интересует АКБ", created_at=T_MSG))
    await session.flush()

    touches = await SalesTouchHistory().touches(session, cp.id)

    assert [t["kind"] for t in touches] == ["message", "call", "deal"]  # свежие сверху
    assert touches[0]["channel"] == "telegram" and touches[0]["direction"] == "in"
    assert touches[1]["channel"] == "phone" and touches[1]["ref"] == "c1"
    assert touches[2]["ref"] == "D-1" and "Сделка" in touches[2]["title"]

    summary = await SalesTouchHistory().summary(session, cp.id)
    assert summary == {
        "calls": 1, "messages": 1, "deals": 1, "total": 3,
        "last_contact_at": T_MSG.isoformat(),
    }


@pytest.mark.asyncio
async def test_isolation_other_counterparty(session):
    a = await _seed_counterparty(session, "Клиент А")
    await _seed_counterparty(session, "Клиент Б")
    await _seed_deal(session, "DA-1", "Клиент А", T_DEAL)
    b_deal = await _seed_deal(session, "DB-1", "Клиент Б", T_DEAL)
    session.add(CallLog(call_id="cb", deal_id=b_deal.id, direction="out",
                        status="ended", started_at=T_CALL))
    session.add(Message(deal_id=b_deal.id, channel="email", direction="out",
                        text="КП Б", created_at=T_MSG))
    await session.flush()

    touches = await SalesTouchHistory().touches(session, a.id)

    assert [t["ref"] for t in touches] == ["DA-1"]  # только своя сделка, чужого нет
    summary = await SalesTouchHistory().summary(session, a.id)
    assert summary["calls"] == 0 and summary["messages"] == 0 and summary["deals"] == 1


@pytest.mark.asyncio
async def test_unknown_counterparty_graceful(session):
    touches = await SalesTouchHistory().touches(session, 9999)
    assert touches == []
    summary = await SalesTouchHistory().summary(session, 9999)
    assert summary == {
        "calls": 0, "messages": 0, "deals": 0, "total": 0, "last_contact_at": None,
    }


@pytest.mark.asyncio
async def test_call_linked_via_deal_without_counterparty_id(session):
    cp = await _seed_counterparty(session, "ООО Вектор")
    deal = await _seed_deal(session, "D-9", "ООО Вектор", T_DEAL)
    # звонок телефонии без резолва контрагента, но привязан к сделке
    session.add(CallLog(call_id="c9", counterparty_id=None, deal_id=deal.id,
                        direction="in", status="ended", started_at=T_CALL))
    await session.flush()

    touches = await SalesTouchHistory().touches(session, cp.id)
    kinds = {t["kind"] for t in touches}
    assert kinds == {"deal", "call"}
    assert (await SalesTouchHistory().summary(session, cp.id))["calls"] == 1
