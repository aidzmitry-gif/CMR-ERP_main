import hashlib
from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from modules.accounting import models, service, shipment_commands, shipment_preview, shipment_profit
from tests.accounting.test_inventory_cost import move
from tests.accounting.test_shipment_preview import fixture


async def posted(db, book, posting):
    receipt, raw = await fixture(db, book, posting)
    receipt["digest"] = hashlib.sha256(shipment_preview.canonical(receipt["snapshot"]).encode()).hexdigest()
    raw["expected_act_digest"] = receipt["digest"]
    data = shipment_preview.ShipmentPlanInput(**raw)
    plan = await shipment_preview.prepare(db, book[0], receipt, data)
    saved = await shipment_commands.confirm(db, book[0], receipt, data, plan["basis_digest"], "tester")
    await db.commit()
    return saved


async def test_immutable_partial_shipment_cost_not_repriced_by_later_purchases(db, book, posting):
    saved = await posted(db, book, posting)
    result = await shipment_profit.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert (row["revenue_net_byn"], row["vat_byn"], row["cogs_byn"], row["gross_profit_byn"], row["margin_percent"]) == (
        "40.00", "8.00", "10.00", "30.00", "75.00")
    assert row["entry_id"] == saved.anchor_entry_id
    assert result["includes_later_adjustments"] is False
    await move(db, book, posting, "later-stock-price", "3", "999.00")
    assert await shipment_profit.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30)) == result
    assert (await shipment_profit.report(db, book[0], date(2026, 9, 2), date(2026, 9, 30)))["rows"] == []
    assert (await shipment_profit.report(db, 999, date(2026, 9, 1), date(2026, 9, 30)))["rows"] == []
    assert (await shipment_profit.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30), offset=1))["rows"] == []


async def test_report_refuses_corrupted_postings_and_snapshot(db, book, posting):
    saved = await posted(db, book, posting)
    changed = deepcopy(saved.snapshot)
    changed["act"]["snapshot"]["document_id"] += 1
    with pytest.raises(service.AccountingError):
        shipment_profit.summarize(SimpleNamespace(snapshot=changed, organization_id=book[0], act_digest=saved.act_digest))
    await db.execute(text("UPDATE line SET amount=amount+0.01 WHERE entry_id=:id"), {"id": saved.anchor_entry_id})
    await db.commit()
    with pytest.raises(service.AccountingError, match="проверить"):
        await shipment_profit.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))


async def test_report_http_contract_auth_and_period(client, db, book, posting):
    await posted(db, book, posting)
    url = f"/accounting/organizations/{book[0]}/reports/shipment-profit"
    response = await client.get(url, params={"start": "2026-09-01", "end": "2026-09-30"})
    assert response.status_code == 200, response.text
    assert response.json()["page_subtotal"]["gross_profit_byn"] == "30.00"
    assert response.headers["cache-control"] == "private, no-store"
    assert (await client.get(url, params={"start": "2026-09-02", "end": "2026-09-01"})).status_code == 409
    assert (await client.get(url, params={"start": "2026-09-01", "end": "2026-09-30", "offset": -1})).status_code == 422
    assert (await client.get(url.replace(str(book[0]), "999"), params={"start": "2026-09-01", "end": "2026-09-30"})).status_code in (403, 404)


async def test_two_shipments_of_same_invoice_remain_separate_and_margin_is_weighted(db, book, posting):
    first = await posted(db, book, posting)
    await move(db, book, posting, "next-batch", "3", "30.00", lot="lot2")
    act = deepcopy(first.snapshot["act"])
    act["source_key"] = "b5b089ab-0000-4000-8000-000000000002"
    act["snapshot"]["operation_date"] = "2026-09-02"
    act["digest"] = hashlib.sha256(shipment_preview.canonical(act["snapshot"]).encode()).hexdigest()
    command = deepcopy(first.command)
    command.update(expected_act_digest=act["digest"], posting_date="2026-09-02")
    for allocation in command["allocations"]:
        allocation["lot"] = "lot2"
    for line in command["commercial_lines"]:
        line["net_amount"] = "5.00"
    db.add(models.SourceControl(organization_id=book[0], source=f"wms:physical-shipment:{book[0]}:{act['source_key']}",
                               version=1, month="2026-09"))
    await db.commit()
    data = shipment_preview.ShipmentPlanInput(**command)
    plan = await shipment_preview.prepare(db, book[0], act, data)
    await shipment_commands.confirm(db, book[0], act, data, plan["basis_digest"], "tester")
    await db.commit()
    result = await shipment_profit.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert len(result["rows"]) == 2
    assert {row["document_id"] for row in result["rows"]} == {27}
    assert result["page_subtotal"] == {"revenue_net_byn": "50.00", "cogs_byn": "40.00",
                                      "gross_profit_byn": "10.00", "margin_percent": "20.00"}
    page = await shipment_profit.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30), limit=1)
    assert page["has_more"] is True
    assert page["page_subtotal"]["gross_profit_byn"] == "-20.00"
