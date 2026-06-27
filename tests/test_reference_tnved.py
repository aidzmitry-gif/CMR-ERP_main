"""Справочник ТН ВЭД ЕАЭС (SCD2) + lookup ставок на дату — вход расчёта landed cost.

Версионный справочник как курсы/НДС: версии по датам; lookup резолвит пошлину + ставку НДС
(из ref_vat_rate по мягкой ссылке vat_code) на дату оформления.
"""
from datetime import date

from core.domain.models import Sku
from core.domain.reference import NomenclatureCategory, TnvedCode, VatRate
from core.services import tnved


async def test_tnved_in_catalog(api):
    departments = (await api.get("/system/references")).json()["departments"]
    by_key = {ref["key"]: ref for refs in departments.values() for ref in refs}
    assert "core.tnved" in by_key
    assert by_key["core.tnved"]["versioned"] is True
    assert by_key["core.tnved"]["endpoint"] == "/system/refs/tnved"


async def test_tnved_versioning_via_router(api):
    base = "/system/refs/tnved"
    # первая версия (открытая)
    r = await api.post(
        f"{base}/versions",
        json={"code": "8507100000", "start_date": "2024-01-01", "name": "Аккумуляторы",
              "duty_rate": "5.0", "vat_code": "НДС20", "unit": "шт"},
    )
    assert r.status_code == 200
    # ставка снижена с 2026 — новая версия закрывает первую
    r = await api.post(
        f"{base}/versions",
        json={"code": "8507100000", "start_date": "2026-01-01", "name": "Аккумуляторы",
              "duty_rate": "0.0", "vat_code": "НДС20", "unit": "шт"},
    )
    assert r.status_code == 200

    # текущая версия — ставка 0
    cur = (await api.get(f"{base}/current", params={"key": "8507100000"})).json()
    assert float(cur["duty_rate"]) == 0.0
    assert cur["end_date"] is None

    # на дату внутри первого периода → старая ставка 5%
    old = (await api.get(f"{base}/as-of", params={"key": "8507100000", "on": "2025-06-01"})).json()
    assert float(old["duty_rate"]) == 5.0


async def test_tnved_lookup_resolves_duty_and_vat(api, session):
    """lookup отдаёт пошлину + ставку НДС, резолвленную из ref_vat_rate на ту же дату."""
    session.add(VatRate(code="НДС20", title="НДС 20%", rate=20,
                        start_date=date(2024, 1, 1), end_date=None))
    session.add(TnvedCode(code="8504401900", name="Зарядные устройства", duty_rate=5,
                          vat_code="НДС20", excise=None, unit="шт",
                          start_date=date(2024, 1, 1), end_date=None))
    await session.commit()

    r = await api.get("/system/tnved/lookup", params={"code": "8504401900", "on": "2026-06-26"})
    assert r.status_code == 200
    body = r.json()
    assert body["duty_rate"] == 5.0
    assert body["vat_rate"] == 20.0  # резолвлено из ref_vat_rate
    assert body["vat_code"] == "НДС20"
    assert body["as_of"] == "2026-06-26"


async def test_tnved_lookup_404_before_start(api, session):
    session.add(TnvedCode(code="8544429009", name="Провода", duty_rate=0,
                          vat_code="НДС20", excise=None, unit="кг",
                          start_date=date(2024, 1, 1), end_date=None))
    await session.commit()
    # дата до начала действия версии → нет ставки на эту дату
    r = await api.get("/system/tnved/lookup", params={"code": "8544429009", "on": "2020-01-01"})
    assert r.status_code == 404


async def test_tnved_via_reference_query(api, session):
    """AI-путь reference.query (ai_exposed) должен резолвить версию на дату, не 422."""
    session.add(TnvedCode(code="8507600000", name="Литий-ионные", duty_rate=0,
                          vat_code="НДС20", excise=None, unit="шт",
                          start_date=date(2024, 1, 1), end_date=None))
    await session.commit()
    r = await api.post(
        "/system/references/query",
        json={"ref": "core.tnved", "key": "8507600000", "as_of": "2026-06-26"},
    )
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["code"] == "8507600000"
    assert float(res["duty_rate"]) == 0.0


