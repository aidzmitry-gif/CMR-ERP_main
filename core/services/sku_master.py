"""Read-фасад мастер-входов landed cost по SKU — единый источник для закупок и маржи (REF3-1).

Сводит уже построенную логику ядра (``tnved.effective_code_for_sku`` + ``tnved.resolve`` +
``tnved.effective_group_field``) и «горячие» поля ``Sku`` (вес/объём/НДС) в ОДИН ответ, по
которому считается себестоимость и маржа: эффективная пошлина ТН ВЭД на дату, ставка НДС,
вес/объём для разнесения фрахта, страна происхождения — с провенансом по каждому полю
(own ∨ group ∨ tnved ∨ none). До этого фасада ``tnved.resolve``/``effective_code_for_sku``
не имели потребителей в ``modules/`` — закупки брали пошлину/вес «на вход или дефолт».

Это **апстрим**: его читают procurement (cost_estimate) и sales (маржа) через
``core.services.sku_master`` — имена полей зафиксированы в ТЗ REF3-1, их полосы подключаются
в свой срок. Чистый async read-сервис ядра: только чтение версий (``scd2``/``tnved``), без
записи и коммита. ``None`` (неизвестный SKU) ≠ нули — отсутствие не маскируем (скрыло бы дыру
в марже).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Sku
from core.domain.reference import VatRate
from core.services import scd2, tnved


async def _resolve_vat_rate(session: AsyncSession, vat_code: str | None, on: date) -> float | None:
    """Ставка НДС % по коду на дату (SCD2) или ``None`` — для своего/группового ``vat_code``."""
    if not vat_code:
        return None
    ver = await scd2.version_as_of(session, VatRate, "code", vat_code, on)
    return float(ver.rate) if ver is not None else None


async def _inputs_for(session: AsyncSession, sku: Sku, on: date) -> dict:
    """Мастер-входы landed cost для уже загруженного ``Sku`` на дату ``on`` (см. ``landed_inputs``)."""
    eff_tnved = await tnved.effective_code_for_sku(session, sku)
    rates = await tnved.resolve(session, eff_tnved["code"], on) if eff_tnved.get("code") else None

    eff_unit = await tnved.effective_group_field(session, sku, "unit")
    eff_country = await tnved.effective_group_field(session, sku, "country")

    # НДС: свой код товара → код группы → код от ТН ВЭД (для own/group резолвим ставку сами,
    # для tnved она уже посчитана в rates на ту же дату). Источник пишем в provenance.vat.
    if sku.vat_code:
        vat_code, vat_source = sku.vat_code, "own"
    else:
        grp_vat = await tnved.effective_group_field(session, sku, "vat_code")
        if grp_vat["value"]:
            vat_code, vat_source = grp_vat["value"], "group"
        elif rates and rates.get("vat_code"):
            vat_code, vat_source = rates["vat_code"], "tnved"
        else:
            vat_code, vat_source = None, "none"
    vat_rate = (
        (rates.get("vat_rate") if rates else None)
        if vat_source == "tnved"
        else await _resolve_vat_rate(session, vat_code, on)
    )

    return {
        "sku_code": sku.code,
        "weight_kg": sku.weight_kg,
        "volume_m3": sku.volume_m3,
        "unit": eff_unit["value"],
        "country": eff_country["value"],
        # эффективный ТН ВЭД (свой ∨ от группы) + откуда взят — вход пошлины
        "effective_tnved": {
            "code": eff_tnved["code"],
            "source": eff_tnved["source"],
            "group_code": eff_tnved["group_code"],
        },
        "duty_pct": rates["duty_rate"] if rates else None,  # пошлина % на дату или None
        "vat_code": vat_code,
        "vat_rate": vat_rate,  # ставка НДС % на дату или None
        # провенанс по полю: own (на товаре) | group (от группы) | tnved (от кода ТН ВЭД) | none
        "provenance": {
            "weight": "own" if sku.weight_kg is not None else "none",
            "volume": "own" if sku.volume_m3 is not None else "none",
            "unit": eff_unit["source"] or "none",
            "country": eff_country["source"] or "none",
            "tnved": eff_tnved["source"] or "none",
            "vat": vat_source,
        },
    }


async def landed_inputs(
    session: AsyncSession, sku_code: str, on_date: date | None = None
) -> dict | None:
    """Мастер-входы landed cost по коду SKU на дату; ``None`` — товара нет (НЕ нули).

    Один ответ для закупок/маржи: пошлина по эффективному ТН ВЭД (свой ∨ от группы) и ставка
    НДС, действовавшие на ``on_date`` (дефолт — сегодня); вес/объём/страна/ед. + провенанс по
    каждому полю. ``duty_pct``/``vat_rate`` = ``None``, если кода нет или нет версии на дату
    (отсутствие не маскируем нулём). Только чтение, без коммита.
    """
    on = on_date or date.today()
    sku = (await session.execute(select(Sku).where(Sku.code == sku_code))).scalars().first()
    if sku is None:
        return None
    return await _inputs_for(session, sku, on)


async def landed_inputs_batch(
    session: AsyncSession, sku_codes: list[str], on_date: date | None = None
) -> dict[str, dict | None]:
    """Мастер-входы для набора кодов одним проходом (выборка SKU — один запрос, не N+1).

    Возврат: ``{sku_code: inputs | None}`` (``None`` для неизвестного кода). Порядок ключей
    повторяет вход (дедуп сохраняет первое вхождение).
    """
    on = on_date or date.today()
    codes = list(dict.fromkeys(sku_codes))  # дедуп, сохраняя порядок
    by_code = {
        s.code: s
        for s in (await session.execute(select(Sku).where(Sku.code.in_(codes)))).scalars().all()
    }
    return {
        code: (await _inputs_for(session, by_code[code], on) if code in by_code else None)
        for code in codes
    }
