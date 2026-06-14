"""Shared-kernel reference data — системные справочники-стандарты (схема ``public``).

Мелкие, общие для всех модулей справочники, которыми владеет ядро: единицы, валюты
(+ историчный курс), страны, банки, ставки НДС (+ история). Данные физически лежат
здесь; вкладка «Справочники» лишь регистрирует их как реестр-витрину (см.
``core.runtime.reference_registry``).

Историчность (курс валюты, ставка НДС) — ручной **SCD Type 2**: датированные версии
с полуоткрытым интервалом ``[start_date, end_date)``; текущая версия — ``end_date IS NULL``.
Нативные temporal-таблицы Postgres — это PG18/19, стек на PG16 → ведём вручную.

Типы намеренно generic (``JSON``/``Numeric``/``Date``) — чтобы dev на SQLite поднимался
через ``create_all``; JSONB/GIN включаются только в Postgres-миграции (источник истины схемы).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class Unit(Base):
    """Единица измерения (шт, кг, м)."""

    __tablename__ = "ref_unit"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    title: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class Country(Base):
    """Страна (ISO-код)."""

    __tablename__ = "ref_country"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)  # ISO "BY", "RU"
    title: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class Bank(Base):
    """Банк (БИК/SWIFT)."""

    __tablename__ = "ref_bank"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # БИК
    title: Mapped[str] = mapped_column(String(255))
    swift: Mapped[str | None] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class Currency(Base):
    """Валюта (ISO-код)."""

    __tablename__ = "ref_currency"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)  # ISO "BYN", "USD"
    title: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class CurrencyRate(Base):
    """Курс валюты к BYN — историчный (SCD Type 2)."""

    __tablename__ = "ref_currency_rate"

    id: Mapped[int] = mapped_column(primary_key=True)  # surrogate key
    currency_code: Mapped[str] = mapped_column(String(8))  # natural key
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    start_date: Mapped[date] = mapped_column(Date)  # действует с (вкл.)
    end_date: Mapped[date | None] = mapped_column(Date)  # по (искл.); NULL = текущая

    __table_args__ = (
        Index("ix_ref_currency_rate_lookup", "currency_code", "start_date"),
    )


class VatRate(Base):
    """Ставка НДС — историчная (SCD Type 2)."""

    __tablename__ = "ref_vat_rate"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16))  # natural key: "НДС20"
    title: Mapped[str] = mapped_column(String(64))
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # 20.00
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)  # NULL = текущая

    __table_args__ = (
        Index("ix_ref_vat_rate_lookup", "code", "start_date"),
    )
