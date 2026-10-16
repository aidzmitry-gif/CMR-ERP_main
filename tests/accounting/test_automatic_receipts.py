from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from core.domain.models import Sku, User
from core.domain.reference import NomenclatureCategory
from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Account, Audit, Entry, Policy
from modules.accounting.schemas import DocumentPostingPolicyInput
from tests.accounting.test_procurement_receipt_drafts import document

pytestmark = pytest.mark.usefixtures("receipt_catalog_sku")


def policy_command(settings=None, effective="2026-09-01"):
    return dict(effective_from=effective, reference="Synthetic automatic purchase test",
        inventory_method="specific", allocation_basis="direct_cost", depreciation_method="straight_line",
        normative_reference="Synthetic fixture, not statutory approval", normative_verified=False,
        document_posting={"purchase": settings if settings is not None else {
            "default_inventory_account": "41.01", "default_settlement_account": "60.01", "vat_account": "18.03"}})


async def configure(client, db, book, settings=None, effective="2026-09-01"):
    for code, quantity, category in [("10.01", True, "asset"), ("10.09", True, "asset"),
            ("41.01", True, "asset"), ("60.01", False, "liability"), ("60.02", False, "liability"),
            ("18.03", False, "asset")]:
        if await db.scalar(select(Account.id).where(Account.organization_id == book[0], Account.code == code)) is None:
            db.add(Account(organization_id=book[0], code=code, title=code, category=category,
                valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                quantity_tracking=quantity, cash=False, normative_ref="synthetic"))
    await db.commit()
    response = await client.post(f"/accounting/organizations/{book[0]}/policies", json=policy_command(settings, effective))
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def receipt(client, book, facts=None):
    response = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents",
        json={"key": "automatic", "document": facts or document()})
    assert response.status_code == 201, response.text
    return f"/accounting/organizations/{book[0]}/receipts/{response.json()['id']}"


async def preview(client, path, version=1, on="2026-09-02"):
    return await client.post(path + "/auto-preview", json={"expected_version": version, "posting_date": on})


async def test_auto_posting_exact_amounts_idempotent_retry_and_immutable_policy(client, db, book):
    policy_id = await configure(client, db, book)
    path = await receipt(client, book)
    response = await preview(client, path)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["resolved_options"] == dict(expected_version=1, posting_date="2026-09-02",
        policy_id=policy_id, settlement_account="60.01", vat_account="18.03", inventory_accounts=["41.01"])
    assert [(row["account"], row["side"], Decimal(row["amount"])) for row in result["lines"]] == [
        ("41.01", "debit", Decimal("100.01")), ("18.03", "debit", Decimal("20.00")),
        ("60.01", "credit", Decimal("120.01"))]
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0
    command = {**result["resolved_options"], "digest": result["digest"]}
    tampered = await client.post(path + "/auto-confirm", json={**command, "settlement_account": "60.02"})
    assert tampered.status_code == 409
    assert (await client.post(path + "/auto-confirm", json={**command, "digest": "f" * 64})).status_code == 409
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0
    confirmed = await client.post(path + "/auto-confirm", json=command)
    assert confirmed.status_code == 201, confirmed.text
    settings = dict(default_inventory_account="10.01", default_settlement_account="60.02", vat_account="18.03")
    await configure(client, db, book, settings, effective="2026-09-03")
    replay = await client.post(path + "/auto-confirm", json=command)
    assert replay.status_code == 201, replay.text
    assert replay.json()["entry_id"] == confirmed.json()["entry_id"]
    assert await db.scalar(select(func.count()).select_from(Entry)) == 1
    assert (await preview(client, path)).status_code == 409
    policy = await db.get(Policy, policy_id)
    policy.document_posting = {"purchase": settings}
    with pytest.raises(ValueError, match="immutable"):
        await db.flush()
    await db.rollback()


