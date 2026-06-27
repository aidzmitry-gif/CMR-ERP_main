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
