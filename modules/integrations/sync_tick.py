"""Фоновый шаг исходящей выгрузки ERP → 1С (M3).

Один проход по очереди ``sync_link`` (state=pending, direction=out): выгрузка через
``services.onec.post_document``. Регистрируется ``core.on_tick`` и вызывается фоновым
циклом ядра; в тестах — напрямую. Транзакцией владеет вызывающий (цикл коммитит сам).
Идемпотентно: уже synced-линки не подбираются, ошибки остаются в state=error до повтора.
"""
from __future__ import annotations

from core.services import sync_outbound


async def tick_sync_out(session, services) -> None:
    """Выгрузить очередь pending → 1С. Без gateway (1С выключена) — тихий no-op."""
    gateway = getattr(services, "onec", None)
    if gateway is None:
        return
    await sync_outbound.flush_pending(session, gateway)
