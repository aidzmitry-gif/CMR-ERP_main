"""ORM-модели модуля Production (схема ``production.*``)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class ProductionOrder(Base):
    """Производственный наряд в канбане цеха: изделие, кол-во, прогресс, этап.

    Этап (`stage`) ведёт наряд от очереди до готовности (см. ``stages.py``).
    Переход в «Готово → склад» (``done``) публикует ``production.completed`` → приход на склад.
    """

    __tablename__ = "production_order"
    __table_args__ = {"schema": "production"}

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(64), default="", server_default="")
    product: Mapped[str] = mapped_column(String(255))
    qty: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # % хода работ
    priority: Mapped[str] = mapped_column(String(32), default="Средний", server_default="Средний")
    owner: Mapped[str] = mapped_column(String(128), default="", server_default="")  # мастер
    stage: Mapped[str] = mapped_column(String(32), default="queue", server_default="queue")
    due_date: Mapped[str | None] = mapped_column(String(32))
    insight: Mapped[str] = mapped_column(String(400), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
