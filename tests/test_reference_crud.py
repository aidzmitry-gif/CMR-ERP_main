"""CRUD системных справочников ядра: простой (units) + версионный SCD2 (currency-rates).

На SQLite через `api`-фикстуру (create_all, без seed). Проверяем архив через is_active,
валидацию required и корректность полуоткрытого интервала [start, end) при чтении на дату.
"""


async def test_simple_ref_crud_and_archive(api):
    # пусто на старте
    assert (await api.get("/system/refs/units")).json() == []

    # create
    r = await api.post("/system/refs/units", json={"code": "шт", "title": "Штука"})
    assert r.status_code == 200
    assert r.json()["code"] == "шт"
    assert r.json()["is_active"] is True

    # валидация required
    assert (await api.post("/system/refs/units", json={"title": "без кода"})).status_code == 422

    # list
    assert [u["code"] for u in (await api.get("/system/refs/units")).json()] == ["шт"]

    # patch
    r = await api.patch("/system/refs/units/шт", json={"title": "Штука (ед.)"})
    assert r.status_code == 200
    assert r.json()["title"] == "Штука (ед.)"

    # archive (soft-delete): исчезает из дефолтного списка, виден с archived=true
    assert (await api.delete("/system/refs/units/шт")).status_code == 200
    assert (await api.get("/system/refs/units")).json() == []
    arch = (await api.get("/system/refs/units", params={"archived": "true"})).json()
    assert arch[0]["code"] == "шт"
    assert arch[0]["is_active"] is False

    # patch несуществующего → 404
    assert (await api.patch("/system/refs/units/нет", json={"title": "x"})).status_code == 404


async def test_ref_mutations_emit_audit_events(api, session):
    """M1: create/patch/archive справочника пишут событие в outbox (concept §8 — аудит правок)."""
    from sqlalchemy import select

    from core.domain.models import OutboxEvent

    await api.post("/system/refs/units", json={"code": "кг", "title": "Килограмм"})
    await api.patch("/system/refs/units/кг", json={"title": "Килограмм (масса)"})
    await api.delete("/system/refs/units/кг")

    rows = (
        await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "reference.ref_unit.changed")
        )
    ).scalars().all()
    actions = {r.payload["action"] for r in rows}
    assert {"create", "update", "archive"} <= actions
    assert all(r.payload["entity_ref"] == "ref_unit:кг" for r in rows)


async def test_versioned_ref_scd2(api):
    base = "/system/refs/currency-rates"

    # первая версия (открытая)
    r = await api.post(
        f"{base}/versions", json={"currency_code": "USD", "start_date": "2026-01-01", "rate": "3.18"}
    )
    assert r.status_code == 200

    # вторая версия закрывает первую датой начала
    r = await api.post(
        f"{base}/versions", json={"currency_code": "USD", "start_date": "2026-05-01", "rate": "3.25"}
    )
    assert r.status_code == 200

    # текущая = последняя, end_date пуст
    cur = (await api.get(f"{base}/current", params={"key": "USD"})).json()
    assert float(cur["rate"]) == 3.25
    assert cur["end_date"] is None

    # на дату внутри первого периода → старая ставка
    a = (await api.get(f"{base}/as-of", params={"key": "USD", "on": "2026-03-01"})).json()
    assert float(a["rate"]) == 3.18

    # граница: start включительно, «по» — нет → на 2026-05-01 уже новая
    b = (await api.get(f"{base}/as-of", params={"key": "USD", "on": "2026-05-01"})).json()
    assert float(b["rate"]) == 3.25

    # все версии по ключу
    assert len((await api.get(base, params={"key": "USD"})).json()) == 2

    # версия с датой не позже текущей открытой → 409 (защита от перекрытия)
    bad = await api.post(
        f"{base}/versions", json={"currency_code": "USD", "start_date": "2026-04-01", "rate": "3.30"}
    )
    assert bad.status_code == 409
