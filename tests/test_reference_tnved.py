"""Справочник ТН ВЭД ЕАЭС (SCD2) + lookup ставок на дату — вход расчёта landed cost.

Версионный справочник как курсы/НДС: версии по датам; lookup резолвит пошлину + ставку НДС
(из ref_vat_rate по мягкой ссылке vat_code) на дату оформления.
"""
from datetime import date

from core.domain.reference import TnvedCode, VatRate


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
