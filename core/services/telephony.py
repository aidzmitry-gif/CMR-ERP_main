"""Контракт телефонного шлюза — инициация исходящего звонка (click-to-call).

Симметрично ``onec`` / ``stock`` / ``registry``: реализация живёт в модуле
``integrations`` (облачная АТС zruchna) и регистрируется в фасаде при загрузке —
``core.services.telephony = ZruchnaClient(...)``. Модули инициируют звонок через
``core.services.telephony``, не зная про конкретного провайдера (§2.4).

Входящие события звонка идут НЕ через этот шлюз, а через шину: коннектор
принимает webhook провайдера и эмитит ``telephony.call.incoming/answered/ended/
transfer`` в outbox; подписчик (sales) ведёт журнал и поднимает карточку.
"""
from __future__ import annotations

from typing import Protocol


class TelephonyGateway(Protocol):
    """Исходящий звонок: поднять трубку у сотрудника ``vnut`` и набрать ``number``.

    Возвращает ответ провайдера (``{ok, ...}``). Реализация выполняет HTTP-запрос
    к АТС (zruchna ``client_call_gen.php``).
    """

    async def originate(self, vnut: str, number: str) -> dict: ...
