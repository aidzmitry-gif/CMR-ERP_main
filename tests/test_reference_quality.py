"""Data-Quality движок справочников: пропуски / битые ссылки / дубли / сироты + score."""
from datetime import date
from decimal import Decimal

from core.domain.models import Counterparty, Sku
from core.domain.reference import NomenclatureCategory, TnvedCode, Unit
from core.services import reference_quality


async def test_audit_skus_missing_and_broken(session):
    session.add(TnvedCode(code="8536", name="реле", duty_rate=Decimal("5"), start_date=date(2020, 1, 1)))
    cat = NomenclatureCategory(code="CAT-1", name="Группа")
    session.add(cat)
    await session.flush()
    session.add_all([
        Sku(code="OK", title="ок", unit="шт", category_id=cat.id, tnved_code="8536"),
        Sku(code="NOUNIT", title="без ед", unit="", category_id=cat.id, tnved_code="8536"),
        Sku(code="NOCAT", title="без группы", unit="шт", category_id=None, tnved_code="8536"),
        Sku(code="BADTN", title="битый тн", unit="шт", category_id=cat.id, tnved_code="0000"),
        Sku(code="BADCAT", title="битая группа", unit="шт", category_id=99999, tnved_code="8536"),
    ])
    await session.commit()

    res = await reference_quality.audit_reference(session, "core.skus")
    by = {(i["kind"], i["field"]): i for i in res["issues"]}
    assert res["total"] == 5
    assert by[("missing", "unit")]["count"] == 1
    assert "NOUNIT" in by[("missing", "unit")]["sample_keys"]
    assert by[("missing", "category_id")]["count"] == 1  # NOCAT
    assert by[("broken_ref", "tnved_code")]["count"] == 1  # BADTN
    assert by[("broken_ref", "category_id")]["count"] == 1  # BADCAT
    assert res["score"] < 1.0


async def test_audit_skus_margin_blind(session):
    # группа с ТН ВЭД (наследуется) и группа без — для проверки own ∨ group
    session.add(TnvedCode(code="8536", name="реле", duty_rate=Decimal("5"), start_date=date(2020, 1, 1)))
    cat_no = NomenclatureCategory(code="CN", name="без ТН")
    cat_tn = NomenclatureCategory(code="CT", name="с ТН", tnved_code="8536")
    session.add_all([cat_no, cat_tn])
    await session.flush()
    session.add_all([
        Sku(code="BLIND", title="нет ТН нигде", unit="шт", category_id=cat_no.id, weight_kg=1.0),
        Sku(code="GROUPTN", title="ТН от группы", unit="шт", category_id=cat_tn.id, weight_kg=2.0),
    ])
    await session.commit()

    res = await reference_quality.audit_reference(session, "core.skus")
    mb = next((i for i in res["issues"] if i["kind"] == "margin_blind"), None)
    assert mb is not None
    assert "BLIND" in mb["sample_keys"]  # нет эфф. ТН ВЭД → слеп по марже
    assert "GROUPTN" not in mb["sample_keys"]  # ТН ВЭД унаследован от группы → НЕ слеп
    assert res["score"] < 1.0  # score учитывает вес margin_blind


async def test_margin_blind_imported_without_dimensions(session):
    # есть ТН ВЭД (импортный), но нет ни веса, ни объёма → фрахт не разнести
    session.add(TnvedCode(code="8507", name="акк", duty_rate=Decimal("10"), start_date=date(2020, 1, 1)))
    session.add(Sku(code="NODIM", title="без габаритов", unit="шт", tnved_code="8507"))
    await session.commit()
    res = await reference_quality.audit_reference(session, "core.skus")
    mb = next(i for i in res["issues"] if i["kind"] == "margin_blind")
    assert "NODIM" in mb["sample_keys"]


async def test_margin_blind_zero_weight_is_hole(session):
    # 0.0 вес И 0.0 объём = та же дыра, что None (нулевой вес физтовара не валиден) — не маскируем нулём
    session.add(TnvedCode(code="8507", name="акк", duty_rate=Decimal("10"), start_date=date(2020, 1, 1)))
    session.add(Sku(code="ZERO", title="нулевой вес", unit="шт", tnved_code="8507", weight_kg=0.0, volume_m3=0.0))
    await session.commit()
    res = await reference_quality.audit_reference(session, "core.skus")
    mb = next(i for i in res["issues"] if i["kind"] == "margin_blind")
    assert "ZERO" in mb["sample_keys"]


async def test_audit_clean_score_is_one(session):
    session.add_all([Unit(code="PCS", title="штука"), Unit(code="KG", title="килограмм")])
    await session.commit()
    res = await reference_quality.audit_reference(session, "core.units")
    assert res["score"] == 1.0
    assert res["issues"] == []


async def test_audit_simple_duplicate_title(session):
    session.add_all([Unit(code="PCS", title="Штука"), Unit(code="SHT", title="штука ")])
    await session.commit()
    res = await reference_quality.audit_reference(session, "core.units")
    dup = next(i for i in res["issues"] if i["kind"] == "duplicate")
    assert dup["count"] == 2
    assert set(dup["sample_keys"]) == {"PCS", "SHT"}
    assert res["score"] < 1.0


async def test_audit_category_orphan(session):
    root = NomenclatureCategory(code="C1", name="корень")
    session.add(root)
    await session.flush()
    session.add(NomenclatureCategory(code="C2", name="сирота", parent_id=99999))
    await session.commit()
    res = await reference_quality.audit_reference(session, "core.nomenclature_groups")
    orphan = next(i for i in res["issues"] if i["kind"] == "orphan")
    assert "C2" in orphan["sample_keys"]


async def test_audit_counterparties_missing_and_dup(session):
    session.add_all([
        Counterparty(name="ООО А", unp="123456789"),
        Counterparty(name="ООО А (дубль)", unp="123456789"),
        Counterparty(name="Без УНП", unp=None),
    ])
    await session.commit()
    res = await reference_quality.audit_reference(session, "core.counterparties")
    miss = next(i for i in res["issues"] if i["kind"] == "missing" and i["field"] == "unp")
    assert miss["count"] == 1
    dup = next(i for i in res["issues"] if i["kind"] == "duplicate")
    assert "123456789" in dup["sample_keys"]


async def test_audit_all_returns_scored_list(session):
    res = await reference_quality.audit_all(session)
    keys = {r["ref"] for r in res}
    assert {"core.skus", "core.counterparties", "core.units"} <= keys
    assert all(isinstance(r["score"], float) for r in res)


# ── эндпоинты (п.2) ───────────────────────────────────────────────────────────


async def test_quality_summary_endpoint(api, session):
    session.add(Unit(code="PCS", title="штука"))
    await session.commit()
    r = await api.get("/system/references/quality")
    assert r.status_code == 200
    refs = r.json()["references"]
    assert any(x["ref"] == "core.skus" for x in refs)
    assert all({"score", "by_kind", "issues_count"} <= set(x) for x in refs)


async def test_quality_detail_endpoint(api):
    r = await api.get("/system/references/quality/core.skus")
    assert r.status_code == 200
    body = r.json()
    assert body["ref"] == "core.skus"
    assert "issues" in body


async def test_quality_detail_unknown_404(api):
    assert (await api.get("/system/references/quality/core.nope")).status_code == 404


async def test_quality_requires_refs_view(api):
    # роль без refs.view и не супер → отказ по текущему контракту auth
    r = await api.get("/system/references/quality", headers={"X-User-Roles": "warehouse"})
    assert r.status_code in (401, 403)
