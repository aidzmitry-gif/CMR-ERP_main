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

from core.domain.models import Sku
from core.domain.reference import NomenclatureCategory, TnvedCode, VatRate
from core.services import scd2

#: предел подъёма по дереву групп при резолве унаследованного ТН ВЭД (защита от цикла parent_id).
_MAX_DEPTH = 32


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


def _none_result() -> dict:
    return {"value": None, "source": None, "group_code": None, "group_name": None}


async def _walk_up_groups(session: AsyncSession, category_id: int, extract) -> dict:
    """Подъём по дереву групп от ``category_id`` вверх, отдаёт первое непустое ``extract(cat)``.

    ``extract`` — функция ``(NomenclatureCategory) -> value | None`` (колонка/JSONB-ключ).
    Архивная группа (``is_active=False``) не «дарит» значение вниз, но подъём продолжается.
    Возврат: ``{value, source: "group"|None, group_code, group_name}``. Ограничен ``_MAX_DEPTH``
    (защита от цикла ``parent_id``).
    """
    cat_id: int | None = category_id
    for _ in range(_MAX_DEPTH):
        cat = await session.get(NomenclatureCategory, cat_id)
        if cat is None:
            break
        val = extract(cat)
        if val and cat.is_active:
            return {"value": val, "source": "group", "group_code": cat.code, "group_name": cat.name}
        if cat.parent_id is None:
            break
        cat_id = cat.parent_id
    return _none_result()


async def effective_group_field(session: AsyncSession, sku: Sku, field: str) -> dict:
    """Эффективное значение «общего поля группы» для товара: своё, иначе унаследованное.

    ``field`` — имя поля и на ``Sku``, и на ``NomenclatureCategory`` (``tnved_code``, ``unit``;
    для ``vat_code``/``country`` своего поля у Sku нет — берётся только от группы). Возврат:
    ``{value, source, group_code, group_name}``. ``source``: ``"own"`` (задано на товаре),
    ``"group"`` (взято с группы — ``group_code``/``group_name`` указывают, с какой), ``None``
    (нигде не задано). Подъём по дереву групп вверх по ``parent_id``, ограничен ``_MAX_DEPTH``
    (защита от цикла). Архивная группа не «дарит» значение вниз, но подъём продолжается.
    """
    own = getattr(sku, field, None)
    if own:
        return {"value": own, "source": "own", "group_code": None, "group_name": None}
    if sku.category_id is None:
        return _none_result()
    return await _walk_up_groups(session, sku.category_id, lambda cat: getattr(cat, field, None))


async def effective_group_attr(session: AsyncSession, sku: Sku, key: str) -> dict:
    """Эффективное значение свободного атрибута товара: свой ключ в ``Sku.attributes``, иначе группы.

    ``key`` — ключ в JSONB-словаре ``attributes`` и товара, и группы (``"Производитель"``,
    ``"Кол-во в коробке"``, …). Собственное непустое значение товара побеждает; иначе подъём по
    дереву групп ищет ключ в ``NomenclatureCategory.attributes``. Возврат — как у
    ``effective_group_field``: ``{value, source: own|group|None, group_code, group_name}``.
    Значения нормализуются в строку для отдачи в JSON (атрибуты свободные, тип не гарантирован).
    """
    own = (sku.attributes or {}).get(key)
    if own not in (None, ""):
        return {"value": str(own), "source": "own", "group_code": None, "group_name": None}
    if sku.category_id is None:
        return _none_result()

    def _from_group(cat: NomenclatureCategory):
        v = (cat.attributes or {}).get(key)
        return str(v) if v not in (None, "") else None

    return await _walk_up_groups(session, sku.category_id, _from_group)


async def effective_code_for_sku(session: AsyncSession, sku: Sku) -> dict:
    """Эффективный код ТН ВЭД товара (обёртка над ``effective_group_field`` для совместимости).

    Возврат: ``{code, source, group_code, group_name}`` — ``code`` вместо ``value`` (контракт
    карточки SKU и тестов не меняется).
    """
    eff = await effective_group_field(session, sku, "tnved_code")
    return {
        "code": eff["value"], "source": eff["source"],
        "group_code": eff["group_code"], "group_name": eff["group_name"],
    }
