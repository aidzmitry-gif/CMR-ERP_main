from copy import deepcopy

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from modules.accounting.assembly_estimate import AssemblyEstimateInput, calculate
from modules.accounting.expense_models import ExpenseArticle, ExpenseGroup
from modules.accounting.models import Entry, Organization


def example():
    return {"product": "Battery assembly", "quantity": "10", "purpose": "customer_order",
            "reference": "Order-17", "specification": "BOM v2", "as_of": "2026-09-28",
            "components": [{"name": "Cell", "per_unit": "4", "loss_percent": "5",
                            "unit_cost_byn": "2.5", "price_basis": "Supplier quote 28/09"},
                           {"name": "Case", "per_unit": "1", "unit_cost_byn": "3",
                            "price_basis": "Landed cost"}],
            "batch_costs": {"labor_byn": "20", "contributions_byn": "7", "subcontract_byn": "0",
                            "overhead_byn": "10", "packaging_byn": "5"},
            "sale_unit_net_byn": "30"}


@pytest.mark.parametrize("purpose", ["customer_order", "stock"])
def test_batch_and_unit_cost_and_gross_margin(purpose):
    data = example()
    data["purpose"] = purpose
    result = calculate(AssemblyEstimateInput(**data))
    assert result["lines"][0]["quantity"] == "42.00"
    assert result["known_components_byn"] == "135.00"
    assert result["total_cost_byn"] == "177.00"
    assert result["unit_cost_byn"] == "17.700000"
    assert result["gross_profit_byn"] == "123.00"
    assert result["margin_percent"] == "41.00"
    assert result["posted"] is False


def test_missing_cost_never_becomes_zero_or_false_profit():
    data = example()
    data["components"][0]["unit_cost_byn"] = None
    result = calculate(AssemblyEstimateInput(**data))
    assert result["status"] == "incomplete"
    assert result["known_components_byn"] == "30.00"
    assert result["missing_price_lines"] == [1]
    assert all(result[field] is None for field in ("total_cost_byn", "unit_cost_byn", "gross_profit_byn", "margin_percent"))


def test_zero_sale_price_is_loss_with_undefined_margin_and_zero_cost_requires_evidence():
    data = example()
    data["sale_unit_net_byn"] = "0"
    result = calculate(AssemblyEstimateInput(**data))
    assert result["gross_profit_byn"] == "-177.00" and result["margin_percent"] is None
    data["components"][0].update(unit_cost_byn="0", price_basis="")
    with pytest.raises(ValidationError):
        AssemblyEstimateInput(**data)


@pytest.mark.parametrize("bad", [True, 0, -1, 1.1, "NaN", "Infinity", "0.0000001", ""])
def test_invalid_quantity_rejected(bad):
    data = example()
    data["quantity"] = bad
    with pytest.raises(ValidationError):
        AssemblyEstimateInput(**data)


def test_rounding_at_line_and_total_not_rounded_unit_cost():
    data = example()
    data.update(quantity="3", sale_unit_net_byn=None,
                components=[{"name": "C", "per_unit": "1", "unit_cost_byn": "0.335", "price_basis": "Quote"}])
    data["batch_costs"] = {key: "0" for key in data["batch_costs"]}
    result = calculate(AssemblyEstimateInput(**data))
    assert result["total_cost_byn"] == "1.01"
    assert result["unit_cost_byn"] == "0.336667"
    assert result["gross_profit_byn"] is None


async def test_authorized_preview_has_no_ledger_effect_and_denies_other_book(client, db, book):
    before = await db.scalar(select(func.count()).select_from(Entry))
    response = await client.post(f"/accounting/organizations/{book[0]}/assembly-estimate", json=example())
    assert response.status_code == 200, response.text
    assert response.json()["organization_id"] == book[0]
    assert response.json()["total_cost_byn"] == "177.00"
    assert response.headers["cache-control"] == "private, no-store"
    assert await db.scalar(select(func.count()).select_from(Entry)) == before
    denied = await client.post("/accounting/organizations/999/assembly-estimate", json=example())
    assert denied.status_code in (403, 404)
    invalid = deepcopy(example())
    invalid["batch_costs"]["labor_byn"] = -1
    response = await client.post(f"/accounting/organizations/{book[0]}/assembly-estimate", json=invalid)
    assert response.status_code == 422


async def test_estimate_binds_only_active_expense_articles_from_selected_book(client, db, book):
    group = ExpenseGroup(organization_id=book[0], code="production", title="Производство")
    db.add(group)
    await db.flush()
    local = ExpenseArticle(organization_id=book[0], group_id=group.id, code="assembly_labor",
                           title="Оплата сборки")
    other_org = Organization(name="Other synthetic company", unp="888888888")
    db.add_all([local, other_org])
    await db.flush()
    other_group = ExpenseGroup(organization_id=other_org.id, code="production", title="Other production")
    db.add(other_group)
    await db.flush()
    foreign = ExpenseArticle(organization_id=other_org.id, group_id=other_group.id,
                             code="assembly_labor", title="Foreign labor")
    db.add(foreign)
    await db.flush()

    data = example()
    data["batch_cost_articles"] = [{"category": "labor_byn", "article_id": local.id}]
    response = await client.post(f"/accounting/organizations/{book[0]}/assembly-estimate", json=data)
    assert response.status_code == 200, response.text
    assert response.json()["cost_article_snapshots"]["labor_byn"] == {
        "id": local.id, "code": "assembly_labor", "title": "Оплата сборки", "group_title": "Производство"
    }

    data["batch_cost_articles"] = [{"category": "labor_byn", "article_id": foreign.id}]
    response = await client.post(f"/accounting/organizations/{book[0]}/assembly-estimate", json=data)
    assert response.status_code == 422
    local.active = False
    await db.flush()
    data["batch_cost_articles"] = [{"category": "labor_byn", "article_id": local.id}]
    response = await client.post(f"/accounting/organizations/{book[0]}/assembly-estimate", json=data)
    assert response.status_code == 422


def test_duplicate_cost_article_categories_are_rejected():
    data = example()
    data["batch_cost_articles"] = [
        {"category": "labor_byn", "article_id": 1},
        {"category": "labor_byn", "article_id": 2},
    ]
    with pytest.raises(ValidationError):
        AssemblyEstimateInput(**data)
