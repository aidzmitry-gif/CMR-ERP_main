"""Общие сервисы ядра и их сборка.

На этапе каркаса большинство сервисов — лёгкие заглушки с устойчивым контрактом:
их реализация наполняется в соответствующих частях дорожной карты (БД — часть 2,
шина — часть 3, Temporal — часть 4, auth — часть 5), а вызывающий код не меняется.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.services.approvals import ApprovalService
from core.services.auth import AuthService
from core.services.config import Settings, get_settings
from core.services.db import Database
from core.services.eventbus import OutboxEventBus
from core.services.litellm import LLMGateway
from core.services.onec import OneCGateway
from core.services.temporal import TemporalService

__all__ = ["Services", "build_services"]


@dataclass
class Services:
    """Контейнер общих сервисов, доступных модулям через ядро."""

    config: Settings
    event_bus: OutboxEventBus
    approvals: ApprovalService
    temporal: TemporalService
    db: Database
    auth: AuthService
    llm: LLMGateway
    # шлюз 1С наполняет модуль integrations при register (часть 6/9); None — модуль не подключён
    onec: OneCGateway | None = None


def build_services() -> Services:
    """Собрать сервисы для текущего окружения."""
    settings = get_settings()
    event_bus = OutboxEventBus()
    return Services(
        config=settings,
        event_bus=event_bus,
        approvals=ApprovalService(event_bus),
        temporal=TemporalService(),
        db=Database(settings),
        auth=AuthService(),
        llm=LLMGateway(),
    )
