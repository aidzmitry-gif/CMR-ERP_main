"""B1 — лок строк outbox против конкурентной двойной доставки (гонка релеев).

``relay_once`` без блокировки строк: синхронный relay в ``convert_lead`` и фоновый
``_background_loop`` (поллинг 2с) могли выбрать ОДНИ и те же строки → двойная
доставка события (двойная сделка/платёж — деньги собственника). Фикс:
``SELECT ... FOR UPDATE SKIP LOCKED``, dialect-aware (только PostgreSQL); на SQLite
(dev/тест — single-writer) деградируем до обычного SELECT.

Настоящую lock-семантику PG на SQLite in-memory не воспроизвести. Регресс-гард
ниже перехватывает РЕАЛЬНЫЙ statement самого ``relay_once`` под замоканным
PostgreSQL-диалектом и проверяет, что он компилируется с FOR UPDATE SKIP LOCKED —
падает без фикса (обычный SELECT), в отличие от простого at-most-once наблюдения.
"""
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from core.domain.models import OutboxEvent
from core.services.eventbus import EventContext, OutboxEventBus


class _PGDialect:
    name = "postgresql"


class _PGBind:
    dialect = _PGDialect()


async def test_relay_once_pg_statement_carries_row_lock(session):
    """Регресс-гард B1: под PostgreSQL relay_once строит SELECT ... FOR UPDATE SKIP LOCKED.

    Перехватываем фактический statement, переданный в ``session.execute`` самим
    ``relay_once`` (не ручной), с ``get_bind`` замоканным на postgresql. Без фикса
    (обычный SELECT без лока) assert падает — это и отличает регресс-гард от
    характеризационной проверки at-most-once ниже.
    """
    bus = OutboxEventBus()
    bus.subscribe("b1.money.moved", lambda payload: None)
    bus.emit(session, "b1.money.moved", {"amount": "100.00", "entity_ref": "deal:1"})
    await session.flush()

    real_execute = session.execute
    captured: dict = {}

    async def spy_execute(stmt, *a, **k):
        captured.setdefault("stmt", stmt)  # первый execute в relay_once — SELECT outbox
        return await real_execute(stmt, *a, **k)

    orig_get_bind = session.get_bind
    session.get_bind = lambda *a, **k: _PGBind  # type: ignore[method-assign]
    session.execute = spy_execute  # type: ignore[method-assign]
    try:
        n = await bus.relay_once(session, EventContext(session=session, services=object()))
    finally:
        session.get_bind = orig_get_bind  # type: ignore[method-assign]
        session.execute = real_execute  # type: ignore[method-assign]

    assert n == 1
    compiled = str(captured["stmt"].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in compiled, compiled


async def test_relay_once_no_double_delivery(session):
    """Характеризация: повторный relay_once не доставляет то же событие дважды."""
    calls: list[dict] = []
    bus = OutboxEventBus()
    bus.subscribe("b1.money.moved", lambda payload: calls.append(payload))
    bus.emit(session, "b1.money.moved", {"amount": "100.00", "entity_ref": "deal:1"})
    await session.flush()

    ctx = EventContext(session=session, services=object())
    assert await bus.relay_once(session, ctx) == 1
    assert await bus.relay_once(session, ctx) == 0  # второй релей — брать нечего
    assert len(calls) == 1, "событие не должно доставляться дважды"

    ev = (await session.execute(select(OutboxEvent))).scalars().first()
    assert ev is not None and ev.processed_at is not None