async def test_selection_sku_over_category_over_explicit_default_and_supplier_override(client, db, book):
    connection = await db.connection()
    await connection.run_sync(lambda c: NomenclatureCategory.__table__.create(c, checkfirst=True))
    db.add(NomenclatureCategory(id=1, code="C1", name="Synthetic group", is_active=True))
    sku = await db.get(Sku, 1)
    sku.category_id = 1
    db.add_all([Sku(id=2, code="sku2", title="SKU2", unit="шт", category_id=1, is_active=True),
                Sku(id=3, code="sku3", title="SKU3", unit="шт", is_active=True)])
    await db.commit()
    settings = dict(default_inventory_account="41.01", inventory_by_sku={"1": "10.01"},
        inventory_by_category={"1": "10.09"}, default_settlement_account="60.01",
        settlement_by_supplier={"1": "60.02"}, vat_account="18.03")
    await configure(client, db, book, settings)
    facts = document()
    facts["items"] += [{**facts["items"][0], "sku_id": i, "sku": f"sku{i}", "sku_title": f"SKU{i}"} for i in [2, 3]]
    path = await receipt(client, book, facts)
    result = await preview(client, path)
    assert result.status_code == 200, result.text
    assert result.json()["resolved_options"]["inventory_accounts"] == ["10.01", "10.09", "41.01"]
    assert result.json()["resolved_options"]["settlement_account"] == "60.02"


async def test_missing_config_version_company_and_missing_vat_fail_without_entries(client, db, book):
    path = await receipt(client, book)
    assert (await preview(client, path)).status_code == 409
    await configure(client, db, book, dict(default_inventory_account="41.01", default_settlement_account="60.01"))
    assert (await preview(client, path)).status_code == 409
    assert (await preview(client, path, version=2)).status_code == 409
    assert (await preview(client, path.replace(f"/{book[0]}/receipts", "/999/receipts"))).status_code == 403
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


async def test_zero_vat_omits_vat_account_and_new_policy_invalidates_unposted_preview(client, db, book):
    await configure(client, db, book)
    facts = document()
    facts["items"][0].update(vat_amount="0.00", vat_rate="0")
    path = await receipt(client, book, facts)
    result = await preview(client, path, on="2026-09-05")
    assert result.status_code == 200, result.text
    command = {**result.json()["resolved_options"], "digest": result.json()["digest"]}
    assert command["vat_account"] is None
    assert len(result.json()["lines"]) == 2
    await configure(client, db, book, dict(default_inventory_account="10.01", default_settlement_account="60.01"), "2026-09-04")
    assert (await client.post(path + "/auto-confirm", json=command)).status_code == 409
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


async def test_invalid_account_selector_and_reader_are_refused_and_config_is_audited(client, db, book):
    await configure(client, db, book)
    selector = await client.get(f"/accounting/organizations/{book[0]}/purchase-posting-selector", params={"kind": "sku", "selector_id": 1})
    assert selector.json() == {"organization_id": book[0], "kind": "sku", "id": 1, "title": "Synthetic receipt item"}
    assert (await client.get(f"/accounting/organizations/{book[0]}/purchase-posting-selector", params={"kind": "supplier", "selector_id": 999})).status_code == 404
    for change in [{"default_inventory_account": "60.01"}, {"inventory_by_sku": {"999": "41.01"}},
                   {"settlement_by_supplier": {"999": "60.01"}}]:
        response = await client.post(f"/accounting/organizations/{book[0]}/policies",
            json=policy_command({**policy_command()["document_posting"]["purchase"], **change}, "2026-09-03"))
        assert response.status_code == 422, response.text
    audit = (await db.scalars(select(Audit).where(Audit.action == "policy_approved"))).all()
    assert any(row.detail.get("document_posting", {}).get("purchase", {}).get("default_inventory_account") == "41.01" for row in audit)
    path = await receipt(client, book)
    result = await preview(client, path)
    command = {**result.json()["resolved_options"], "digest": result.json()["digest"]}
    db.add(User(username="reader", full_name="Synthetic reader", role="finance", status="active"))
    db.add(AccessGrant(organization_id=book[0], subject="reader", role="reader"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("reader", ["finance"])
    assert (await client.post(path + "/auto-confirm", json=command)).status_code == 403
    assert (await client.post(f"/accounting/organizations/{book[0]}/policies", json=policy_command(effective="2026-09-06"))).status_code == 403
    assert (await client.get(f"/accounting/organizations/{book[0]}/purchase-posting-selector", params={"kind": "sku", "selector_id": 1})).status_code == 403
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


@pytest.mark.parametrize("key", ["0", "01", "-1", "1.0", "true", "2147483648"])
def test_selector_keys_are_exact_native_ids(key):
    with pytest.raises(ValidationError):
        DocumentPostingPolicyInput.model_validate({"purchase": {"inventory_by_sku": {key: "41.01"}}})