async def test_tnved_lookup_vat_null_when_no_vat_code(api, session):
    """Если vat_code не задан/нет версии НДС на дату — vat_rate=None (не падаем)."""
    session.add(TnvedCode(code="9030339000", name="Тестеры", duty_rate=0,
                          vat_code=None, excise=None, unit="шт",
                          start_date=date(2024, 1, 1), end_date=None))
    await session.commit()
    body = (await api.get(
        "/system/tnved/lookup", params={"code": "9030339000", "on": "2026-06-26"}
    )).json()
    assert body["duty_rate"] == 0.0
    assert body["vat_rate"] is None


async def test_effective_tnved_own_wins(session):
    """Свой код товара — источник own, группу не смотрим."""
    grp = NomenclatureCategory(code="G1", name="Аккумуляторы", tnved_code="8507100000")
    session.add(grp)
    await session.flush()
    sku = Sku(code="AKB-1", title="АКБ", category_id=grp.id, tnved_code="8507600000")
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_code_for_sku(session, sku)
    assert eff == {"code": "8507600000", "source": "own", "group_code": None, "group_name": None}


async def test_effective_tnved_inherited_from_group(session):
    """Нет своего → наследуем от группы (вверх по parent_id), с указанием группы."""
    root = NomenclatureCategory(code="G10", name="Аккумуляторы", tnved_code="8507100000")
    session.add(root)
    await session.flush()
    child = NomenclatureCategory(code="G11", name="Грузовые", parent_id=root.id)  # без своего ТН ВЭД
    session.add(child)
    await session.flush()
    sku = Sku(code="AKB-2", title="АКБ", category_id=child.id, tnved_code=None)
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_code_for_sku(session, sku)
    assert eff["code"] == "8507100000"
    assert eff["source"] == "group"
    assert eff["group_code"] == "G10"  # унаследовано от КОРНЯ, не от пустого child


async def test_effective_tnved_skips_archived_group(session):
    """Архивная группа не дарит код вниз; подъём продолжается к активному предку."""
    root = NomenclatureCategory(code="G30", name="Аккумуляторы", tnved_code="8507100000")
    session.add(root)
    await session.flush()
    # промежуточная группа архивна и имеет свой код — НЕ должен примениться
    mid = NomenclatureCategory(code="G31", name="Старое", parent_id=root.id,
                               tnved_code="9999999999", is_active=False)
    session.add(mid)
    await session.flush()
    sku = Sku(code="AKB-3", title="АКБ", category_id=mid.id, tnved_code=None)
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_code_for_sku(session, sku)
    assert eff["code"] == "8507100000"  # взят от активного корня, архивный mid пропущен
    assert eff["group_code"] == "G30"


async def test_effective_tnved_none_when_nowhere(session):
    """Нет ни своего, ни в группах вверх → None (не падаем, не выдумываем)."""
    grp = NomenclatureCategory(code="G20", name="Прочее")  # без ТН ВЭД
    session.add(grp)
    await session.flush()
    sku = Sku(code="X-1", title="X", category_id=grp.id, tnved_code=None)
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_code_for_sku(session, sku)
    assert eff == {"code": None, "source": None, "group_code": None, "group_name": None}


# ── Общие данные группы (наследуемые поля unit/country/vat_code, M4) ──────────


async def test_effective_group_unit_own_wins(session):
    """Своя ед.изм товара — источник own, группу не смотрим."""
    grp = NomenclatureCategory(code="GU1", name="Батарейки", unit="упак")
    session.add(grp)
    await session.flush()
    sku = Sku(code="U-1", title="Батарейка", category_id=grp.id, unit="шт")
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_group_field(session, sku, "unit")
    assert eff["value"] == "шт"
    assert eff["source"] == "own"


