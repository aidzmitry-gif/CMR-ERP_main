"""Сервис процессов (Temporal). На старте — заглушка-реестр без воркера.

Реальный Temporal поднимается в части 4 (durable workflow + матрица согласований,
human-in-the-loop). Здесь — только базовый класс `Workflow`, чтобы модули могли
объявлять процессы уже сейчас, а ядро — их регистрировать.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("aios.temporal")


class Workflow:
    """Базовый маркер бизнес-процесса. В части 4 станет Temporal workflow."""

    name: str = "workflow"

    async def run(self, *args, **kwargs):
        raise NotImplementedError("Тело workflow появится на этапе реализации модуля")


class TemporalService:
    """Заглушка клиента Temporal — пока только сообщает о себе."""

    def __init__(self) -> None:
        self.connected = False

    async def start(self) -> None:
        logger.info("Temporal: заглушка (реальный клиент — часть 4)")
