"""M5: 360°-история касаний на карточке контрагента через фасад touch_history."""
from core.domain.models import Counterparty


class _TouchGateway:
    """Mock sales-фасада: плоский журнал касаний + сводка."""

    async def touches(self, session, counterparty_id, *, limit=50):
        return [
            {"kind": "call", "ts": "2026-06-24T10:00", "channel": "phone",
             "direction": "in", "title": "Входящий звонок", "ref": "call:5"},
            {"kind": "deal", "ts": "2026-06-20T09:00", "channel": None,
             "direction": None, "title": "Сделка CRM-12", "ref": "deal:12"},
        ]

    async def summary(self, session, counterparty_id):
        return {"calls": 1, "deals": 1, "messages": 0, "last_contact": "2026-06-24T10:00"}


async def test_card_requires_permission(api, session):
    """Карточка несёт PII/историю общения: роль без права sales.deal.read → 403."""
    cp = Counterparty(name="ООО Закрытый", unp="200000009")
    session.add(cp)
    await session.commit()
    r = await api.get(f"/system/mdm/counterparty/{cp.id}", headers={"X-User-Roles": "warehouse"})
    assert r.status_code == 403


async def test_card_without_gateway_has_empty_touches(api, session):
    """Модуль sales выключен → шлюз None: карточка без истории (graceful None-путь).

    (По умолчанию sales регистрирует SalesTouchHistory — этот путь проверяет деградацию,
    когда фасада нет; наполненный путь — в test_sales_touch_history.py.)
    """
    cp = Counterparty(name="ООО Без истории", unp="200000001")
    session.add(cp)
    await session.commit()
    core = api._transport.app.state.core
    previous = core.services.touch_history
    core.services.touch_history = None
    try:
        card = (await api.get(f"/system/mdm/counterparty/{cp.id}")).json()
        assert card["touches"] == []
        assert card["touch_summary"] is None
    finally:
        core.services.touch_history = previous


async def test_card_reads_touches_via_gateway(api, session):
    cp = Counterparty(name="ООО С историей", unp="200000002")
    session.add(cp)
    await session.commit()

    core = api._transport.app.state.core
    core.services.touch_history = _TouchGateway()
    try:
        card = (await api.get(f"/system/mdm/counterparty/{cp.id}")).json()
        kinds = [t["kind"] for t in card["touches"]]
        assert kinds == ["call", "deal"]  # свежие сверху
        assert card["touch_summary"]["calls"] == 1
        assert card["touch_summary"]["last_contact"] == "2026-06-24T10:00"
    finally:
        core.services.touch_history = None


async def test_card_graceful_when_gateway_raises(api, session):
    """Если sales-фасад бросает — карточка без истории, не 500."""
    class _BadGateway:
        async def touches(self, session, counterparty_id, *, limit=50):
            raise RuntimeError("sales недоступен")

        async def summary(self, session, counterparty_id):
            raise RuntimeError("sales недоступен")

    cp = Counterparty(name="ООО Сбой", unp="200000003")
    session.add(cp)
    await session.commit()

    core = api._transport.app.state.core
    core.services.touch_history = _BadGateway()
    try:
        r = await api.get(f"/system/mdm/counterparty/{cp.id}")
        assert r.status_code == 200
        assert r.json()["touches"] == []
    finally:
        core.services.touch_history = None