async def test_effective_group_country_inherited(session):
    """Страна (своего поля у Sku нет) наследуется от группы вверх по дереву."""
    root = NomenclatureCategory(code="GC10", name="Импорт", country="CN")
    session.add(root)
    await session.flush()
    child = NomenclatureCategory(code="GC11", name="Китай-АКБ", parent_id=root.id)
    session.add(child)
    await session.flush()
    sku = Sku(code="C-1", title="АКБ", category_id=child.id)
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_group_field(session, sku, "country")
    assert eff["value"] == "CN"
    assert eff["source"] == "group"
    assert eff["group_code"] == "GC10"  # унаследовано от корня, не от пустого child


async def test_effective_group_vat_inherited(session):
    """Ставка НДС по умолчанию группы наследуется товаром (своего поля у Sku нет)."""
    grp = NomenclatureCategory(code="GV1", name="Услуги", vat_code="НДС20")
    session.add(grp)
    await session.flush()
    sku = Sku(code="V-1", title="Услуга", category_id=grp.id)
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_group_field(session, sku, "vat_code")
    assert eff["value"] == "НДС20"
    assert eff["source"] == "group"


async def test_effective_group_field_skips_archived(session):
    """Архивная группа не дарит значение вниз; подъём идёт к активному предку."""
    root = NomenclatureCategory(code="GA10", name="Импорт", country="CN")
    session.add(root)
    await session.flush()
    mid = NomenclatureCategory(code="GA11", name="Старое", parent_id=root.id,
                               country="RU", is_active=False)
    session.add(mid)
    await session.flush()
    sku = Sku(code="A-1", title="Товар", category_id=mid.id)
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_group_field(session, sku, "country")
    assert eff["value"] == "CN"  # архивный mid (RU) пропущен, взят активный корень
    assert eff["group_code"] == "GA10"


async def test_effective_group_field_none_when_nowhere(session):
    """Нигде не задано → value None (не выдумываем)."""
    grp = NomenclatureCategory(code="GN1", name="Прочее")
    session.add(grp)
    await session.flush()
    sku = Sku(code="N-1", title="X", category_id=grp.id)
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_group_field(session, sku, "country")
    assert eff == {"value": None, "source": None, "group_code": None, "group_name": None}


async def test_sku_card_exposes_group_defaults(api, session):
    """Карточка SKU отдаёт effective_unit/country/group_vat от группы."""
    session.add(VatRate(code="НДС20", title="НДС 20%", rate=20,
                        start_date=date(2024, 1, 1), end_date=None))
    grp = NomenclatureCategory(code="GD1", name="Группа", unit="упак",
                               country="CN", vat_code="НДС20")
    session.add(grp)
    await session.flush()
    session.add(Sku(code="GD-SKU", title="Товар", category_id=grp.id))
    await session.commit()

    card = (await api.get("/system/sku/GD-SKU")).json()
    # unit у Sku всегда задан (default «шт») → источник own, группа не перебивает
    assert card["effective_unit"]["value"] == "шт"
    assert card["effective_unit"]["source"] == "own"
    # страна/НДС своего поля у Sku не имеют → наследуются от группы
    assert card["effective_country"]["value"] == "CN"
    assert card["effective_country"]["source"] == "group"
    assert card["group_vat"]["value"] == "НДС20"
    assert card["group_vat"]["rate"] == 20.0  # резолвлено из ref_vat_rate на сегодня


# ── Свободные атрибуты группы (Производитель/коробка/габариты) — JSONB-наследование ──


async def test_effective_group_attr_own_wins(session):
    """Свой ключ в Sku.attributes побеждает значение группы."""
    grp = NomenclatureCategory(code="GAT1", name="Батарейки",
                               attributes={"Производитель": "GP Batteries"})
    session.add(grp)
    await session.flush()
    sku = Sku(code="ATT-1", title="АКБ", category_id=grp.id,
              attributes={"Производитель": "Panasonic"})
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_group_attr(session, sku, "Производитель")
    assert eff["value"] == "Panasonic"
    assert eff["source"] == "own"


