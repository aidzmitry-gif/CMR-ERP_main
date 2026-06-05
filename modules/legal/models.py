"""ORM-модели модуля Legal (схема ``legal.*``)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class LegalCase(Base):
    """Юр-дело в воронке: документ/договор/претензия/суд → завершение.

    Стадия (`stage`) ведёт дело по этапам контроля документов и взыскания
    (см. ``stages.py``). ``urgency`` — срочность (Срочно/Контроль/Обычный).
    """

    __tablename__ = "legal_case"
    __table_args__ = {"schema": "legal"}

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(64), default="", server_default="")
    company: Mapped[str] = mapped_column(String(255), default="", server_default="")
    title: Mapped[str] = mapped_column(String(255), default="", server_default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    urgency: Mapped[str] = mapped_column(String(32), default="Обычный", server_default="Обычный")
    owner: Mapped[str] = mapped_column(String(128), default="", server_default="")
    stage: Mapped[str] = mapped_column(String(32), default="inbox", server_default="inbox")
    next_step: Mapped[str] = mapped_column(String(255), default="", server_default="")
    due_date: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
