"""Общее ядро (shared kernel) — ORM-модели сущностей, нужных всем модулям.

Контрагент, контакт, SKU/номенклатура и пользователь живут здесь, и все модули
читают их через ядро, а не дублируют у себя (§2.4). Таблицы — в схеме по умолчанию
(``public``); таблицы модулей живут в собственных схемах.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class Counterparty(Base):
    """Контрагент (клиент или поставщик)."""

    __tablename__ = "counterparty"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    unp: Mapped[str | None] = mapped_column(String(32))  # УНП (РБ)


class Contact(Base):
    """Контактное лицо контрагента."""

    __tablename__ = "contact"

    id: Mapped[int] = mapped_column(primary_key=True)
    counterparty_id: Mapped[int | None] = mapped_column(ForeignKey("counterparty.id"))
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))


class Sku(Base):
    """Единица номенклатуры (товарная позиция)."""

    __tablename__ = "sku"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(16), default="шт", server_default="шт")


class User(Base):
    """Пользователь системы (сотрудник). Роли/права — в части 5 (RBAC)."""

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True)
    full_name: Mapped[str] = mapped_column(String(255))


class OutboxEvent(Base):
    """Журнал доменных событий (transactional outbox).

    Пишется в одной транзакции с изменением состояния (гарантия at-least-once);
    relay доставляет подписчикам и проставляет ``processed_at`` (часть 3).
    Это инфраструктурная таблица ядра.
    """

    __tablename__ = "outbox_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Approval(Base):
    """Запрос на согласование (human-in-the-loop).

    Долгоживущий: висит в БД в ожидании решения человека, переживает рестарт.
    Маршрутизируется по роли (`route`), эскалируется по таймеру (`due_at`).
    Это инфраструктурная таблица ядра (часть 4).
    """

    __tablename__ = "approval"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    entity_ref: Mapped[str] = mapped_column(String(64))  # например "deal:7"
    subject: Mapped[str] = mapped_column(String(255))
    route: Mapped[str] = mapped_column(String(64))  # роль-согласующий
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    requested_by: Mapped[str] = mapped_column(String(128), default="", server_default="")
    decided_by: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(String(255))
    escalation_level: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuditLog(Base):
    """Неизменяемый журнал аудита — проекция доменных событий (append-only, часть 5)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    actor: Mapped[str] = mapped_column(String(128), default="", server_default="")
    action: Mapped[str] = mapped_column(String(128))
    entity_ref: Mapped[str] = mapped_column(String(64), default="", server_default="")
    detail: Mapped[dict] = mapped_column(JSON)