async def test_effective_group_attr_inherited(session):
    """Нет своего ключа → наследуем от группы вверх по дереву (число → строка)."""
    root = NomenclatureCategory(code="GAT10", name="Импорт",
                                attributes={"Производитель": "Космос", "Кол-во в коробке": 10})
    session.add(root)
    await session.flush()
    child = NomenclatureCategory(code="GAT11", name="Подгруппа", parent_id=root.id)  # пусто
    session.add(child)
    await session.flush()
    sku = Sku(code="ATT-2", title="Товар", category_id=child.id, attributes={})
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_group_attr(session, sku, "Производитель")
    assert eff["value"] == "Космос"
    assert eff["source"] == "group"
    assert eff["group_code"] == "GAT10"  # от корня, не от пустого child
    # значение нормализуется в строку (атрибуты свободного типа)
    box = await tnved.effective_group_attr(session, sku, "Кол-во в коробке")
    assert box["value"] == "10"


async def test_effective_group_attr_skips_archived(session):
    """Архивная группа не дарит атрибут вниз; подъём идёт к активному предку."""
    root = NomenclatureCategory(code="GAT20", name="Импорт",
                                attributes={"Производитель": "Космос"})
    session.add(root)
    await session.flush()
    mid = NomenclatureCategory(code="GAT21", name="Старое", parent_id=root.id,
                               attributes={"Производитель": "Устаревший"}, is_active=False)
    session.add(mid)
    await session.flush()
    sku = Sku(code="ATT-3", title="Товар", category_id=mid.id, attributes={})
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_group_attr(session, sku, "Производитель")
    assert eff["value"] == "Космос"  # архивный mid пропущен
    assert eff["group_code"] == "GAT20"


async def test_effective_group_attr_none_when_nowhere(session):
    """Ключа нет ни у товара, ни в группах → value None (не выдумываем)."""
    grp = NomenclatureCategory(code="GAT30", name="Прочее", attributes={})
    session.add(grp)
    await session.flush()
    sku = Sku(code="ATT-4", title="X", category_id=grp.id, attributes={})
    session.add(sku)
    await session.flush()
    eff = await tnved.effective_group_attr(session, sku, "Производитель")
    assert eff == {"value": None, "source": None, "group_code": None, "group_name": None}


async def test_sku_card_exposes_effective_attrs(api, session):
    """Карточка SKU отдаёт effective_attrs: своё (own) + унаследованное от группы (group)."""
    grp = NomenclatureCategory(code="GE1", name="Группа",
                               attributes={"Производитель": "GP Batteries", "Кол-во в коробке": "10 шт"})
    session.add(grp)
    await session.flush()
    session.add(Sku(code="GE-SKU", title="Товар", category_id=grp.id,
                    attributes={"Марка": "GP Ultra"}))  # своя марка, производитель — от группы
    await session.commit()

    attrs = (await api.get("/system/sku/GE-SKU")).json()["effective_attrs"]
    assert attrs["Производитель"] == {
        "value": "GP Batteries", "source": "group", "group_code": "GE1", "group_name": "Группа",
    }
    assert attrs["Кол-во в коробке"]["value"] == "10 шт"
    assert attrs["Кол-во в коробке"]["source"] == "group"
    assert attrs["Марка"]["value"] == "GP Ultra"
    assert attrs["Марка"]["source"] == "own"


async def test_sku_card_country_falls_back_to_legacy_jsonb(api, session):
    """Страна из легаси JSONB-ключа «Страна происхождения» не пропадает с карточки.

    Типизированной колонки country нет (ни у товара, ни у группы) → effective_country
    должно подхватить значение из Sku.attributes (как пишет синк 1С), а не отдать None.
    """
    grp = NomenclatureCategory(code="GCL1", name="Группа")  # без типизированной country
    session.add(grp)
    await session.flush()
    session.add(Sku(code="CL-SKU", title="АКБ", category_id=grp.id,
                    attributes={"Страна происхождения": "Китай"}))
    await session.commit()

    card = (await api.get("/system/sku/CL-SKU")).json()
    assert card["effective_country"]["value"] == "Китай"
    assert card["effective_country"]["source"] == "own"
