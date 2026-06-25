"""Survivorship-правила как данные (M2): чистый движок ``decide`` + provenance при импорте."""
from core.domain.models import Counterparty, SurvivorshipRule
from core.services import reference_import, survivorship
from core.services.survivorship import FieldValue, Rule

# —— чистый движок decide() (без БД) ——

def test_non_empty_wins_default():
    rule = Rule()  # дефолт
    cur = FieldValue("Точное имя", "manual")
    inc = FieldValue("Имя из 1С", "1c")
    assert survivorship.decide(cur, inc, rule).value == "Точное имя"  # эталон сохраняется
    # пустое заполняется
    assert survivorship.decide(FieldValue("", "1c"), inc, rule).value == "Имя из 1С"


def test_manual_only_blocks_sync():
    rule = Rule(strategy="manual_only")
    cur = FieldValue("+375 29 ручной", "manual")
    assert survivorship.decide(cur, FieldValue("+375 17 из 1С", "1c"), rule).value == "+375 29 ручной"
    # но ручная правка проходит
    assert survivorship.decide(cur, FieldValue("новый", "manual"), rule).value == "новый"


def test_source_priority_egr_beats_1c():
    rule = Rule(strategy="source_priority")  # дефолтный порядок egr>erp>manual>1c>bitrix
    cur = FieldValue("из 1С", "1c")
    assert survivorship.decide(cur, FieldValue("из ЕГР", "egr"), rule).value == "из ЕГР"
    # 1С не побеждает ЕГР
    cur_egr = FieldValue("из ЕГР", "egr")
    assert survivorship.decide(cur_egr, FieldValue("из 1С", "1c"), rule).value == "из ЕГР"


def test_most_recent_wins_by_date():
    rule = Rule(strategy="most_recent")
    cur = FieldValue("старый", "1c", "2026-06-01")
    inc = FieldValue("новый", "manual", "2026-06-18")
    assert survivorship.decide(cur, inc, rule).value == "новый"
    # старее входящее — не меняет
    old = FieldValue("ещё старее", "1c", "2026-05-01")
    assert survivorship.decide(cur, old, rule).value == "старый"


# —— интеграция: импорт пишет provenance и уважает правила ——

async def test_import_writes_provenance(session):
    r = await reference_import.upsert_counterparty(
        session, unp="191000001", name="ООО Новый", source="1c", external_ref="x1"
    )
    assert r.created is True
    assert r.counterparty.provenance["name"]["source"] == "1c"


async def test_manual_only_rule_protects_field_from_sync(session):
    # правило: имя меняется только вручную
    session.add(SurvivorshipRule(entity_type="counterparty", field="name", strategy="manual_only"))
    cp = Counterparty(name="Имя вручную", unp="191000002",
                      provenance={"name": {"source": "manual", "at": "2026-06-18"}})
    session.add(cp)
    await session.flush()

    r = await reference_import.upsert_counterparty(
        session, unp="191000002", name="Имя из 1С", source="1c", external_ref="y1"
    )
    assert cp.name == "Имя вручную"  # синк из 1С НЕ затёр ручное
    assert "name" not in r.updated_fields


async def test_source_priority_rule_lets_egr_win_over_existing_1c(session):
    session.add(SurvivorshipRule(
        entity_type="counterparty", field="name", strategy="source_priority",
        source_priority=["egr", "erp", "manual", "1c", "bitrix"],
    ))
    cp = Counterparty(name="Имя из 1С", unp="191000003",
                      provenance={"name": {"source": "1c", "at": "2026-06-02"}})
    session.add(cp)
    await session.flush()

    await reference_import.upsert_counterparty(
        session, unp="191000003", name="ОАО из ЕГР", source="egr", external_ref="z1"
    )
    assert cp.name == "ОАО из ЕГР"  # ЕГР приоритетнее 1С → перезаписал
    assert cp.provenance["name"]["source"] == "egr"
