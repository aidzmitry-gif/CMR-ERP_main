"""HTTP regressions for fixed-asset evidence, access and depreciation boundaries."""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from modules.accounting import models, service
from tests.accounting.test_fixed_assets import _asset_accounts, _registered


@pytest.fixture
async def asset_basis(db, book, posting):
    await _asset_accounts(db, book[0])
    entry = await service.post(
        db, book[0], posting("guard-acquisition", "01.1", "60", "1200.00"), "tester",
    )
    line = await db.scalar(select(models.Line).where(
        models.Line.entry_id == entry.id, models.Line.side == "debit",
    ))
    await db.commit()
    return {
        "request_key": str(uuid4()), "asset_key": "synthetic:asset:guard",
        "source_entry_id": entry.id, "source_line_id": line.id,
        "expected_source_digest": entry.digest, "name": "Synthetic equipment",
        "inventory_number": "SYNTHETIC-001", "acquisition_date": "2026-09-01",
        "commissioning_date": "2026-09-01", "depreciation_start": "2026-09-01",
        "cost": "1200.00", "residual_value": "0.00", "useful_life_months": 12,
        "depreciation_method": "straight_line", "asset_account": "01.1",
        "accumulated_account": "02.1", "expense_account": "26",
        "dimensions": {"department": "ADMIN"},
        "evidence": "Synthetic acquisition evidence reviewed by the accountant",
    }


async def _counts(db):
    return tuple([await db.scalar(select(func.count()).select_from(table)) for table in (
        models.Entry, models.Line, models.FixedAssetRegisterEntry,
        models.FixedAssetDepreciationReceipt,
    )])


@pytest.mark.parametrize("changes, message", [
    ({"acquisition_date": "2026-09-02"}, "Commissioning cannot precede acquisition"),
    ({"depreciation_start": "2026-08-01"}, "Depreciation cannot start before commissioning"),
    ({"residual_value": "1200.01"}, "Residual value cannot exceed cost"),
    ({"accumulated_account": "01.1"}, "Fixed-asset accounts must be distinct"),
    ({"expense_account": "01.1"}, "Fixed-asset accounts must be distinct"),
    ({"expense_account": "02.1"}, "Accumulated and expense accounts must be distinct"),
])
async def test_register_rejects_inconsistent_dates_values_and_accounts(
    client, db, book, asset_basis, changes, message,
):
    before = await _counts(db)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/fixed-assets/preview",
        json={**asset_basis, **changes},
    )
    assert response.status_code == 422 and message in response.text
    assert await _counts(db) == before


@pytest.mark.parametrize("changes, message", [
    ({"source_entry_id": 999999}, "source was not found in this organization"),
    ({"source_line_id": 999999}, "source was not found in this organization"),
    ({"expected_source_digest": "0" * 64}, "posting changed; read it again"),
    ({"cost": "1199.99"}, "exact cost"),
    ({"acquisition_date": "2026-08-01", "commissioning_date": "2026-08-31"},
     "Commissioning cannot precede the acquisition posting"),
    ({"accumulated_account": "60"}, "must belong to account 02"),
    ({"accumulated_account": "02.999"}, "not effective for this organization"),
    ({"depreciation_method": "production_units"}, "must match the acquisition policy"),
])
async def test_register_requires_exact_reviewed_source_and_applicable_accounts(
    client, db, book, asset_basis, changes, message,
):
    before = await _counts(db)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/fixed-assets/preview",
        json={**asset_basis, **changes},
    )
    assert response.status_code == 422 and message in response.json()["detail"]
    assert await _counts(db) == before


@pytest.mark.parametrize("field, value, message", [
    ("cash", True, "must be noncash BYN without quantity tracking"),
    ("currency_tracking", True, "must be noncash BYN without quantity tracking"),
    ("quantity_tracking", True, "must be noncash BYN without quantity tracking"),
    ("category", "income", "invalid category"),
])
async def test_register_rechecks_live_account_settings(client, db, book, asset_basis, field, value, message):
    account = await db.scalar(select(models.Account).where(
        models.Account.organization_id == book[0], models.Account.code == "01.1",
    ))
    # Account settings are immutable history: append the effective version.
    db.add(models.Account(**{
        column.key: getattr(account, column.key)
        for column in models.Account.__table__.columns if column.key != "id"
    } | {"valid_from": date(2026, 9, 1), field: value}))
    await db.commit()
    before = await _counts(db)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/fixed-assets/preview", json=asset_basis,
    )
    assert response.status_code == 422 and message in response.json()["detail"]
    assert await _counts(db) == before


