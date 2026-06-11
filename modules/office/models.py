"""ORM-модели модуля Office (схема ``office.*``).

Документ ведёт сделку по постпродажному конвейеру: отгрузка → документы → оплата.
Поля ``*_ref`` — следы связей с другими отделами (Sales/Склад/Логистика/Финансы/Юрист),
наполняются обработчиками событий и роутами (см. ``events.py``, ``routes.py``).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class OfficeDoc(Base):
    """Документ по сделке в воронке офис-менеджера: отгрузка → документы → оплата."""

    __tablename__ = "office_doc"
    __table_args__ = {"schema": "office"}

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(64), default="", server_default="")
    company: Mapped[str] = mapped_column(String(255), default="", server_default="")
    title: Mapped[str] = mapped_column(String(255), default="", server_default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    delivery: Mapped[str] = mapped_column(String(64), default="", server_default="")   # способ доставки / перевозчик
    docs_status: Mapped[str] = mapped_column(String(64), default="", server_default="")  # статус документов
    priority: Mapped[str] = mapped_column(String(32), default="Средний", server_default="Средний")
    owner: Mapped[str] = mapped_column(String(128), default="", server_default="")
    stage: Mapped[str] = mapped_column(String(32), default="ready", server_default="ready")
    next_step: Mapped[str] = mapped_column(String(255), default="", server_default="")
    op_date: Mapped[str | None] = mapped_column(String(32))

    # --- доставка ---
    region: Mapped[str] = mapped_column(String(64), default="", server_default="")     # направление по РБ
    weight: Mapped[str] = mapped_column(String(32), default="", server_default="")      # вес/габарит груза
    address: Mapped[str] = mapped_column(String(255), default="", server_default="")    # адрес выдачи

    # --- следы связей с отделами (event-driven) ---
    sales_ref: Mapped[str] = mapped_column(String(64), default="", server_default="")       # ← CRM (sales.deal.won)
    wms_ref: Mapped[str] = mapped_column(String(64), default="", server_default="")          # ↔ Склад (приёмка/сборка/отгрузка)
    logistics_ref: Mapped[str] = mapped_column(String(64), default="", server_default="")    # → Логистика (заявка перевозчику)
    finance_ref: Mapped[str] = mapped_column(String(64), default="", server_default="")       # ↔ Финансы (счёт/оплата)
    legal_ref: Mapped[str] = mapped_column(String(64), default="", server_default="")          # → Юрист (претензия по просрочке)
    overdue_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")          # дни просрочки оплаты

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
