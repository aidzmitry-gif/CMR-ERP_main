"""Контракт шлюза истории касаний — фасад ядра к 360°-досье контрагента (M5).

Звонки, письма, сделки живут в модуле ``sales`` (своя схема). Карточка контрагента в ядре
не лезет в схему модуля (изоляция §2.4) — она читает историю общения через
``core.services.touch_history``, а реализацию регистрирует ``sales``:
``core.services.touch_history = SalesTouchHistory()``. Пока модуль не реализовал — поле
``None``, карточка показывает реквизиты без истории (graceful).

Кросс-модульное чтение — через фасад/read-model, не ad-hoc join из ядра в схему модуля
(концепция §2). ``touches`` возвращает плоский журнал событий по контрагенту:
``[{kind, ts, channel, direction, title, ref}]`` (kind: call|message|deal), свежие сверху.
"""
from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class TouchHistoryGateway(Protocol):
    """Чтение истории касаний (звонки/письма/сделки) контрагента по его id."""

    async def touches(
        self, session: AsyncSession, counterparty_id: int, *, limit: int = 50
    ) -> list[dict]: ...

    async def summary(self, session: AsyncSession, counterparty_id: int) -> dict:
        """Сводка касаний: счётчики по типам/каналам, дата последнего контакта."""
        ...