@pytest.mark.parametrize("problem, message", [
    ("foreign_currency", "must be recorded in BYN"),
    ("wrong_asset_account", "must belong to account 01"),
    ("closed_period", "Reopen the acquisition period"),
    ("missing_policy", "no policy belonging to this organization"),
])
async def test_register_refuses_ineligible_acquisition_state(client, db, book, asset_basis, problem, message):
    # Insert a separate synthetic untrusted source to exercise admission.
    # Never rewrite the immutable acquisition or disable its ORM/SQL guards.
    entry = await db.get(models.Entry, asset_basis["source_entry_id"])
    line = await db.get(models.Line, asset_basis["source_line_id"])
    if problem == "closed_period":
        period = await db.scalar(select(models.Period).where(
            models.Period.organization_id == book[0], models.Period.month == "2026-09",
        ))
        period.closed = True
    else:
        source = models.Entry(**{
            column.key: getattr(entry, column.key)
            for column in models.Entry.__table__.columns if column.key != "id"
        } | {"source": f"synthetic:untrusted:{problem}",
             "policy_id": 999999 if problem == "missing_policy" else entry.policy_id})
        db.add(source)
        await db.flush()
        source_line = models.Line(**{
            column.key: getattr(line, column.key)
            for column in models.Line.__table__.columns if column.key != "id"
        } | {"entry_id": source.id,
             "currency": "USD" if problem == "foreign_currency" else line.currency,
             "account_code": "41" if problem == "wrong_asset_account" else line.account_code})
        db.add(source_line)
        await db.flush()
        asset_basis.update(source_entry_id=source.id, source_line_id=source_line.id)
        if problem == "wrong_asset_account":
            asset_basis["asset_account"] = "41"
    await db.commit()
    before = await _counts(db)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/fixed-assets/preview", json=asset_basis,
    )
    assert response.status_code == 422 and message in response.json()["detail"]
    assert await _counts(db) == before


@pytest.mark.parametrize("problem, message", [
    ("request_reuse", "request key was reused with different content"),
    ("asset_reuse", "key is already registered with different content"),
    ("stale_preview", "package changed; review it again"),
])
async def test_register_confirmation_cannot_reuse_keys_or_a_stale_digest(
    client, db, book, posting, problem, message,
):
    command, prepared, _ = await _registered(client, db, book, posting)
    body = {**command, "digest": prepared["digest"]}
    if problem == "request_reuse":
        body["digest"] = "0" * 64
    elif problem == "asset_reuse":
        body.update(request_key=str(uuid4()), digest="0" * 64)
    else:
        body.update(request_key=str(uuid4()), asset_key="synthetic:second-asset")
    before = await _counts(db)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/fixed-assets/confirm", json=body,
        headers={"X-Expected-Principal": "tester"},
    )
    assert response.status_code == 409 and message in response.json()["detail"]
    assert await _counts(db) == before


def _depreciation(book, asset, **changes):
    return {
        "request_key": str(uuid4()), "asset_id": asset["id"], "month": "2026-09",
        "expected_asset_digest": asset["digest"], "policy_id": book[1],
        "posting_date": "2026-09-30", "dimensions": {},
        "evidence": "Synthetic reviewed monthly depreciation calculation", **changes,
    }


@pytest.mark.parametrize("changes, message", [
    ({"asset_id": 999999}, "not found in this organization"),
    ({"expected_asset_digest": "0" * 64}, "register row changed"),
    ({"month": "2026-08", "posting_date": "2026-08-31"}, "precedes the explicit depreciation start"),
    ({"policy_id": 999999}, "Select an applicable policy"),
    ({"posting_date": "2026-10-01"}, "must belong to the selected month"),
])
async def test_depreciation_requires_current_asset_month_and_policy(client, db, book, posting, changes, message):
    _, _, asset = await _registered(client, db, book, posting)
    before = await _counts(db)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/fixed-assets/depreciation-preview",
        json=_depreciation(book, asset, **changes),
    )
    assert response.status_code == 422 and message in response.text
    assert await _counts(db) == before


