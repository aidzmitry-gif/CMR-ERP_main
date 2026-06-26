"""Резолв таможенных ставок по коду ТН ВЭД на дату — для расчёта landed cost.

Один lookup отдаёт всё, что нужно расчёту себестоимости: ставку ввозной пошлины (ЕТТ ЕАЭС)
и ставку НДС, действовавшие на дату оформления. НДС хранится не в ``ref_tnved``, а мягкой
ссылкой ``vat_code`` → ``ref_vat_rate`` (отдельный SCD2-справочник) — здесь резолвится обе
версии на одну дату, чтобы потребитель (модуль procurement) не делал два запроса и не знал
про связь справочников.

Чистый сервис ядра (без коммита): только чтение версий через ``scd2.version_as_of``.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.reference import TnvedCode, VatRate
from core.services import scd2


async def resolve(session: AsyncSession, code: str, on: date) -> dict | None:
    """Ставки по коду ТН ВЭД на дату ``on``. ``None`` — нет версии кода на эту дату.

    Возврат: ``{code, name, duty_rate, vat_code, vat_rate, excise, unit, as_of}``.
    ``duty_rate`` — пошлина % (ЕТТ); ``vat_rate`` — ставка НДС % на дату (или ``None``, если
    ``vat_code`` не задан/не найден на дату). Числа — ``float`` для JSON.
    """
    row = await scd2.version_as_of(session, TnvedCode, "code", code, on)
    if row is None:
        return None

    vat_rate = None
    if row.vat_code:
        vat = await scd2.version_as_of(session, VatRate, "code", row.vat_code, on)
        if vat is not None:
            vat_rate = float(vat.rate)

    return {
        "code": row.code,
        "name": row.name,
        "duty_rate": float(row.duty_rate),
        "vat_code": row.vat_code,
        "vat_rate": vat_rate,  # ставка НДС %, резолвленная на ту же дату; None — не задана
        "excise": row.excise,
        "unit": row.unit,
        "as_of": on.isoformat(),
    }
