"""Событийная шина — паттерн transactional outbox.

Доменные события пишутся в таблицу ``outbox_event`` в той же транзакции, что и
изменение состояния (гарантия at-least-once). Доставку подписчикам выполняет
relay: сейчас — поллинг БД, целевой вариант — консьюмер Redis Streams (§ часть 3).
"""
from __future__ import annotations

import inspect
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import AuditLog, OutboxEvent

logger = logging.getLogger("aios.eventbus")

# Only these handlers are independent call projections. Finance and unknown event
# types retain fail-stop delivery; a broad telephony.* prefix is not sufficient.
_ISOLATED_CALL_EVENTS = (
    "telephony.call.incoming",
    "telephony.call.answered",
    "telephony.call.ended",
    "telephony.call.transfer",
)


def _call_id(value: object) -> str | None:
    # Match sales.record_event's identity, including Python's whitespace rules.
    return (value.strip() or None) if isinstance(value, str) else None


@dataclass
class EventContext:
    """Контекст доставки события обработчику: relay-сессия + фасад сервисов ядра.

    Передаётся обработчикам, объявившим второй параметр (напр. AI-агенты, которым
    нужен доступ к шлюзу LLM и шине). Обработчики с одним параметром (только
    ``payload``) продолжают работать без изменений (§2.5 — AI как обработчик событий).
    """

    session: AsyncSession
    services: object
    _after_commit: list[Callable[[], object]] | None = field(default=None, repr=False)
    occurred_at: datetime | None = None

    def after_commit(self, callback: Callable[[], object]) -> object | None:
        """Defer a relay notification; direct callers retain immediate delivery."""
        if self._after_commit is None:
            return callback()
        self._after_commit.append(callback)
        return None


def _wants_ctx(handler: Callable) -> bool:
    """Принимает ли обработчик контекст (второй параметр)?"""
    try:
        return len(inspect.signature(handler).parameters) >= 2
    except (ValueError, TypeError):
        return False