@pytest.mark.parametrize("kind", ["register", "depreciation"])
@pytest.mark.parametrize("denial", ["principal_changed", "reader"])
async def test_fixed_asset_write_requires_same_principal_and_accounting_role(
    client, db, book, posting, kind, denial,
):
    command, prepared, asset = await _registered(client, db, book, posting)
    if kind == "register":
        path, body = "confirm", {**command, "digest": prepared["digest"]}
    else:
        path, body = "depreciation-confirm", {**_depreciation(book, asset), "digest": "0" * 64}
    if denial == "reader":
        grant = await db.scalar(select(models.AccessGrant).where(
            models.AccessGrant.organization_id == book[0], models.AccessGrant.subject == "tester",
        ))
        grant.role = "reader"
        await db.commit()
    before = await _counts(db)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/fixed-assets/{path}", json=body,
        headers={"X-Expected-Principal": "another-user" if denial == "principal_changed" else "tester"},
    )
    assert response.status_code == (409 if denial == "principal_changed" else 403)
    assert await _counts(db) == before


@pytest.mark.parametrize("path", ["999999", f"depreciation-status/{uuid4()}"])
async def test_missing_asset_or_receipt_returns_not_found(client, book, path):
    response = await client.get(f"/accounting/organizations/{book[0]}/fixed-assets/{path}")
    assert response.status_code == 404


@pytest.mark.parametrize("month", ["2026-13", "not-a-month"])
async def test_depreciation_listing_rejects_invalid_month(client, book, month):
    response = await client.get(
        f"/accounting/organizations/{book[0]}/fixed-assets/depreciation", params={"month": month},
    )
    assert response.status_code == 422 and response.json()["detail"] == "Month must be YYYY-MM"


async def test_one_month_life_replays_and_stops_at_residual_value(client, db, book, asset_basis):
    asset_basis.update(useful_life_months=1, residual_value="200.00")
    base = f"/accounting/organizations/{book[0]}/fixed-assets"
    preview = await client.post(f"{base}/preview", json=asset_basis)
    assert preview.status_code == 200
    register = await client.post(f"{base}/confirm", headers={"X-Expected-Principal": "tester"},
                                 json={**asset_basis, "digest": preview.json()["digest"]})
    assert register.status_code == 201
    asset = register.json()
    command = _depreciation(book, asset)
    preview = await client.post(f"{base}/depreciation-preview", json=command)
    assert preview.status_code == 200 and preview.json()["calculation"]["amount"] == "1000.00"
    posted = await client.post(f"{base}/depreciation-confirm", headers={"X-Expected-Principal": "tester"},
                               json={**command, "digest": preview.json()["digest"]})
    assert posted.status_code == 201
    before = await _counts(db)
    for key in (command["request_key"], str(uuid4())):
        replay = await client.post(f"{base}/depreciation-preview", json={**command, "request_key": key})
        assert replay.status_code == 200 and replay.json()["status"] == "already_posted"
        assert replay.json()["entry_id"] == posted.json()["entry_id"]
    exhausted = _depreciation(book, asset, month="2026-10", posting_date="2026-10-31")
    preview = await client.post(f"{base}/depreciation-preview", json=exhausted)
    assert preview.status_code == 200 and preview.json()["status"] == "fully_depreciated"
    assert preview.json()["posting_available"] is False
    denied = await client.post(f"{base}/depreciation-confirm", headers={"X-Expected-Principal": "tester"},
                               json={**exhausted, "digest": "0" * 64})
    assert denied.status_code == 409 and "no postable amount" in denied.json()["detail"]
    rows = await client.get(f"{base}/depreciation", params={"month": "2026-09"})
    assert rows.status_code == 200 and len(rows.json()["rows"]) == 1
    assert rows.headers["Cache-Control"] == "private, no-store"
    assert await _counts(db) == before
