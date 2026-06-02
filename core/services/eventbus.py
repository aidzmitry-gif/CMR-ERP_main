"""Событийная шина — паттерн transactional outbox.

Доменные события пишутся в таблицу ``outbox_event`` в той же транзакции, что и
изменение состояния (гарантия at-least-once). Доставку подписчикам выполняет
relay: сейчас — поллинг БД, целевой вариант — консьюмер Redis Streams (§ часть 3).
"""
from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import AuditLog, OutboxEvent

logger = logging.getLogger("aios.eventbus")


class OutboxEventBus:
    """Шина событий поверх outbox-таблицы."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    def emit(self, session: AsyncSession, event_type: str, payload: dict, version: int = 1) -> None:
        """Записать событие в outbox в текущей транзакции (без немедленной доставки)."""
        session.add(OutboxEvent(event_type=event_type, version=version, payload=payload))

    async def dispatch(self, event_type: str, payload: dict) -> None:
        """Вызвать подписчиков события (используется relay)."""
        for handler in self._handlers.get(event_type, []):
            result = handler(payload)
            if inspect.isawaitable(result):
                await result

    async def relay_once(self, session: AsyncSession) -> int:
        """Доставить необработанные события подписчикам и пометить processed_at."""
        rows = (
            await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.processed_at.is_(None))
                .order_by(OutboxEvent.id)
            )
        ).scalars().all()
        for event in rows:
            logger.info("relay %s#%d -> %d", event.event_type, event.id, len(self._handlers.get(event.event_type, [])))
            await self.dispatch(event.event_type, event.payload)
            event.processed_at = datetime.now(timezone.utc)
            # неизменяемый аудит: проекция каждого события
            session.add(
                AuditLog(
                    actor=str(event.payload.get("by") or event.payload.get("actor") or ""),
                    action=event.event_type,
                    entity_ref=str(event.payload.get("entity_ref") or ""),
                    detail=event.payload,
                )
            )
        if rows:
            await session.commit()
        return len(rows)
