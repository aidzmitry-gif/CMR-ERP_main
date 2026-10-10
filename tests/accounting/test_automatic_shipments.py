from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from modules.accounting import automatic_shipments, models, service, shipment_preview
from tests.accounting.test_shipment_preview import fixture

ACCOUNTS = dict(buyer_account="62", revenue_account="90.1", vat_revenue_account="90.2",
                vat_payable_account="68.2", expense_account="90.4")


def policy(settings=None):
    return dict(effective_from="2026-09-02", reference="Synthetic sales policy",
        inventory_method="specific", allocation_basis="direct_cost", depreciation_method="straight_line",
        normative_reference="Synthetic fixture only", normative_verified=True,
        document_posting={"purchase": {}, "sales": settings or ACCOUNTS})


async def setup(client, db, book, posting):
    receipt, raw = await fixture(db, book, posting)
    response = await client.post(f"/accounting/organizations/{book[0]}/policies", json=policy())
    assert response.status_code == 201, response.text
    raw["policy_id"] = response.json()["id"]
    raw["posting_date"] = raw["document_date"] = "2026-09-02"
    receipt["snapshot"]["operation_date"] = "2026-09-02"
    gateway = AsyncMock()
    gateway.accounting_shipment_source.return_value = {"receipt": receipt}
    client.test_app.state.core.services.wms_reservations = gateway
    client.test_app.state.core.services.sales_source = SimpleNamespace()
    automatic = automatic_shipments.automatic_input(shipment_preview.ShipmentPlanInput(**raw))
    return receipt, raw, automatic.model_dump(mode="json", exclude_none=True), gateway


async def test_auto_whole_act_accounts_native_amounts_and_durable_replay(client, db, book, posting, monkeypatch):
    receipt, original, body, gateway = await setup(client, db, book, posting)
    base = f"/accounting/organizations/{book[0]}/shipments/{receipt['source_key']}"
    options = await client.get(f"/accounting/organizations/{book[0]}/shipments/auto-rules?on=2026-09-02")
    assert options.json() == {"organization_id": book[0], "policy_id": original["policy_id"], "accounts": ACCOUNTS,
                             "inventory_accounts": ["41.2"]}
    assert all("account" not in row for row in body["allocations"])
    preview = await client.post(base + "/auto-preview", json=body)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["resolved_command"] == shipment_preview.ShipmentPlanInput(**original).model_dump(mode="json")
    assert (plan["net_byn"], plan["vat_byn"], plan["gross_byn"]) == ("40.00", "8.00", "48.00")
    assert [row["cost_byn"] for row in plan["mapping"]] == ["3.33", "6.67"]
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1
    command = {**plan["resolved_command"], "expected_basis_digest": plan["basis_digest"]}
    first = await client.post(base + "/auto-confirm", json=command)
    assert first.status_code == 201, first.text
    await db.commit()
    lines = (await db.scalars(select(models.Line).where(models.Line.entry_id == first.json()["anchor_entry_id"]))).all()
    expected = {("62", "debit"): "48", ("90.1", "credit"): "48", ("90.2", "debit"): "8",
                ("68.2", "credit"): "8", ("90.4", "debit"): "10", ("41.2", "credit"): "10"}
    for key, amount in expected.items():
        assert sum((line.amount for line in lines if (line.account_code, line.side) == key), Decimal(0)) == Decimal(amount)
    assert sum((line.quantity for line in lines if line.account_code == "41.2"), Decimal(0)) == 3
    assert sum((line.amount * (1 if line.side == "debit" else -1) for line in lines), Decimal(0)) == 0
    count = await db.scalar(select(func.count()).select_from(models.Entry))
    async def forbidden(*args, **kwargs):
        raise AssertionError("Saved replay must not resolve current policy")
    monkeypatch.setattr(automatic_shipments, "resolve_command", forbidden)
    replay = await client.post(base + "/auto-confirm", json=command)
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == count
    assert gateway.accounting_shipment_source.await_count == 3
    changed = deepcopy(command)
    changed["commercial_lines"][0]["net_amount"] = "20.01"
    assert (await client.post(base + "/auto-confirm", json=changed)).status_code == 409


@pytest.mark.parametrize("field,code", [("buyer_account", "51"), ("revenue_account", "62"),
    ("vat_revenue_account", "90.4"), ("vat_payable_account", "60"), ("expense_account", "90.1")])
async def test_policy_refuses_wrong_sale_account_roles(client, db, book, posting, field, code):
    await fixture(db, book, posting)
    response = await client.post(f"/accounting/organizations/{book[0]}/policies", json=policy({**ACCOUNTS, field: code}))
    assert response.status_code == 422, response.text
    assert await db.scalar(select(func.count()).select_from(models.Policy)) == 1


@pytest.mark.parametrize("case", ["wrong_policy", "stale_act", "short_quantity", "missing_analytics", "wrong_invoice"])
async def test_auto_source_policy_and_allocation_holds_have_no_posting(client, db, book, posting, case):
    receipt, original, body, gateway = await setup(client, db, book, posting)
    if case == "wrong_policy":
        body["policy_id"] = book[1]
    elif case == "stale_act":
        body["expected_act_digest"] = "b" * 64
    elif case == "short_quantity":
        body["allocations"][0]["quantity"] = "0.5"
    elif case == "missing_analytics":
        body["commercial_lines"][0]["buyer_dimensions"].pop("contract")
    else:
        body["commercial_lines"][0]["buyer_dimensions"]["settlement_document"] = "sales:document:999"
    response = await client.post(f"/accounting/organizations/{book[0]}/shipments/{receipt['source_key']}/auto-preview", json=body)
    assert response.status_code == 409, response.text
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1
    assert await db.scalar(select(models.SourceControl.entry_id)) is None


