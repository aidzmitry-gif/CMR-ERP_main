"""Витрина правил слияния (survivorship, M2): GET /system/mdm/rules.

Эндпоинт читает таблицу survivorship_rule для живого экрана «Правила слияния».
"""
from core.domain.models import SurvivorshipRule


async def test_rules_empty_by_default(api):
    assert (await api.get("/system/mdm/rules")).json() == {"rules": []}


async def test_rules_listed_and_filtered(api, session):
    session.add_all([
        SurvivorshipRule(
            entity_type="counterparty", field="unp",
            strategy="source_priority", source_priority=["egr", "erp", "1c"],
        ),
        SurvivorshipRule(
            entity_type="counterparty", field="phone", strategy="most_recent", source_priority=[],
        ),
        SurvivorshipRule(
            entity_type="sku", field="weight_kg", strategy="manual_only", source_priority=[],
        ),
    ])
    await session.commit()

    # все правила
    rules = (await api.get("/system/mdm/rules")).json()["rules"]
    assert len(rules) == 3
    by_field = {r["field"]: r for r in rules}
    assert by_field["unp"]["strategy"] == "source_priority"
    assert by_field["unp"]["source_priority"] == ["egr", "erp", "1c"]
    assert by_field["weight_kg"]["entity_type"] == "sku"

    # фильтр по сущности
    cp_only = (await api.get("/system/mdm/rules", params={"entity_type": "counterparty"})).json()
    assert {r["field"] for r in cp_only["rules"]} == {"unp", "phone"}
