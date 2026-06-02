"""Шина событий. На старте — внутрипроцессная заглушка.

В части 3 заменяется на паттерн Postgres outbox + консьюмер Redis Streams с
версионированием схем событий. Контракт ``subscribe`` / ``publish`` сохраняется,
поэтому модули переписывать не нужно (см. §4, часть 3 архитектуры).
"""
from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from typing import Callable, Protocol

logger = logging.getLogger("aios.eventbus")


class EventBus(Protocol):
    """Контракт шины событий."""

    def subscribe(self, event_type: str, handler: Callable) -> None: ...

    async def publish(self, event_type: str, payload: dict) -> None: ...


class InProcessEventBus:
    """Простейшая шина в пределах процесса: вызывает подписчиков синхронно."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event_type: str, payload: dict) -> None:
        handlers = self._handlers.get(event_type, [])
        logger.info("event %s -> подписчиков: %d", event_type, len(handlers))
        for handler in handlers:
            result = handler(payload)
            if inspect.isawaitable(result):
                await result
