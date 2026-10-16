from datetime import date
from uuid import uuid4

from sqlalchemy import select

from modules.accounting import models, service


async def _asset_accounts(db, org_id):
    for code, title, category in [
        ("01.1", "ОС оборудование", "asset"),
        ("02.1", "Амортизация оборудования", "asset"),
        ("26", "Общехозяйственные расходы", "expense"),
    ]:
        db.add(models.Account(organization_id=org_id, code=code, title=title, category=category,
                              valid_from=date(2026, 1, 1), required_dimensions=[],
                              currency_tracking=False, quantity_tracking=False, cash=False,
                              normative_ref="Synthetic fixed-asset fixture"))
    await db.commit()


async def _registered(client, db, book, posting):
    await _asset_accounts(db, book[0])
    source = await service.post(db, book[0], posting("fixed-asset-acquisition", "01.1", "60", "1200.00"), "tester")
    line = await db.scalar(select(models.Line).where(models.Line.entry_id == source.id, models.Line.side == "debit"))
    command = {
        "request_key": str(uuid4()), "asset_key": "asset:equipment:001", "source_entry_id": source.id,
        "source_line_id": line.id, "expected_source_digest": source.digest, "name": "Станок",
        "inventory_number": "ОС-001", "acquisition_date": "2026-09-01", "commissioning_date": "2026-09-01",
        "depreciation_start": "2026-09-01", "cost": "1200.00", "residual_value": "0.00",
        "useful_life_months": 12, "depreciation_method": "straight_line", "asset_account": "01.1",
        "accumulated_account": "02.1", "expense_account": "26", "dimensions": {"department": "ADMIN"},
        "evidence": "Акт приёма-передачи и инвентарная карточка проверены бухгалтером",
    }
    preview = await client.post(f"/accounting/organizations/{book[0]}/fixed-assets/preview", json=command)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()
    assert prepared["status"] == "reviewed_fixed_asset" and prepared["register_available"] is True
    confirm = await client.post(f"/accounting/organizations/{book[0]}/fixed-assets/confirm",
                                headers={"X-Expected-Principal": "tester"},
                                json={**command, "digest": prepared["digest"]})
    assert confirm.status_code == 201, confirm.text
    return command, prepared, confirm.json()


async def test_fixed_asset_register_binds_exact_acquisition_line(client, db, book, posting):
    command, prepared, result = await _registered(client, db, book, posting)
    assert result["asset_key"] == command["asset_key"]
    assert result["cost"] == "1200.00"
    replay = await client.post(f"/accounting/organizations/{book[0]}/fixed-assets/confirm",
                               headers={"X-Expected-Principal": "tester"},
                               json={**command, "digest": prepared["digest"]})
    assert replay.status_code == 201 and replay.json()["id"] == result["id"]
    listing = await client.get(f"/accounting/organizations/{book[0]}/fixed-assets")
    assert listing.status_code == 200 and listing.json()["rows"][0]["inventory_number"] == "ОС-001"


async def test_fixed_asset_depreciation_is_previewed_and_posted_once(client, db, book, posting):
    _, _, asset = await _registered(client, db, book, posting)
    body = {
        "request_key": str(uuid4()), "asset_id": asset["id"], "month": "2026-09",
        "expected_asset_digest": asset["digest"], "policy_id": book[1], "posting_date": "2026-09-30",
        "dimensions": {}, "evidence": "Расчёт амортизации за месяц сверил бухгалтер",
    }
    preview = await client.post(f"/accounting/organizations/{book[0]}/fixed-assets/depreciation-preview", json=body)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()
    assert prepared["posting_available"] is True and prepared["calculation"]["amount"] == "100.00"
    assert prepared["posting_document"]["operation"] == "fixed_asset_depreciation"
    confirm = await client.post(f"/accounting/organizations/{book[0]}/fixed-assets/depreciation-confirm",
                                headers={"X-Expected-Principal": "tester"},
                                json={**body, "digest": prepared["digest"]})
    assert confirm.status_code == 201, confirm.text
    assert confirm.json()["calculation"]["remaining_value"] == "1100.00"
    status = await client.get(f"/accounting/organizations/{book[0]}/fixed-assets/depreciation-status/{body['request_key']}")
    assert status.status_code == 200 and status.json()["entry_id"] == confirm.json()["entry_id"]
    replay = await client.post(f"/accounting/organizations/{book[0]}/fixed-assets/depreciation-confirm",
                               headers={"X-Expected-Principal": "tester"},
                               json={**body, "digest": prepared["digest"]})
    assert replay.status_code == 201 and replay.json()["entry_id"] == confirm.json()["entry_id"]


async def test_fixed_asset_depreciation_requires_sequential_months(client, db, book, posting):
    _, _, asset = await _registered(client, db, book, posting)
    body = {
        "request_key": str(uuid4()), "asset_id": asset["id"], "month": "2026-11",
        "expected_asset_digest": asset["digest"], "policy_id": book[1], "posting_date": "2026-11-30",
        "dimensions": {}, "evidence": "Расчёт пропущенного первого и второго месяца проверен",
    }
    response = await client.post(f"/accounting/organizations/{book[0]}/fixed-assets/depreciation-preview", json=body)
    assert response.status_code == 422 and "earlier depreciation" in response.json()["detail"]