class OutboxEventBus:
    """Шина событий поверх outbox-таблицы."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    def emit(self, session: AsyncSession, event_type: str, payload: dict, version: int = 1) -> None:
        """Записать событие в outbox в текущей транзакции (без немедленной доставки)."""
        session.add(OutboxEvent(event_type=event_type, version=version, payload=payload))

    async def dispatch(self, event_type: str, payload: dict, ctx: "EventContext | None" = None) -> None:
        """Вызвать подписчиков события (используется relay).

        Обработчик с двумя параметрами получает ``ctx`` (сессия + сервисы), с
        одним — только ``payload`` (обратная совместимость).
        """
        for handler in self._handlers.get(event_type, []):
            result = handler(payload, ctx) if _wants_ctx(handler) else handler(payload)
            if inspect.isawaitable(result):
                await result

    async def _deliver(self, session: AsyncSession, event: OutboxEvent, ctx: EventContext | None) -> None:
        dated_ctx = replace(ctx, occurred_at=event.created_at) if ctx is not None else None
        await self.dispatch(event.event_type, event.payload, dated_ctx)
        event.processed_at = datetime.now(timezone.utc)
        # Successful delivery and its immutable audit share the same transaction.
        session.add(
            AuditLog(
                actor=str(event.payload.get("by") or event.payload.get("actor") or ""),
                action=event.event_type,
                entity_ref=str(event.payload.get("entity_ref") or ""),
                detail=event.payload,
            )
        )

    async def relay_once(
        self,
        session: AsyncSession,
        ctx: "EventContext | None" = None,
        *,
        event_types=None,
    ) -> int:
        """Доставить необработанные события подписчикам и пометить processed_at.

        Лок строк outbox (B1): без блокировки синхронный ``relay_once`` в
        ``convert_lead`` и фоновый ``_background_loop`` (поллинг 2с) выбрали бы ОДНИ
        и те же строки → двойная доставка события (двойная сделка/платёж — деньги
        собственника). Каноничный outbox-лок — ``SELECT ... FOR UPDATE SKIP LOCKED``:
        конкурентные релеи берут ДИЗЪЮНКТНЫЕ наборы, лок держится до ``commit`` ниже.
        SKIP LOCKED — только PostgreSQL; на SQLite (dev/тест — single-writer, гонки
        нет) деградируем до обычного SELECT.
        """
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.processed_at.is_(None))
            .order_by(OutboxEvent.id)
        )
        if event_types is not None:
            stmt = stmt.where(OutboxEvent.event_type.in_(event_types))
        if session.get_bind().dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        rows = (await session.execute(stmt)).scalars().all()
        pending_calls: dict[str, deque[int]] = defaultdict(deque)
        phone_ids = [event.id for event in rows if event.event_type in _ISOLATED_CALL_EVENTS]
        if phone_ids:
            if session.get_bind().dialect.name == "sqlite":
                # sqlite3/aiosqlite legacy mode does not BEGIN for a SELECT.
                # Without a real outer transaction, RELEASE of our first
                # SAVEPOINT commits its writes, defeating a later outer rollback.
                # Inspect the driver, not SQLAlchemy's logical transaction flag;
                # leave an existing caller/modern-driver transaction intact.
                connection = await session.connection()
                raw = await connection.get_raw_connection()
                if not raw.driver_connection.in_transaction:
                    await connection.exec_driver_sql("BEGIN")
            # Ordinary MVCC read deliberately includes predecessors locked by a
            # different relay, even when event_types excludes them. Only fetch
            # identity fields, preserving JSON types and Python .strip() semantics.
            # A concurrently completed predecessor conservatively delays one tick.
            # Uncommitted producer inserts are outside this visible-pending contract.
            predecessors = await session.execute(
                select(OutboxEvent.id, OutboxEvent.payload["call_id"])
                .where(
                    OutboxEvent.processed_at.is_(None),
                    OutboxEvent.event_type.in_(_ISOLATED_CALL_EVENTS),
                    OutboxEvent.id <= max(phone_ids),
                )
                .order_by(OutboxEvent.id)
            )
            for event_id, value in predecessors:
                if key := _call_id(value):
                    pending_calls[key].append(event_id)

        delivered = 0
        notifications: list[Callable[[], object]] = []
        for event in rows:
            # A failed flush expires the ORM event on savepoint rollback. Keep
            # diagnostic and ordering values outside that expired instance.
            event_type, event_id = event.event_type, event.id
            logger.info("relay %s#%d -> %d", event_type, event_id, len(self._handlers.get(event_type, [])))
            if event_type not in _ISOLATED_CALL_EVENTS:
                await self._deliver(session, event, ctx)
                delivered += 1
                continue

            key = _call_id(event.payload.get("call_id")) if isinstance(event.payload, dict) else None
            predecessors = pending_calls.get(key) if key else None
            if predecessors and predecessors[0] < event_id:
                continue
            if ctx is None and any(_wants_ctx(handler) for handler in self._handlers.get(event_type, ())):
                # Missing caller context is a configuration error, not malformed
                # payload. Official call handlers otherwise return without writes.
                raise ValueError(f"EventContext is required for {event_type} delivery")

            # begin_nested unconditionally flushes earlier caller/batch writes.
            # Neither that flush nor physical SAVEPOINT creation may be swallowed
            # as a malformed telephone event.
            savepoint = await session.begin_nested()
            await session.connection()
            event_notifications: list[Callable[[], object]] = []
            event_ctx = replace(ctx, _after_commit=event_notifications) if ctx is not None else None
            try:
                await self._deliver(session, event, event_ctx)
                await session.flush()
            except Exception as exc:
                await savepoint.rollback()
                # Do not log provider payloads or SQL parameter values.
                logger.error("isolated telephony relay error: %s#%d (%s)", event_type, event_id, type(exc).__name__)
                continue
            # Releasing a savepoint and the outer commit are infrastructure errors,
            # not recoverable payload failures. Cancellation also propagates.
            await savepoint.commit()
            notifications.extend(event_notifications)
            delivered += 1
            if predecessors and predecessors[0] == event_id:
                predecessors.popleft()
        if rows:
            await session.commit()
            for notify in notifications:
                try:
                    notify()
                except Exception as exc:
                    # Delivery has committed. One best-effort SSE failure must
                    # neither report a database failure nor discard other cards.
                    logger.error("post-commit relay notification error (%s)", type(exc).__name__)
        return delivered
