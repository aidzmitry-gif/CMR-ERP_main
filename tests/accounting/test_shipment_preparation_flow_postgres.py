"""Public preparation endpoints with real WMS facts and PostgreSQL persistence."""
# ruff: noqa: F811
from uuid import uuid4

from sqlalchemy import func, select, update

from modules.accounting.models import AccessGrant, Entry, ShipmentAccountingReceipt, SourceControl
from modules.wms.models import StockMovement
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.accounting.test_shipment_receipt_postgres import prepare_accounting
from tests.integration.test_invoice_physical_shipments_postgres import physical_pg  # noqa: F401


async def test_source_lot_draft_reload_and_preview_preserve_pending_act(physical_pg):
    api = physical_pg[0]
    factory, org, act, data = await prepare_accounting(physical_pg)
    root = f"/accounting/organizations/{org}"
    physical = f"/wms/organizations/{org}/physical-shipments/by-key/{act['source_key']}"
    source = f"wms:physical-shipment:{org}:{act['source_key']}"
    async with factory() as session:
        entries_before = await session.scalar(select(func.count()).select_from(Entry))
        stock_before = await session.scalar(select(func.count()).select_from(StockMovement))

    async with factory() as session:
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == org).values(role="accountant"))
        await session.commit()
    api.headers["X-User-Roles"] = "finance"
    assert (await api.get(physical)).status_code == 403
    source_url = root + f"/shipments/{act['source_key']}/source"
    fetched = await api.get(source_url)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == act
    document = await api.get(root + f"/shipments/{act['source_key']}/document")
    assert document.status_code == 200 and "Не является ТН или ТТН" in document.text
    assert "default-src 'none'" in document.headers["content-security-policy"]
    assert (await api.get(source_url.replace(f"/organizations/{org}/", "/organizations/999/"))).status_code == 403
    line = fetched.json()["snapshot"]["lines"][0]
    lots = await api.get(root + "/inventory/lots", params={"policy_id": data.policy_id,
        "posting_date": data.posting_date.isoformat(), "account": "41.2",
        "warehouse": line["warehouse"], "sku": line["sku_code"]})
    assert lots.status_code == 200, lots.text
    assert lots.json()["lots"] == [{"lot": "L", "book_quantity": "3.000000",
        "book_value_byn": "10.00", "selectable": True, "reason": None}]

    command = data.model_dump(mode="json")
    form_fields = ["document_date", "explanation", "recognition_basis", "unit_basis", "cost_allocation", "vat_rounding"]
    payload = {"act_digest": fetched.json()["digest"], "posting_date": command["posting_date"],
        "policy_id": command["policy_id"], "form": {key: command[key] for key in form_fields},
        "allocations": command["allocations"], "terms": command["commercial_lines"]}
    draft_url = root + f"/shipments/{act['source_key']}/draft"
    save = {"request_key": str(uuid4()), "expected_revision": 0, "payload": payload}
    first = await api.post(draft_url, json=save)
    assert first.status_code == 200, first.text
    assert (await api.post(draft_url, json=save)).json() == first.json()
    # Each API request receives a new DB session; this is a durable reload.
    restored = (await api.get(draft_url)).json()["draft"]["payload"]
    assert restored == payload
    prepared = {**restored["form"], "expected_act_digest": fetched.json()["digest"],
        "policy_id": restored["policy_id"], "posting_date": restored["posting_date"],
        "recognition": "sale_on_shipment", "allocations": restored["allocations"],
        "commercial_lines": restored["terms"]}
    preview_url = root + f"/shipments/{act['source_key']}/preview"
    preview = await api.post(preview_url, json=prepared)
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert result["source"] == source and result["costs"][0]["issue_cost_byn"] == "3.33"
    assert (result["net_byn"], result["vat_byn"], result["gross_byn"]) == ("20.00", "4.00", "24.00")
    assert result["posted"] is False and result["confirmation_available"] is True
    assert result["statutory_certified"] is False
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry)) == entries_before
        assert await session.scalar(select(func.count()).select_from(StockMovement)) == stock_before
        assert await session.scalar(select(func.count()).select_from(ShipmentAccountingReceipt)) == 0
        control = await session.scalar(select(SourceControl).where(SourceControl.source == source))
        assert control is not None and control.entry_id is None

    async with factory() as session:
        await session.execute(update(AccessGrant).where(AccessGrant.organization_id == org).values(role="reader"))
        await session.commit()
    assert (await api.get(source_url)).status_code == 200
    assert (await api.post(preview_url, json=prepared)).status_code == 403
