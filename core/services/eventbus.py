"""Событийная шина — паттерн transactional outbox.

Доменные события пишутся в таблицу ``outbox_event`` в той же транзакции, что и
изменение состояния (гарантия at-least-once). Доставку подписчикам выполняет
relay: сейчас — поллинг БД, целевой вариант — консьюмер Redis Streams (§ часть 3).
"""
from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import AuditLog, OutboxEvent

logger = logging.getLogger("aios.eventbus")


@dataclass
class EventContext:
    """Контекст доставки события обработчику: relay-сессия + фасад сервисов ядра.

    Передаётся обработчикам, объявившим второй параметр (напр. AI-агенты, которым
    нужен доступ к шлюзу LLM и шине). Обработчики с одним параметром (только
    ``payload``) продолжают работать без изменений (§2.5 — AI как обработчик событий).
    """

    session: AsyncSession
    services: object


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

    async def relay_once(self, session: AsyncSession, ctx: "EventContext | None" = None) -> int:
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
        if session.get_bind().dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        rows = (await session.execute(stmt)).scalars().all()
        for event in rows:
            logger.info("relay %s#%d -> %d", event.event_type, event.id, len(self._handlers.get(event.event_type, [])))
            await self.dispatch(event.event_type, event.payload, ctx)
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
