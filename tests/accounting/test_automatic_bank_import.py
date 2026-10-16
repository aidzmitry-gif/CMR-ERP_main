from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from modules.accounting import automatic_bank_import, bank_import
from modules.accounting.models import Account, BankImportReceipt, Entry, Line, SourceBinding
from modules.accounting.schemas import DocumentPostingPolicyInput
from modules.finance.models import BankTransaction
from tests.accounting.test_bank_import import map_source


def policy(rules=None):
    return dict(effective_from="2026-09-01", reference="Synthetic bank policy",
        inventory_method="specific", allocation_basis="direct_cost", depreciation_method="straight_line",
        normative_reference="Synthetic fixture, not statutory approval", normative_verified=True,
        document_posting={"purchase": {}, "bank": {"rules": rules or {
            "buyer_receipt": dict(title="Buyer receipt", direction="receipt", settlement_account="62", cash_activity="operating"),
            "supplier_payment": dict(title="Supplier payment", direction="payment", settlement_account="60", cash_activity="operating")}}})


async def setup(client, db, book, direction="receipt", rules=None):
    configured = await client.post(f"/accounting/organizations/{book[0]}/policies", json=policy(rules))
    assert configured.status_code == 201, configured.text
    source = BankTransaction(ext_id="AUTO-BANK-1", occurred_on=date(2026, 9, 3), amount="123.45", currency="BYN",
        account_code="main", source_provider="synthetic-bank", direction=direction, purpose="No account inferred from purpose")
    db.add(source)
    await db.commit()
    db.add(SourceBinding(organization_id=book[0], source_type="finance_bank_transaction", source_id=source.id,
        ownership="own", evidence="Synthetic reviewed source ownership", actor="tester"))
    await db.commit()
    await map_source(db, book[0], source)
    return source, dict(request_key=str(uuid4()), source_transaction_id=source.id,
        source_digest=bank_import._digest(bank_import.source_snapshot(source)), policy_id=configured.json()["id"],
        posting_date="2026-09-04", rule_key="supplier_payment" if direction == "payment" else "buyer_receipt",
        settlement_dimensions={"counterparty": "reviewed-party", "contract": "reviewed-contract"}, explanation="Reviewed operation")


def confirmation(plan, key):
    return {"rule_key": key, "command": {**plan["resolved_command"], "basis_digest": plan["basis_digest"], "digest": plan["digest"]}}


@pytest.mark.parametrize("direction,expected", [("receipt", [("51", "debit"), ("62", "credit")]),
    ("payment", [("60", "debit"), ("51", "credit")])])