async def test_fresh_confirmation_rejects_changed_accounts_and_terms(client, db, book, posting):
    receipt, original, body, gateway = await setup(client, db, book, posting)
    base = f"/accounting/organizations/{book[0]}/shipments/{receipt['source_key']}"
    plan = (await client.post(base + "/auto-preview", json=body)).json()
    original_command = {**plan["resolved_command"], "expected_basis_digest": plan["basis_digest"]}
    for case in ("account", "term", "basis"):
        command = deepcopy(original_command)
        if case == "account":
            command["commercial_lines"][0]["buyer_account"] = "51"
        elif case == "term":
            command["commercial_lines"][0]["net_amount"] = "20.01"
        else:
            command["expected_basis_digest"] = "b" * 64
        response = await client.post(base + "/auto-confirm", json=command)
        assert response.status_code == 409, response.text
        assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1
    # Immutable new version changes the policy selection even if rules are equal.
    newer = policy()
    newer["effective_from"] = "2026-09-03"
    assert (await client.post(f"/accounting/organizations/{book[0]}/policies", json=newer)).status_code == 201
    assert (await client.get(f"/accounting/organizations/{book[0]}/shipments/auto-rules?on=2026-09-03")).json()["policy_id"] != original["policy_id"]
    assert (await client.post(base + "/auto-confirm", json={**original_command, "posting_date": "2026-09-03"})).status_code == 409


async def test_auto_dto_refuses_account_override_and_wrong_org_before_gateway(client, db, book, posting):
    receipt, original, body, gateway = await setup(client, db, book, posting)
    base = f"/accounting/organizations/{book[0]}/shipments/{receipt['source_key']}"
    changed = deepcopy(body)
    changed["commercial_lines"][0]["buyer_account"] = "62"
    assert (await client.post(base + "/auto-preview", json=changed)).status_code == 422
    assert (await client.post(f"/accounting/organizations/999/shipments/{receipt['source_key']}/auto-preview", json=body)).status_code == 403
    gateway.accounting_shipment_source.assert_not_awaited()


async def test_missing_sales_settings_and_future_or_quantitative_accounts_hold(client, db, book, posting):
    receipt, raw = await fixture(db, book, posting)
    command = automatic_shipments.automatic_input(shipment_preview.ShipmentPlanInput(**raw))
    with pytest.raises(service.AccountingError, match="не настроены"):
        await automatic_shipments.resolve_command(db, book[0], command, receipt)
    for i, attrs in enumerate([dict(valid_from=date(2026, 10, 1)), dict(quantity_tracking=True), dict(cash=True)]):
        code = f"62.{i+1}"
        values = dict(organization_id=book[0], code=code, title=code, category="asset", valid_from=date(2026, 1, 1),
            required_dimensions=[], currency_tracking=False, quantity_tracking=False, cash=False, normative_ref="synthetic")
        db.add(models.Account(**{**values, **attrs}))
        await db.commit()
        response = await client.post(f"/accounting/organizations/{book[0]}/policies", json=policy({**ACCOUNTS, "buyer_account": code}))
        assert response.status_code == 422, response.text


@pytest.mark.parametrize("case", ["ambiguous", "other_warehouse", "other_sku", "other_lot", "future"])
async def test_inventory_account_resolution_uses_exact_source_and_cutoff(client, db, book, posting, case):
    receipt, original, body, _ = await setup(client, db, book, posting)
    db.add(models.Account(organization_id=book[0], code="41.3", title="Second stock account",
        category="asset", valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
        quantity_tracking=True, cash=False, normative_ref="Synthetic fixture only"))
    await db.commit()
    extra = posting("second-account", "41.3", "60", amount="1.00",
                    posting_date="2026-09-03" if case == "future" else "2026-09-02")
    extra.policy_id = original["policy_id"]
    extra.lines[0].quantity = Decimal("1")
    extra.lines[0].dimensions = {"warehouse": "other" if case == "other_warehouse" else "W",
        "sku": "other" if case == "other_sku" else "SKU", "lot": "other" if case == "other_lot" else "lot1"}
    await service.post(db, book[0], extra, "tester")
    await db.commit()
    count = await db.scalar(select(func.count()).select_from(models.Entry))
    response = await client.post(f"/accounting/organizations/{book[0]}/shipments/{receipt['source_key']}/auto-preview", json=body)
    assert response.status_code == (409 if case == "ambiguous" else 200), response.text
    if case == "ambiguous":
        assert "однозначно" in response.json()["detail"]
    else:
        assert {row["account"] for row in response.json()["resolved_command"]["allocations"]} == {"41.2"}
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == count
    assert await db.scalar(select(models.SourceControl.entry_id)) is None


@pytest.mark.parametrize("case", ["no_lot", "foreign_line", "wrong_legacy_account", "valid_legacy_account"])
async def test_inventory_account_missing_and_override_controls(client, db, book, posting, case):
    receipt, original, body, _ = await setup(client, db, book, posting)
    if case == "no_lot":
        body["allocations"][0]["lot"] = "absent"
    elif case == "foreign_line":
        body["allocations"][0]["line_source"] = "foreign"
    else:
        body["allocations"][0]["account"] = "41.2" if case == "valid_legacy_account" else "41.3"
    response = await client.post(f"/accounting/organizations/{book[0]}/shipments/{receipt['source_key']}/auto-preview", json=body)
    assert response.status_code == (200 if case == "valid_legacy_account" else 409), response.text
    if case == "valid_legacy_account":
        assert response.json()["resolved_command"]["allocations"][0]["account"] == original["allocations"][0]["account"]
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1
    assert await db.scalar(select(models.SourceControl.entry_id)) is None
