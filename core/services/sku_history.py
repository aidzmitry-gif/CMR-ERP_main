"""История мастер-характеристик SKU — запись датированных версий (SCD Type 2).

``Sku`` — единственная «текущая» золотая запись; здесь храним датированные СНИМКИ её
мастер-полей в ``ref_sku_version``, чтобы документ «на дату» видел характеристики,
действовавшие тогда (как курс валюты/НДС). Натуральный ключ — мягкий ``sku_code``.

``record_sku_version`` — единый путь записи истории: зовётся из точки правки SKU (так же,
как карточка сделки зовёт MDM-сервис для контрагента, а не пишет в shared-kernel напрямую).
Чтение версий — generic-роутером ``/system/refs/sku-history`` и ``reference_query`` (as-of).

Транзакцию коммитит вызывающий код (сервисы ядра не коммитят, §ядро).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Sku
from core.domain.reference import SkuVersion
from core.services import scd2

#: мастер-поля SKU, чей датированный снимок ведём. Операционные (цена/остаток/себес) — НЕ здесь:
#: другой владелец (1С/склад) и жизненный цикл (шов §1, mdm-data-class-seam.md).
SNAPSHOT_FIELDS = (
    "title", "unit", "category_id", "weight_kg", "tnved_code", "shelf_life_days", "attributes",
)


def _snapshot(obj: Sku | SkuVersion) -> dict:
    """Снимок мастер-полей (общие имена у ``Sku`` и ``SkuVersion``)."""
    return {f: getattr(obj, f) for f in SNAPSHOT_FIELDS}


async def record_sku_version(
    session: AsyncSession, sku: Sku, start: date
) -> SkuVersion | None:
    """Открыть версию истории SKU с даты ``start`` снимком текущих мастер-полей товара.

    Идемпотентно по содержимому: если текущая открытая версия идентична снимку — ничего не
    пишем (не плодим версии без изменений) и возвращаем ``None``. Иначе закрываем текущую
    (``end_date = start``) и открываем новую (``scd2.add_version``). Бросает ``ValueError``,
    если ``start`` не позже текущей открытой версии (контракт SCD2). Не коммитит.
    """
    current = await scd2.current_version(session, SkuVersion, "sku_code", sku.code)
    snapshot = _snapshot(sku)
    if current is not None and _snapshot(current) == snapshot:
        return None
    return await scd2.add_version(session, SkuVersion, "sku_code", sku.code, start, **snapshot)