async def test_bank_automatic_posts_exact_native_sides_and_saved_replay(client, db, book, monkeypatch, direction, expected):
    source, command = await setup(client, db, book, direction)
    path = f"/accounting/organizations/{book[0]}/bank-import"
    options = await client.get(path + "/auto-rules?on=2026-09-04")
    assert options.status_code == 200, options.text
    assert options.json()["policy_id"] == command["policy_id"]
    preview = await client.post(path + "/auto-preview", json=command)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert sorted((r["account"], r["side"]) for r in plan["lines"]) == sorted(expected)
    assert all(r["amount"] == "123.45" for r in plan["lines"])
    assert plan["resolved_command"]["bank_dimensions"] == {}
    assert await db.scalar(select(func.count(Entry.id))) == 0
    body = confirmation(plan, command["rule_key"])
    result = await client.post(path + "/auto-confirm", json=body)
    assert result.status_code == 201, result.text
    entry = result.json()["entry_id"]
    assert result.json()["organization_id"] == book[0]
    assert result.json()["source_transaction_id"] == source.id
    lines = (await db.scalars(select(Line).where(Line.entry_id == entry))).all()
    assert len(lines) == 2
    assert next(r for r in lines if r.account_code != "51").dimensions["counterparty"] == "reviewed-party"
    # An unknown HTTP outcome must replay the saved command before current facts.
    source.amount = "999.99"
    await db.commit()
    async def forbidden(*args, **kwargs):
        raise AssertionError("saved replay must not resolve today's policy/source/mapping")
    monkeypatch.setattr(automatic_bank_import, "resolve_command", forbidden)
    replay = await client.post(path + "/auto-confirm", json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()["entry_id"] == entry
    assert await db.scalar(select(func.count(Entry.id))) == 1
    assert await db.scalar(select(func.count(BankImportReceipt.entry_id))) == 1
    changed = {**body, "command": {**body["command"], "settlement_dimensions": {"counterparty": "other"}}}
    assert (await client.post(path + "/auto-confirm", json=changed)).status_code == 409


@pytest.mark.parametrize("change", [{"rule_key": "missing"}, {"rule_key": "supplier_payment"},
    {"source_digest": "0" * 64}, {"policy_id": 999}, {"posting_date": "2026-08-30"}])
async def test_missing_wrong_direction_stale_source_or_policy_holds_without_writes(client, db, book, change):
    _, command = await setup(client, db, book)
    result = await client.post(f"/accounting/organizations/{book[0]}/bank-import/auto-preview", json={**command, **change})
    assert result.status_code == 422, result.text
    assert await db.scalar(select(func.count(Entry.id))) == 0
    assert await db.scalar(select(func.count(BankImportReceipt.entry_id))) == 0


@pytest.mark.parametrize("field,value", [("settlement_account", "60"), ("cash_activity", "financing"),
    ("bank_account", "62"), ("bank_dimensions", {"bank_account": "other"}), ("digest", "0" * 64)])
async def test_modified_resolved_command_cannot_post(client, db, book, field, value):
    _, command = await setup(client, db, book)
    path = f"/accounting/organizations/{book[0]}/bank-import"
    preview = await client.post(path + "/auto-preview", json=command)
    assert preview.status_code == 200, preview.text
    body = confirmation(preview.json(), command["rule_key"])
    body["command"][field] = value
    result = await client.post(path + "/auto-confirm", json=body)
    assert result.status_code == 409, result.text
    assert await db.scalar(select(func.count(Entry.id))) == 0


@pytest.mark.parametrize("account", ["51", "10", "90.1", "nonexistent"])
async def test_policy_rejects_cash_quantity_income_and_absent_accounts(client, db, book, account):
    if account == "10":
        db.add(Account(organization_id=book[0], code="10", title="Materials", category="asset",
            valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False, quantity_tracking=True, cash=False, normative_ref="synthetic"))
        await db.commit()
    response = await client.post(f"/accounting/organizations/{book[0]}/policies", json=policy({"bad":
        dict(title="Rejected", direction="receipt", settlement_account=account, cash_activity="operating")}))
    assert response.status_code in {409, 422}, response.text


async def test_unconfigured_bank_is_held_and_purchase_policy_shape_is_unchanged(client, book):
    response = await client.get(f"/accounting/organizations/{book[0]}/bank-import/auto-rules?on=2026-09-04")
    assert response.status_code == 409
    old = DocumentPostingPolicyInput.model_validate({"purchase": {}}).model_dump(exclude_none=True)
    assert "bank" not in old


async def test_wrong_organization_cannot_resolve_the_source(client, db, book):
    _, command = await setup(client, db, book)
    result = await client.post("/accounting/organizations/999/bank-import/auto-preview", json=command)
    assert result.status_code == 403
    assert await db.scalar(select(func.count(Entry.id))) == 0


@pytest.mark.parametrize("missing", ["registry", "direction"])
async def test_missing_registry_or_explicit_direction_is_held(client, db, book, missing):
    source, command = await setup(client, db, book)
    if missing == "registry":
        source.account_code = "unmapped"
    else:
        source.source_provider = None  # Legacy snapshot deliberately omits direction.
    await db.commit()
    command["source_digest"] = bank_import._digest(bank_import.source_snapshot(source))
    response = await client.post(f"/accounting/organizations/{book[0]}/bank-import/auto-preview", json=command)
    assert response.status_code in {409, 422}, response.text
    assert await db.scalar(select(func.count(Entry.id))) == 0
