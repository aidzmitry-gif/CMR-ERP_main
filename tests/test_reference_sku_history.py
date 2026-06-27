"""История мастер-характеристик SKU (SCD2): запись версий + витрина/AI/карточка.

Натуральный ключ истории — мягкий ``sku_code`` (без FK к ``sku.id``); запись версий —
``core.services.sku_history.record_sku_version`` (единый путь из точки правки SKU).
"""
from datetime import date

from core.domain.models import Sku
from core.domain.reference import SkuVersion
from core.services import scd2
from core.services.sku_history import record_sku_version


async def test_record_version_and_idempotency(session):
    """record_sku_version открывает версию; без изменений полей — не плодит (None)."""
    sku = Sku(code="REL-12", title="Реле 12В", unit="шт", weight_kg=0.2)
    session.add(sku)
    await session.flush()

    v1 = await record_sku_version(session, sku, date(2026, 1, 1))
    assert v1 is not None
    assert v1.end_date is None  # текущая (открытая)
    assert v1.title == "Реле 12В"

    # повтор без изменений → None (история не растёт на пустом месте)
    assert await record_sku_version(session, sku, date(2026, 2, 1)) is None

    # изменили мастер-поля → новая версия закрывает прежнюю датой начала
    sku.title = "Реле 12В (комплект 2 шт)"
    sku.weight_kg = 0.25
    v2 = await record_sku_version(session, sku, date(2026, 3, 1))
    assert v2 is not None and v2.end_date is None

    cur = await scd2.current_version(session, SkuVersion, "sku_code", "REL-12")
    assert cur.id == v2.id
    # документ «на 15.01» видит характеристики, действовавшие тогда
    old = await scd2.version_as_of(session, SkuVersion, "sku_code", "REL-12", date(2026, 1, 15))
    assert old.title == "Реле 12В"


async def test_history_router_and_card(api, session):
    """Роутер /system/refs/sku-history (список/as-of) + history в карточке /system/sku."""
    sku = Sku(code="CASE-A", title="Корпус A", unit="шт")
    session.add(sku)
    await session.flush()
    await record_sku_version(session, sku, date(2026, 1, 1))
    sku.title = "Корпус A2"
    await record_sku_version(session, sku, date(2026, 6, 1))
    await session.commit()

    rows = (await api.get("/system/refs/sku-history?key=CASE-A")).json()
    assert [r["title"] for r in rows] == ["Корпус A2", "Корпус A"]  # новые сверху (start_date desc)

    asof = (await api.get("/system/refs/sku-history/as-of?key=CASE-A&on=2026-03-01")).json()
    assert asof["title"] == "Корпус A"

    card = (await api.get("/system/sku/CASE-A")).json()
    assert [h["title"] for h in card["history"]] == ["Корпус A2", "Корпус A"]


async def test_history_manual_add_version(api):
    """Ручное добавление версии через generic-роутер (мягкий ключ — без Sku-записи)."""
    r1 = await api.post(
        "/system/refs/sku-history/versions",
        json={"sku_code": "MAN-1", "start_date": "2026-01-01", "title": "V1", "unit": "шт"},
    )
    assert r1.status_code == 200
    r2 = await api.post(
        "/system/refs/sku-history/versions",
        json={"sku_code": "MAN-1", "start_date": "2026-02-01", "title": "V2", "unit": "шт"},
    )
    assert r2.json()["title"] == "V2" and r2.json()["end_date"] is None

    rows = (await api.get("/system/refs/sku-history?key=MAN-1")).json()
    closed = next(x for x in rows if x["title"] == "V1")
    assert closed["end_date"] == "2026-02-01"  # прежняя закрыта датой новой


async def test_query_sku_history_as_of(api, session):
    """AI-доступ: reference.query core.sku_history с as_of → версия на дату."""
    sku = Sku(code="Q-1", title="Q v1", unit="шт")
    session.add(sku)
    await session.flush()
    await record_sku_version(session, sku, date(2026, 1, 1))
    sku.title = "Q v2"
    await record_sku_version(session, sku, date(2026, 6, 1))
    await session.commit()

    r = await api.post(
        "/system/references/query",
        json={"ref": "core.sku_history", "key": "Q-1", "as_of": "2026-03-01"},
    )
    assert r.json()["result"]["title"] == "Q v1"
    r = await api.post("/system/references/query", json={"ref": "core.sku_history", "key": "Q-1"})
    assert r.json()["result"]["title"] == "Q v2"  # текущая без as_of


async def test_snapshot_includes_new_master_fields(session):
    """volume_m3/vat_code попадают в SCD2-снимок (SNAPSHOT_FIELDS)."""
    sku = Sku(code="VOL-1", title="товар", unit="шт", volume_m3=0.05, vat_code="НДС20")
    session.add(sku)
    await session.flush()
    v = await record_sku_version(session, sku, date(2026, 1, 1))
    assert v.volume_m3 == 0.05
    assert v.vat_code == "НДС20"


async def test_sku_card_returns_new_master_fields(api, session):
    """Карточка SKU-витрины отдаёт volume_m3 и собственный vat_code."""
    session.add(Sku(code="VC-1", title="товар", unit="шт", volume_m3=0.12, vat_code="НДС20"))
    await session.commit()
    card = (await api.get("/system/sku/VC-1")).json()
    assert card["volume_m3"] == 0.12
    assert card["vat_code"] == "НДС20"


async def test_catalog_exposes_sku_history(api):
    """Каталог и AI-каталог содержат core.sku_history (версионный, ai_exposed)."""
    cat = (await api.get("/system/references")).json()
    assert "core.sku_history" in [r["key"] for r in cat["departments"]["Общие"]]

    ai = (await api.get("/system/references/ai-catalog")).json()
    meta = next(r for r in ai["references"] if r["key"] == "core.sku_history")
    assert meta["versioned"] is True
