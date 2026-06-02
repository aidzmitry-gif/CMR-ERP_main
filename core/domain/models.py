"""Общее ядро (shared kernel) — ORM-модели сущностей, нужных всем модулям.

Контрагент, контакт, SKU/номенклатура и пользователь живут здесь, и все модули
читают их через ядро, а не дублируют у себя (§2.4). Таблицы — в схеме по умолчанию
(``public``); таблицы модулей живут в собственных схемах.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String
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
