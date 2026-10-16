from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from core.domain.models import Counterparty, Sku
from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Entry
from modules.procurement.receipt_documents import ReceiptRevision

pytestmark = pytest.mark.usefixtures("receipt_catalog_sku")


def document():
    return {"currency": "BYN", "invoice_reference": "INV1", "document_date": "2026-09-01",
            "operation_date": "2026-09-02", "supplier": "supplier1", "supplier_id": 1,
            "supplier_unp": "190000001", "contract": "contract1",
            "contract_basis": "Synthetic purchase without a registered contract",
            "warehouse": "warehouse1", "warehouse_id": 1,
            "warehouse_title": "Synthetic warehouse", "explanation": "Synthetic primary invoice",
            "items": [{"sku_id": 1, "sku_title": "Synthetic receipt item", "sku": "sku1", "unit": "шт",
                       "lot": "lot1", "quantity": "2.000001",
                       "net_amount": "100.01", "vat_rate": "20", "vat_amount": "20.00",
                       "vat_basis": "Synthetic invoice fact"}]}


async def ensure_receipt_catalog_sku(session, *, unit="шт"):
    connection = await session.connection()

    def create_catalog(sync):
        Sku.metadata.tables["ref_nomenclature_category"].create(sync, checkfirst=True)
        Sku.__table__.create(sync, checkfirst=True)

    await connection.run_sync(create_catalog)
    sku = await session.get(Sku, 1)
    if sku is None:
        session.add(Sku(id=1, code="sku1", title="Synthetic receipt item", unit=unit, is_active=True))
    else:
        sku.unit = unit
    await session.flush()


async def test_supplier_contract_selection_is_company_supplier_and_date_scoped(client, db, book):
    from modules.accounting.models import Organization
    from modules.procurement.models import Supplier
    from modules.procurement.supplier_contracts import SupplierContract

    path = f"/procurement/organizations/{book[0]}/supplier-contracts"
    command = {"supplier_id": 1, "number": "SC-1", "title": "Synthetic supply agreement",
               "signed_on": "2026-01-01", "expires_on": "2026-12-31",
               "evidence": "Synthetic signed original checked by purchaser"}
    created = await client.post(path, json=command)
    assert created.status_code == 201, created.text
    contract_id = created.json()["id"]
    assert (await client.post(path, json=command)).json()["id"] == contract_id
    assert (await client.post(path, json={**command, "title": "Other facts"})).status_code == 409
    options = await client.get(path, params={"supplier_id": 1})
    assert options.status_code == 200, options.text
    assert [(item["id"], item["number"]) for item in options.json()["items"]] == [(contract_id, "SC-1")]
    assert (await client.get(f"/procurement/organizations/{book[0] + 999}/supplier-contracts",
                             params={"supplier_id": 1})).status_code == 403

    facts = document()
    facts.pop("contract_basis")
    facts.update(contract="SC-1", contract_id=contract_id)
    receipt_path = f"/procurement/organizations/{book[0]}/receipt-documents"
    accepted = await client.post(receipt_path, json={"key": "contract-linked", "document": facts})
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["revisions"][0]["document"]["contract_id"] == contract_id
    for key, changes in (
        ("contract-number-mismatch", {"contract": "SC-OTHER"}),
        ("contract-expired", {"document_date": "2027-01-01"}),
        ("contract-unregistered", {"contract_id": None}),
    ):
        response = await client.post(receipt_path, json={"key": key, "document": {**facts, **changes}})
        assert response.status_code in {409, 422}, response.text

    other = Organization(name="Other company", unp="999999994")
    db.add(other)
    await db.flush()
    foreign = SupplierContract(organization_id=other.id, supplier_id=1, number="FOREIGN",
                               title="Foreign company agreement", signed_on=date(2026, 1, 1),
                               evidence="Synthetic unrelated agreement", created_by="other")
    db.add(foreign)
    await db.commit()
    response = await client.post(receipt_path, json={"key": "foreign-contract", "document": {
        **facts, "contract": "FOREIGN", "contract_id": foreign.id,
    }})
    assert response.status_code == 409, response.text
    db.add(Counterparty(id=2, name="second supplier", unp="190000002"))
    db.add(Supplier(id=2, counterparty_id=2, name="second supplier", unp="190000002", status="active"))
    await db.flush()
    wrong_supplier = SupplierContract(organization_id=book[0], supplier_id=2, number="SUPPLIER-2",
                                      title="Second supplier agreement", signed_on=date(2026, 1, 1),
                                      evidence="Synthetic other supplier agreement", created_by="other")
    db.add(wrong_supplier)
    await db.commit()
    response = await client.post(receipt_path, json={"key": "other-supplier-contract", "document": {
        **facts, "contract": "SUPPLIER-2", "contract_id": wrong_supplier.id,
    }})
    assert response.status_code == 409, response.text

    revoke_path = path + f"/{contract_id}/revoke"
    revoke = {"key": str(uuid4()), "reason": "The signed original was withdrawn"}
    first = await client.post(revoke_path, json=revoke)
    assert first.status_code == 200, first.text
    assert first.json()["is_active"] is False
    assert first.json()["deactivated_by"] == "tester"
    assert first.json()["deactivation_reason"] == revoke["reason"]
    assert first.json()["deactivated_at"]
    assert (await client.post(revoke_path, json=revoke)).json()["deactivation_key"] == revoke["key"]
    assert (await client.post(revoke_path, json={**revoke, "key": str(uuid4())})).status_code == 409
    assert (await client.get(path, params={"supplier_id": 1})).json()["items"] == []
    history = await client.get(path, params={"supplier_id": 1, "status": "revoked"})
    assert history.status_code == 200, history.text
    assert history.json()["status"] == "revoked"
    assert history.json()["truncated"] is False
    assert [item["id"] for item in history.json()["items"]] == [contract_id]
    assert history.json()["items"][0]["deactivation_reason"] == revoke["reason"]
    assert history.json()["items"][0]["deactivated_by"] == "tester"
    assert (await client.get(path, params={"supplier_id": 2, "status": "revoked"})).json()["items"] == []
    assert (await client.get(path, params={"supplier_id": 1, "status": "all"})).status_code == 422
    assert (await client.get(f"/procurement/organizations/{book[0] + 999}/supplier-contracts",
                             params={"supplier_id": 1, "status": "revoked"})).status_code == 403
    assert (await client.post(receipt_path, json={"key": "revoked-contract", "document": facts})).status_code == 409
    replacement = await client.post(path, json={**command, "evidence": "Corrected signed original"})
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["id"] != contract_id
    assert [item["id"] for item in (await client.get(path, params={"supplier_id": 1})).json()["items"]] == [replacement.json()["id"]]
    assert [item["id"] for item in (await client.get(path, params={"supplier_id": 1, "status": "revoked"})).json()["items"]] == [contract_id]
    assert accepted.json()["revisions"][0]["document"]["contract_id"] == contract_id


async def test_revoked_supplier_contract_history_pages_without_skipping_equal_timestamps(client, db, book):
    from modules.procurement.supplier_contracts import SupplierContract

    path = f"/procurement/organizations/{book[0]}/supplier-contracts"
    timestamp = datetime(2026, 9, 26, 10, tzinfo=timezone.utc)
    rows = [SupplierContract(
        organization_id=book[0], supplier_id=1, number=f"OLD-{i}", title="Synthetic historical agreement",
        signed_on=date(2025, 1, 1), evidence="Synthetic signed original", created_by="tester",
        is_active=False, deactivated_by="tester", deactivated_at=timestamp if i else timestamp - timedelta(days=1),
        deactivation_reason="Synthetic replacement", deactivation_key=str(uuid4()),
    ) for i in range(102)]
    db.add_all(rows)
    await db.flush()
    expected = [row.id for row in rows[:0:-1]] + [rows[0].id]
    await db.commit()

    first = await client.get(path, params={"supplier_id": 1, "status": "revoked"})
    assert first.status_code == 200, first.text
    assert first.json()["truncated"] is True
    assert len(first.json()["items"]) == 100
    assert first.json()["next_before_at"] and first.json()["next_before_id"]
    second = await client.get(path, params={"supplier_id": 1, "status": "revoked",
                                            "before_at": first.json()["next_before_at"],
                                            "before_id": first.json()["next_before_id"]})
    assert second.status_code == 200, second.text
    assert second.json()["truncated"] is False
    assert second.json()["next_before_at"] is None
    assert [row["id"] for row in first.json()["items"] + second.json()["items"]] == expected
    assert (await client.get(path, params={"supplier_id": 1, "status": "revoked",
                                          "before_id": first.json()["next_before_id"]})).status_code == 422
    assert (await client.get(path, params={"supplier_id": 1, "status": "active",
                                          "before_at": first.json()["next_before_at"],
                                          "before_id": first.json()["next_before_id"]})).status_code == 422


async def test_receipt_sku_selection_freezes_snapshot_and_rejects_catalog_drift(client, db, book):
    path = f"/procurement/organizations/{book[0]}/receipt-documents"
    facts = document()
    old_text = {**facts, "items": [{k: v for k, v in facts["items"][0].items()
                                   if k not in {"sku_id", "sku_title"}}]}
    assert (await client.post(path, json={"key": "unbound-item", "document": old_text})).status_code == 422

    sku = await db.get(Sku, 1)
    sku.title = "Renamed catalogue item"
    await db.commit()
    assert (await client.post(path, json={"key": "stale-item", "document": facts})).status_code == 409
    sku.title = "Synthetic receipt item"
    await db.commit()
    created = await client.post(path, json={"key": "bound-item", "document": facts})
    assert created.status_code == 201, created.text
    assert created.json()["revisions"][0]["document"]["items"][0]["sku_id"] == 1

    sku.title = "Renamed catalogue item"
    await db.commit()
    replay = await client.post(path, json={"key": "bound-item", "document": facts})
    assert replay.status_code == 201 and replay.json()["id"] == created.json()["id"]
    assert replay.json()["revisions"][0]["document"]["items"][0]["sku_title"] == "Synthetic receipt item"
    assert (await client.put(f"{path}/{created.json()['id']}", json={
        "key": "stale-sku-edit", "expected_version": 1, "document": facts,
    })).status_code == 409


async def test_receipt_warehouse_selection_is_scoped_snapshotted_and_replayable(client, db, book):
    from modules.accounting.models import Organization
    from modules.wms.models import WarehouseDirectory

    org = book[0]
    options_path = f"/procurement/organizations/{org}/receipt-warehouse-options"
    options = await client.get(options_path, params={"q": "Synthetic"})
    assert options.status_code == 200, options.text
    assert options.json()["items"] == [{"id": 1, "name": "warehouse1",
                                        "title": "Synthetic warehouse", "is_active": True}]
    assert options.headers["cache-control"] == "private, no-store"

    path = f"/procurement/organizations/{org}/receipt-documents"
    facts = document()
    unbound = {key: value for key, value in facts.items()
               if key not in {"warehouse_id", "warehouse_title"}}
    missing = await client.post(path, json={"key": "warehouse-unbound", "document": unbound})
    assert missing.status_code == 422 and "warehouse" in missing.text.lower()

    stale = await client.post(path, json={"key": "warehouse-stale", "document": {
        **facts, "warehouse_title": "Old warehouse title",
    }})
    assert stale.status_code == 409, stale.text
    warehouse = await db.get(WarehouseDirectory, 1)
    warehouse.is_active = False
    await db.commit()
    inactive = await client.post(path, json={"key": "warehouse-inactive", "document": facts})
    assert inactive.status_code == 409, inactive.text
    warehouse.is_active = True

    other = Organization(name="Other warehouse company", unp="999999994")
    db.add(other)
    await db.flush()
    foreign = WarehouseDirectory(organization_id=other.id, name="warehouse1",
                                 title="Synthetic warehouse", is_active=True, created_by="other")
    db.add(foreign)
    await db.commit()
    wrong_company = await client.post(path, json={"key": "warehouse-foreign", "document": {
        **facts, "warehouse_id": foreign.id,
    }})
    assert wrong_company.status_code == 409, wrong_company.text

    created = await client.post(path, json={"key": "warehouse-bound", "document": facts})
    assert created.status_code == 201, created.text
    receipt_id = created.json()["id"]
    assert created.json()["revisions"][0]["document"]["warehouse_id"] == warehouse.id
    assert created.json()["revisions"][0]["document"]["warehouse_title"] == "Synthetic warehouse"

    warehouse.title = "Renamed warehouse"
    await db.commit()
    replay = await client.post(path, json={"key": "warehouse-bound", "document": facts})
    assert replay.status_code == 201 and replay.json()["id"] == receipt_id
    assert replay.json()["revisions"][0]["document"]["warehouse_title"] == "Synthetic warehouse"
    preview = await client.post(f"{path}/{receipt_id}/preview", json={
        "expected_version": 1, "posting_date": "2026-09-03", "policy_id": book[1],
        "settlement_account": "60", "vat_account": None, "inventory_accounts": ["41"],
    })
    assert preview.status_code == 409 and "Warehouse directory" in preview.text
    with pytest.raises(ValueError, match="Warehouse directory record changed"):
        await client.test_app.state.core.services.procurement_source.warehouse_receipt_source(
            db, org, receipt_id, 1,
        )
    stale_edit = await client.put(f"{path}/{receipt_id}", json={
        "key": "warehouse-stale-edit", "expected_version": 1,
        "document": {**facts, "explanation": "Changed with stale warehouse snapshot"},
    })
    assert stale_edit.status_code == 409, stale_edit.text
    rebound = await client.put(f"{path}/{receipt_id}", json={
        "key": "warehouse-rebind", "expected_version": 1,
        "document": {**facts, "warehouse_title": "Renamed warehouse",
                     "explanation": "Changed after explicit warehouse selection"},
    })
    assert rebound.status_code == 200, rebound.text
    assert rebound.json()["version"] == 2
    assert rebound.json()["revisions"][1]["document"]["warehouse_title"] == "Renamed warehouse"
    from modules.procurement.receipt_documents import ReceiptContent, classify_receipt_correction
    flags, classification = classify_receipt_correction(
        ReceiptContent.model_validate(facts),
        ReceiptContent.model_validate(rebound.json()["revisions"][1]["document"]),
    )
    assert flags["primary_document_change"] is True
    assert flags["physical_change"] is False
    assert "primary_document_change" in classification


@pytest.mark.parametrize("missing", [{"sku_id", "sku_title"}, {"sku_title"}])
async def test_old_text_sku_draft_needs_explicit_selection_before_posting_or_warehouse(client, db, book, missing):
    from modules.procurement.receipt_documents import ReceiptDocument

    facts = document()
    legacy = {**facts, "items": [{k: v for k, v in facts["items"][0].items()
                                  if k not in missing}]}
    row = ReceiptDocument(organization_id=book[0], source_key="legacy-text-sku",
                          current_version=1, status="draft", created_by="historical")
    db.add(row)
    await db.flush()
    receipt_id = row.id
    db.add(ReceiptRevision(receipt_id=receipt_id, version=1, document=legacy, actor="historical"))
    await db.commit()
    path = f"/procurement/organizations/{book[0]}/receipt-documents/{receipt_id}"
    replay = await client.post(path.rsplit("/", 1)[0], json={"key": "legacy-text-sku", "document": legacy})
    assert replay.status_code == 201 and replay.json()["id"] == receipt_id
    preview = await client.post(path + "/preview", json={
        "expected_version": 1, "posting_date": "2026-09-03", "policy_id": book[1],
        "settlement_account": "60", "vat_account": None, "inventory_accounts": ["41"],
    })
    assert preview.status_code == 409 and "SKU catalogue" in preview.text
    with pytest.raises(ValueError, match="SKU catalogue"):
        await client.test_app.state.core.services.procurement_source.warehouse_receipt_source(
            db, book[0], receipt_id, 1,
        )
    edited = await client.put(path, json={"key": "legacy-sku-upgrade", "expected_version": 1, "document": facts})
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2
    assert all(field not in edited.json()["revisions"][0]["document"]["items"][0] for field in missing)
    assert edited.json()["revisions"][1]["document"]["items"][0]["sku_id"] == 1


async def test_catalog_supplier_snapshot_stays_in_revision_and_rejects_drift(client, db, book):
    from modules.procurement.models import Supplier

    async with db.bind.begin() as connection:
        await connection.run_sync(lambda sync: Supplier.metadata.create_all(
            sync, tables=[Supplier.__table__]))
    party = Counterparty(name="Selected supplier", unp="190000003")
    db.add(party)
    await db.flush()
    supplier = Supplier(name="Selected supplier", unp="190000003", status="active", counterparty_id=party.id)
    db.add(supplier)
    await db.commit()
    data = {**document(), "supplier": supplier.name,
            "supplier_id": supplier.id, "supplier_unp": supplier.unp}
    path = f"/procurement/organizations/{book[0]}/receipt-documents"
    created = await client.post(path, json={"key": "catalog-supplier", "document": data})
    assert created.status_code == 201, created.text
    assert created.json()["revisions"][0]["document"]["supplier_id"] == supplier.id
    supplier.name = "Renamed supplier"
    await db.commit()
    replay = await client.post(path, json={"key": "catalog-supplier", "document": data})
    assert replay.status_code == 201 and replay.json()["id"] == created.json()["id"]
    assert replay.json()["revisions"][0]["document"]["supplier"] == "Selected supplier"
    stale = await client.post(path, json={"key": "new-source", "document": data})
    assert stale.status_code == 409
    edited = await client.put(f"{path}/{created.json()['id']}",
                              json={"key": "stale-supplier-edit", "expected_version": 1, "document": data})
    assert edited.status_code == 409
    supplier.name = "Selected supplier"
    party.name = "Changed MDM supplier"
    await db.commit()
    replay = await client.post(path, json={"key": "catalog-supplier", "document": data})
    assert replay.status_code == 201 and replay.json()["id"] == created.json()["id"]
    assert (await client.post(path, json={"key": "mdm-changed", "document": data})).status_code == 409
    preview = await client.post(f"{path}/{created.json()['id']}/preview", json={
        "expected_version": 1, "posting_date": "2026-09-03", "policy_id": book[1],
        "settlement_account": "60", "vat_account": None, "inventory_accounts": ["41"],
    })
    assert preview.status_code == 409
    assert len((await client.get(path)).json()) == 1


async def test_new_text_only_receipt_is_rejected_but_legacy_replay_and_upgrade_work(client, db, book):
    from modules.procurement.receipt_documents import ReceiptDocument

    path = f"/procurement/organizations/{book[0]}/receipt-documents"
    bound = document()
    legacy = {key: value for key, value in bound.items() if key not in {"supplier_id", "supplier_unp"}}
    rejected = await client.post(path, json={"key": "new-unbound", "document": legacy})
    assert rejected.status_code == 422
    assert await db.scalar(select(func.count()).select_from(ReceiptDocument)) == 0

    row = ReceiptDocument(organization_id=book[0], source_key="old-unbound",
                          current_version=1, status="draft", created_by="historical")
    db.add(row)
    await db.flush()
    receipt_id = row.id
    db.add(ReceiptRevision(receipt_id=receipt_id, version=1, document=legacy, actor="historical"))
    await db.commit()
    replay = await client.post(path, json={"key": "old-unbound", "document": legacy})
    assert replay.status_code == 201 and replay.json()["id"] == receipt_id
    assert "supplier_id" not in replay.json()["revisions"][0]["document"]
    assert (await client.put(f"{path}/{receipt_id}", json={
        "key": "legacy-unbound-edit", "expected_version": 1, "document": legacy,
    })).status_code == 422
    upgraded = await client.put(f"{path}/{receipt_id}", json={
        "key": "legacy-bound-edit", "expected_version": 1, "document": bound,
    })
    assert upgraded.status_code == 200, upgraded.text
    assert upgraded.json()["version"] == 2
    assert upgraded.json()["revisions"][0]["document"] == legacy
    assert upgraded.json()["revisions"][1]["document"]["supplier_id"] == 1


async def test_unbound_legacy_draft_cannot_be_posted_or_sent_to_warehouse(client, db, book):
    from modules.procurement.receipt_documents import ReceiptDocument, ReceiptPosting
    from modules.procurement.source_gateway import ProcurementSourceService

    old = {key: value for key, value in document().items() if key not in {"supplier_id", "supplier_unp"}}
    old["items"][0]["unit"] = "кг"
    old["items"][0]["quantity"] = "2.00"
    row = ReceiptDocument(organization_id=book[0], source_key="legacy-unbound",
                          current_version=1, status="draft", created_by="historical")
    db.add(row)
    await db.flush()
    receipt_id = row.id
    db.add(ReceiptRevision(receipt_id=receipt_id, version=1, document=old, actor="historical"))
    await db.commit()

    preview = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents/{receipt_id}/preview",
                                json={"expected_version": 1, "posting_date": "2026-09-03", "policy_id": book[1],
                                      "settlement_account": "60", "vat_account": None,
                                      "inventory_accounts": ["41"]})
    assert preview.status_code == 409 and "supplier" in preview.text.lower()
    with pytest.raises(ValueError, match="supplier"):
        await ProcurementSourceService().warehouse_receipt_source(db, book[0], receipt_id, 1)
    assert await db.get(ReceiptPosting, receipt_id) is None

    # A previously posted historical source is still readable for reconciliation.
    row.status = "posted"
    db.add(ReceiptPosting(receipt_id=receipt_id, version=1, entry_id=12345,
                          options={}, digest="a" * 64, actor="historical"))
    await db.commit()
    gateway = ProcurementSourceService()
    assert (await gateway.receipt_source(db, book[0], receipt_id))["document"] == old
    assert (await gateway.warehouse_receipt_source(db, book[0], receipt_id, 1))["document"] == old


async def test_order_line_without_order_rejected_and_legacy_payload_unchanged(client, book):
    from modules.procurement.receipt_documents import ReceiptContent
    data = document()
    assert "order_line_id" not in ReceiptContent.model_validate(data).model_dump(mode="json")["items"][0]
    data["items"][0]["order_line_id"] = 1
    response = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents",
                                json={"key": "line-without-order", "document": data})
    assert response.status_code == 422, response.text


async def test_receipt_preserves_exact_order_line_and_rejects_cross_order_or_sku(client, db, book):
    from modules.procurement.models import PurchaseOrder, PurchaseOrderLine
    from modules.procurement.ownership import PurchaseOwnership

    orders = [PurchaseOrder(number=f"line-test-{i}", supplier="supplier1") for i in range(2)]
    db.add_all(orders)
    await db.flush()
    lines = [PurchaseOrderLine(order_id=order.id, sku_code="sku1", qty=10) for order in orders]
    db.add_all(lines)
    for order in orders:
        db.add(PurchaseOwnership(organization_id=book[0], kind="order", source_id=order.id,
                                 snapshot={}, evidence="Synthetic ownership", actor="tester"))
    await db.flush()
    order_ids, line_ids = [row.id for row in orders], [row.id for row in lines]
    await db.commit()
    path = f"/procurement/organizations/{book[0]}/receipt-documents"
    for index, (line_id, sku) in enumerate(((line_ids[1], "sku1"), (line_ids[0], "wrong-sku"), (999999, "sku1"))):
        payload = document()
        payload["items"][0].update(order_id=order_ids[0], order_line_id=line_id, sku=sku)
        response = await client.post(path, json={"key": f"bad-order-line-{index}", "document": payload})
        assert response.status_code == 409, response.text
    payload = document()
    payload["items"][0].update(order_id=order_ids[0], order_line_id=line_ids[0])
    response = await client.post(path, json={"key": "exact-order-line", "document": payload})
    assert response.status_code == 201, response.text
    assert response.json()["revisions"][0]["document"]["items"][0]["order_line_id"] == line_ids[0]
    repeated = await client.post(path, json={"key": "exact-order-line", "document": payload})
    assert repeated.status_code == 201 and repeated.json()["id"] == response.json()["id"]


async def test_primary_draft_preserves_versions_and_never_posts(client, db, book):
    path = f"/procurement/organizations/{book[0]}/receipt-documents"
    data = {"key": "source1", "document": document()}
    first = await client.post(path, json=data)
    repeat = await client.post(path, json=data)
    assert first.status_code == repeat.status_code == 201
    assert first.json()["id"] == repeat.json()["id"]
    assert first.json()["status"] == "draft"
    changed = {**document(), "invoice_reference": "INV1 corrected"}
    second = await client.put(path + f"/{first.json()['id']}", json={"key": "edit-v2", "expected_version": 1, "document": changed})
    assert second.status_code == 200
    assert second.json()["version"] == 2
    revisions = second.json()["revisions"]
    assert [r["document"]["invoice_reference"] for r in revisions] == ["INV1", "INV1 corrected"]
    assert revisions[0]["document"]["items"][0]["quantity"] == "2.000001"
    assert all(r["actor"] == "tester" for r in revisions)
    replay = await client.put(path + f"/{first.json()['id']}", json={"key": "edit-v2", "expected_version": 1, "document": changed})
    assert replay.status_code == 200 and replay.json()["version"] == 2
    assert len(replay.json()["revisions"]) == 2
    assert replay.json()["revisions"][1]["request_key"] == "edit-v2"
    sku = await db.get(Sku, 1)
    sku.title = "Renamed after accepted edit"
    await db.commit()
    replay_after_catalog_change = await client.put(path + f"/{first.json()['id']}", json={
        "key": "edit-v2", "expected_version": 1, "document": changed,
    })
    assert replay_after_catalog_change.status_code == 200
    assert len(replay_after_catalog_change.json()["revisions"]) == 2
    assert (await client.put(path + f"/{first.json()['id']}", json={"key": "stale-edit", "expected_version": 1, "document": changed})).status_code == 409
    assert (await client.put(path + f"/{first.json()['id']}", json={"key": "edit-v2", "expected_version": 1, "document": document()})).status_code == 409
    assert (await client.post(path, json={**data, "document": changed})).status_code == 409
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0
    assert len((await client.get(path)).json()) == 1
    row = await db.scalar(select(ReceiptRevision).where(ReceiptRevision.version == 1))
    row.actor = "tampered"
    with pytest.raises(ValueError, match="immutable"):
        await db.flush()
    await db.rollback()


async def test_source_permission_does_not_grant_ledger_write(client, db, book):
    db.add(AccessGrant(organization_id=book[0], subject="buyer", role="reader"))
    await db.commit()
    # Module authority + book membership permit a procurement draft, not a posting.
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("buyer", ["procurement"])
    response = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents", json={"key": "buyer1", "document": document()})
    assert response.status_code == 201
    assert (await client.post(f"/accounting/organizations/{book[0]}/entries", json={})).status_code == 403
    listed = await client.get("/procurement/receipt-organizations")
    assert [row["id"] for row in listed.json()] == [book[0]]
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("buyer", ["warehouse"])
    assert (await client.get(f"/procurement/organizations/{book[0]}/receipt-documents")).status_code == 403
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("stranger", ["director"])
    assert (await client.get(f"/procurement/organizations/{book[0]}/receipt-documents")).status_code == 403
    assert (await client.get("/procurement/receipt-organizations")).json() == []


@pytest.mark.parametrize("patch", [{"currency": "USD"}, {"currency": None}, {"supplier": ""}])
async def test_draft_does_not_guess_currency_or_supplier(client, book, patch):
    response = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents", json={"key": "bad", "document": {**document(), **patch}})
    assert response.status_code == 422


async def test_primary_draft_commit_failure_is_not_http_success(client, db, book, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from modules.procurement.receipt_documents import ReceiptDocument

    async def fail():
        raise IntegrityError("synthetic commit failure", None, Exception("rollback test"))

    monkeypatch.setattr(db, "commit", fail)
    response = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents", json={"key": "failed", "document": document()})
    assert response.status_code == 409
    assert await db.scalar(select(func.count()).select_from(ReceiptDocument)) == 0

async def source_options(client, db, book, *, unit=None):
    from datetime import date

    from modules.accounting.models import Account
    await ensure_receipt_catalog_sku(db, unit=unit or "шт")
    db.add(Account(organization_id=book[0], code="41.2", title="Synthetic goods", category="asset", valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False, quantity_tracking=True, cash=False, normative_ref="synthetic"))
    await db.commit()
    data = document()
    data["items"][0].update(vat_rate="0", vat_amount="0.00")
    if unit is not None:
        data["items"][0]["unit"] = unit
    path = f"/procurement/organizations/{book[0]}/receipt-documents"
    created = await client.post(path, json={"key": "post-source", "document": data})
    assert created.status_code == 201
    return path + f"/{created.json()['id']}", {"expected_version": 1, "posting_date": "2026-09-03", "policy_id": book[1], "settlement_account": "60", "vat_account": None, "inventory_accounts": ["41.2"]}


async def test_source_posting_uses_facts_and_freezes_document(client, db, book):
    from modules.procurement.receipt_documents import ReceiptPosting
    from modules.procurement.source_gateway import ProcurementSourceService
    path, options = await source_options(client, db, book)
    revised = document()
    revised["invoice_reference"] = "INV1 revised"
    revised["items"][0].update(vat_rate="0", vat_amount="0.00")
    assert (await client.put(path, json={"key": "source-revision", "expected_version": 1, "document": revised})).status_code == 200
    options["expected_version"] = 2
    preview = await client.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    assert preview.json()["lines"][0]["amount"] == "100.01"
    assert preview.json()["lines"][0]["dimensions"]["counterparty_id"] == "1"
    client.test_app.state.core.services.procurement_source = ProcurementSourceService()
    accounting_preview = await client.post(
        f"/accounting/organizations/{book[0]}/receipts/{path.rsplit('/', 1)[1]}/preview",
        json=options)
    assert accounting_preview.status_code == 200, accounting_preview.text
    assert accounting_preview.json()["digest"] == preview.json()["digest"]
    confirmed = {**options, "digest": preview.json()["digest"]}
    first = await client.post(path + "/confirm", json=confirmed)
    party = await db.get(Counterparty, 1)
    party.name = "supplier1 renamed after posting"
    await db.commit()
    again = await client.post(path + "/confirm", json=confirmed)
    assert first.status_code == again.status_code == 201, first.text
    assert first.json()["entry_id"] == again.json()["entry_id"]
    assert (await db.get(Entry, first.json()["entry_id"])).rule_version == "purchase-byn-v2"
    posting = await db.get(ReceiptPosting, int(path.rsplit("/", 1)[1]))
    assert posting.options["supplier_counterparty_id"] == 1
    basis = await ProcurementSourceService().posted_receipt_basis(
        db, book[0], posting.receipt_id, 2)
    assert basis["entry_id"] == first.json()["entry_id"]
    assert await db.scalar(select(func.count()).select_from(Entry)) == 1
    assert await db.scalar(select(func.count()).select_from(ReceiptPosting)) == 1
    assert (await client.put(path, json={"key": "posted-edit", "expected_version": 1, "document": document()})).status_code == 409
    assert (await client.post(path + "/confirm", json={**confirmed, "posting_date": "2026-09-04"})).status_code == 409
    rows = (await client.get(path.rsplit("/", 1)[0])).json()
    assert rows[0]["status"] == "posted"
    assert rows[0]["posting"]["entry_id"] == first.json()["entry_id"]
    source_path = f"/procurement/organizations/{book[0]}/receipt-postings/{first.json()['entry_id']}"
    source = await client.get(source_path)
    assert source.status_code == 200
    assert source.json()["document"] == rows[0]["revisions"][1]["document"]
    assert source.json()["version"] == 2
    assert (await client.get(source_path.rsplit("/", 1)[0] + "/999999")).status_code == 404
    from modules.accounting.models import Organization
    other = Organization(name="Other", unp="999999995")
    db.add(other)
    await db.flush()
    db.add(AccessGrant(organization_id=other.id, subject="tester", role="chief"))
    await db.commit()
    assert (await client.get(f"/procurement/organizations/{other.id}/receipt-postings/{first.json()['entry_id']}")).status_code == 404
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("stranger", ["director"])
    assert (await client.get(source_path)).status_code == 403


async def test_posted_receipt_correction_draft_is_exact_idempotent_and_fail_closed(client, db, book):
    from modules.procurement.receipt_documents import ReceiptDocument, ReceiptPosting
    from modules.procurement.source_gateway import ProcurementSourceService

    path, options = await source_options(client, db, book)
    preview = await client.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    confirmed = await client.post(path + "/confirm", json={**options, "digest": preview.json()["digest"]})
    assert confirmed.status_code == 201, confirmed.text
    original_id = int(path.rsplit("/", 1)[1])
    correction_path = path + "/correction-drafts"
    command = {"key": str(uuid4()), "expected_version": 1,
               "expected_entry_id": confirmed.json()["entry_id"]}

    created = await client.post(correction_path, json=command)
    assert created.status_code == 201, created.text
    draft = created.json()
    assert draft["id"] != original_id
    assert draft["status"] == "draft" and draft["version"] == 1
    assert draft["correction_of"] == {"receipt_id": original_id, "version": 1,
                                      "entry_id": confirmed.json()["entry_id"]}
    assert draft["revisions"][0]["document"] == (await client.get(path.rsplit("/", 1)[0])).json()[0]["revisions"][0]["document"]
    replay = await client.post(correction_path, json=command)
    assert replay.status_code == 201 and replay.json() == draft
    assert (await client.post(correction_path, json={**command, "expected_entry_id": confirmed.json()["entry_id"] + 1})).status_code == 409
    assert (await client.post(correction_path, json={**command, "expected_version": 2})).status_code == 409
    assert (await client.post(correction_path, json={"key": str(uuid4()), "expected_version": 2,
                                                     "expected_entry_id": confirmed.json()["entry_id"]})).status_code == 409
    assert (await client.post(correction_path, json={"key": str(uuid4()), "expected_version": 1,
                                                     "expected_entry_id": confirmed.json()["entry_id"] + 1})).status_code == 409
    assert (await client.post(f"/procurement/organizations/{book[0] + 999}/receipt-documents/{original_id}/correction-drafts",
                              json=command)).status_code == 403
    second_source = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents", json={
        "key": "second-posted-source", "document": document(),
    })
    assert second_source.status_code == 201, second_source.text
    unposted = await client.post(
        f"/procurement/organizations/{book[0]}/receipt-documents/{second_source.json()['id']}/correction-drafts",
        json={"key": str(uuid4()), "expected_version": 1,
              "expected_entry_id": confirmed.json()["entry_id"]})
    assert unposted.status_code == 409
    collision = await client.post(
        f"/procurement/organizations/{book[0]}/receipt-documents/{second_source.json()['id']}/correction-drafts",
        json=command)
    assert collision.status_code == 409

    edited = await client.put(f"/procurement/organizations/{book[0]}/receipt-documents/{draft['id']}", json={
        "key": str(uuid4()), "expected_version": 1,
        "document": {**draft["revisions"][0]["document"], "explanation": "Explicit correction review note"},
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2 and edited.json()["correction_of"] == draft["correction_of"]
    assert (await client.post(correction_path, json=command)).json() == edited.json()

    preview_blocked = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents/{draft['id']}/preview",
                                        json={**options, "expected_version": 2})
    assert preview_blocked.status_code == 409 and "correction workflow" in preview_blocked.text
    confirm_blocked = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents/{draft['id']}/confirm",
                                        json={**options, "expected_version": 2, "digest": "a" * 64})
    assert confirm_blocked.status_code == 409 and "correction workflow" in confirm_blocked.text
    direct_entry = await client.post(f"/accounting/organizations/{book[0]}/entries", json={
        "source": f"procurement:receipt:{draft['id']}", "source_version": 1,
        "operation": "manual", "document_date": "2026-09-03", "operation_date": "2026-09-03",
        "posting_date": "2026-09-03", "policy_id": book[1], "rule_version": "manual-v1",
        "explanation": "Attempted direct posting of a correction draft", "opening": False,
        "lines": [
            {"account": "41.2", "side": "debit", "amount": "1.00", "quantity": "1.000000", "dimensions": {}},
            {"account": "60", "side": "credit", "amount": "1.00", "dimensions": {}},
        ],
    })
    assert direct_entry.status_code == 422 and "separately approved correction workflow" in direct_entry.text
    from modules.accounting import service
    await service.reject_correction_receipt_source(
        db, book[0], "procurement:receipt:" + "9" * 100,
    )

    listed = await client.get(f"/procurement/organizations/{book[0]}/receipt-documents")
    correction_row = next(row for row in listed.json() if row["id"] == draft["id"])
    assert correction_row["correction_of"] == draft["correction_of"]
    source = await ProcurementSourceService().receipt_source(db, book[0], draft["id"])
    assert source["correction_of"] == draft["correction_of"]
    with pytest.raises(ValueError, match="Correction drafts cannot be prepared"):
        await ProcurementSourceService().warehouse_receipt_source(db, book[0], draft["id"], 2)
    assert await db.scalar(select(func.count()).select_from(ReceiptDocument)) == 3
    assert await db.scalar(select(func.count()).select_from(ReceiptPosting)) == 1
    assert await db.scalar(select(func.count()).select_from(Entry)) == 1
    original = await db.get(ReceiptDocument, original_id)
    assert original.current_version == 1
    assert await db.get(ReceiptPosting, original_id) is not None


async def create_readiness_correction(client, db, book):
    path, options = await source_options(client, db, book)
    preview = await client.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    confirmed = await client.post(path + "/confirm", json={**options, "digest": preview.json()["digest"]})
    assert confirmed.status_code == 201, confirmed.text
    created = await client.post(path + "/correction-drafts", json={
        "key": str(uuid4()), "expected_version": 1, "expected_entry_id": confirmed.json()["entry_id"],
    })
    assert created.status_code == 201, created.text
    readiness_path = f"/procurement/organizations/{book[0]}/receipt-documents/{created.json()['id']}/correction-readiness"
    return readiness_path, created.json()


async def test_correction_readiness_is_read_only_and_classifies_unchanged_or_explanation_only(client, db, book):
    from modules.procurement.receipt_documents import ReceiptPosting

    readiness_path, draft = await create_readiness_correction(client, db, book)
    entry_count = await db.scalar(select(func.count()).select_from(Entry))
    posting_count = await db.scalar(select(func.count()).select_from(ReceiptPosting))

    unchanged = await client.get(readiness_path)
    assert unchanged.status_code == 200, unchanged.text
    result = unchanged.json()
    assert result["correction_of"] == draft["correction_of"]
    assert result["current_version"] == 1
    assert result["classification"] == ["no_difference"]
    assert result["no_difference"] is True
    assert all(result[key] is False for key in (
        "physical_change", "inventory_value_change", "vat_change", "primary_document_change",
        "operation_date_change", "explanation_only", "posting_available", "wms_movement_available",
    ))
    assert result["blockers"] == ["no_economic_difference", "posting_workflow_not_approved"]

    edited = await client.put(f"/procurement/organizations/{book[0]}/receipt-documents/{draft['id']}", json={
        "key": str(uuid4()), "expected_version": 1,
        "document": {**draft["revisions"][0]["document"], "explanation": "Reviewed correction note"},
    })
    assert edited.status_code == 200, edited.text
    explanation = (await client.get(readiness_path)).json()
    assert explanation["current_version"] == 2
    assert explanation["classification"] == ["explanation_only"]
    assert explanation["explanation_only"] is True and explanation["no_difference"] is False
    assert explanation["blockers"] == ["no_economic_difference", "posting_workflow_not_approved"]
    assert await db.scalar(select(func.count()).select_from(Entry)) == entry_count
    assert await db.scalar(select(func.count()).select_from(ReceiptPosting)) == posting_count


async def test_correction_readiness_classifies_inventory_value_and_vat_changes(client, db, book):
    readiness_path, draft = await create_readiness_correction(client, db, book)
    corrected = {**draft["revisions"][0]["document"], "items": [
        {**draft["revisions"][0]["document"]["items"][0], "net_amount": "125.00",
         "vat_rate": "20", "vat_amount": "25.00", "vat_basis": "Corrected VAT invoice basis"},
    ]}
    edited = await client.put(f"/procurement/organizations/{book[0]}/receipt-documents/{draft['id']}", json={
        "key": str(uuid4()), "expected_version": 1, "document": corrected,
    })
    assert edited.status_code == 200, edited.text

    result = (await client.get(readiness_path)).json()
    assert result["classification"] == ["inventory_value_change", "vat_change"]
    assert result["inventory_value_change"] is True and result["vat_change"] is True
    assert result["physical_change"] is False and result["primary_document_change"] is False
    assert result["blockers"] == [
        "inventory_cost_layer_correction_required", "vat_register_and_eschf_evidence_required",
        "correction_posting_period_required", "posting_workflow_not_approved",
    ]
    assert result["posting_available"] is False and result["wms_movement_available"] is False


def test_correction_classification_keeps_value_and_vat_changes_on_shared_lines_when_other_lines_change():
    from modules.procurement.receipt_documents import ReceiptContent, classify_receipt_correction

    first = document()
    first["items"] = [
        {**first["items"][0], "sku": "A", "sku_title": "A", "lot": "A",
         "net_amount": "100.00", "vat_amount": "20.00"},
        {**first["items"][0], "sku": "B", "sku_title": "B", "lot": "B",
         "net_amount": "200.00", "vat_amount": "40.00"},
    ]
    corrected = {**first, "items": [
        {**first["items"][0], "net_amount": "200.00", "vat_amount": "40.00"},
        {**first["items"][1], "sku": "C", "sku_title": "C", "lot": "C",
         "net_amount": "100.00", "vat_amount": "20.00"},
    ]}

    flags, classification = classify_receipt_correction(
        ReceiptContent.model_validate(first), ReceiptContent.model_validate(corrected),
    )

    assert flags["physical_change"] is True
    assert flags["inventory_value_change"] is True
    assert flags["vat_change"] is True
    assert classification[:3] == ["physical_change", "inventory_value_change", "vat_change"]


async def test_correction_readiness_classifies_physical_primary_and_operation_date_changes(client, db, book):
    readiness_path, draft = await create_readiness_correction(client, db, book)
    original = draft["revisions"][0]["document"]
    from modules.wms.models import WarehouseDirectory
    alternate_warehouse = WarehouseDirectory(organization_id=book[0], name="warehouse2",
                                             title="Synthetic alternate warehouse", is_active=True,
                                             created_by="tester")
    db.add(alternate_warehouse)
    await db.flush()
    corrected = {
        **original,
        "invoice_reference": "INV2",
        "document_date": "2026-09-05",
        "operation_date": "2026-09-05",
        "contract": "contract2",
        "warehouse": "warehouse2", "warehouse_id": alternate_warehouse.id,
        "warehouse_title": "Synthetic alternate warehouse",
        "items": [{**original["items"][0], "lot": "lot2", "quantity": "3.000000"}],
    }
    edited = await client.put(f"/procurement/organizations/{book[0]}/receipt-documents/{draft['id']}", json={
        "key": str(uuid4()), "expected_version": 1, "document": corrected,
    })
    assert edited.status_code == 200, edited.text

    result = (await client.get(readiness_path)).json()
    assert result["classification"] == ["physical_change", "primary_document_change", "operation_date_change"]
    assert result["physical_change"] is True
    assert result["primary_document_change"] is True
    assert result["operation_date_change"] is True
    assert result["inventory_value_change"] is False and result["vat_change"] is False
    assert result["blockers"] == [
        "physical_receipt_adjustment_required", "primary_document_reissue_evidence_required",
        "correction_posting_period_required", "posting_workflow_not_approved",
    ]


async def test_correction_readiness_is_organization_scoped_and_rejects_non_drafts_or_invalid_json(client, db, book):
    from sqlalchemy import update

    from modules.accounting.models import Organization
    from modules.procurement.receipt_documents import ReceiptDocument

    readiness_path, draft = await create_readiness_correction(client, db, book)
    foreign = Organization(name="Readiness foreign company", unp="999999993")
    db.add(foreign)
    await db.commit()
    foreign_response = await client.get(
        f"/procurement/organizations/{foreign.id}/receipt-documents/{draft['id']}/correction-readiness",
    )
    assert foreign_response.status_code == 403

    ordinary = await client.post(f"/procurement/organizations/{book[0]}/receipt-documents", json={
        "key": "readiness-ordinary-receipt", "document": document(),
    })
    assert ordinary.status_code == 201, ordinary.text
    ordinary_response = await client.get(
        f"/procurement/organizations/{book[0]}/receipt-documents/{ordinary.json()['id']}/correction-readiness",
    )
    assert ordinary_response.status_code == 409

    row = await db.get(ReceiptDocument, draft["id"])
    row.current_version = 2
    await db.commit()
    stale = await client.get(readiness_path)
    assert stale.status_code == 409 and "current draft revision is missing" in stale.text
    row.current_version = 1
    await db.commit()

    await db.execute(update(ReceiptRevision).where(
        ReceiptRevision.receipt_id == draft["id"], ReceiptRevision.version == 1,
    ).values(document={"invoice_reference": "incomplete"}))
    await db.commit()
    invalid = await client.get(readiness_path)
    assert invalid.status_code == 409 and "incomplete or invalid" in invalid.text


async def test_stale_source_preview_and_reader_cannot_post(client, db, book):
    path, options = await source_options(client, db, book)
    preview = (await client.post(path + "/preview", json=options)).json()
    assert (await client.put(path, json={"key": "stale-preview-edit", "expected_version": 1, "document": document()})).status_code == 200
    assert (await client.post(path + "/confirm", json={**options, "digest": preview["digest"]})).status_code == 409
    db.add(AccessGrant(organization_id=book[0], subject="buyer", role="reader"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("buyer", ["procurement"])
    assert (await client.post(path + "/preview", json={**options, "expected_version": 2})).status_code == 403
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0


async def test_vat_worksheet_traces_confirmed_primary_revision(client, db, book):
    from datetime import date

    from modules.accounting.models import Account

    path, options = await source_options(client, db, book)
    db.add(Account(organization_id=book[0], code="18", title="Input VAT", category="asset", valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False, quantity_tracking=False, cash=False, normative_ref="synthetic"))
    await db.commit()
    revised = document()
    revised["invoice_reference"] = "INV1 VAT revision"
    assert (await client.put(path, json={"key": "vat-revision", "expected_version": 1, "document": revised})).status_code == 200
    options.update(expected_version=2, vat_account="18")
    preview = await client.post(path + "/preview", json=options)
    assert preview.status_code == 200, preview.text
    confirmed = await client.post(path + "/confirm", json={**options, "digest": preview.json()["digest"]})
    assert confirmed.status_code == 201, confirmed.text
    worksheet = await client.get(f"/accounting/organizations/{book[0]}/input-vat-lines", params={"start": "2026-09-01", "end": "2026-09-30"})
    assert worksheet.status_code == 200, worksheet.text
    row, = worksheet.json()["rows"]
    assert row["operation"] == "inventory_purchase"
    assert row["source"] == f"procurement:receipt:{path.rsplit('/', 1)[1]}"
    assert row["source_version"] == 2 and row["amount"] == "20.00"
    assert row["dimensions"]["settlement_document"] == "INV1 VAT revision"
    assert row["dimensions"]["counterparty"] == revised["supplier"]
    assert row["review_issues"] == [] and row["deduction_status"] == "not_assessed"
    primary = await client.get(f"/procurement/organizations/{book[0]}/receipt-postings/{row['entry_id']}")
    assert primary.status_code == 200, primary.text
    assert primary.json()["version"] == 2
    assert primary.json()["document"]["invoice_reference"] == row["dimensions"]["settlement_document"]


async def test_source_link_failure_rolls_back_entry(client, db, book, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from modules.procurement.receipt_documents import ReceiptPosting
    path, options = await source_options(client, db, book)
    preview = (await client.post(path + "/preview", json=options)).json()
    original = db.flush
    async def failing_flush(*args, **kwargs):
        if any(isinstance(row, ReceiptPosting) for row in db.new):
            raise IntegrityError("synthetic source link failure", {}, Exception())
        return await original(*args, **kwargs)
    monkeypatch.setattr(db, "flush", failing_flush)
    response = await client.post(path + "/confirm", json={**options, "digest": preview["digest"]})
    assert response.status_code == 409
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0
    assert await db.scalar(select(func.count()).select_from(ReceiptPosting)) == 0


async def test_procurement_role_cannot_bypass_accounting_module_access(client, db, book):
    path, options = await source_options(client, db, book)
    preview = (await client.post(path + "/preview", json=options)).json()
    db.add(AccessGrant(organization_id=book[0], subject="buyer", role="accountant"))
    await db.commit()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("buyer", ["procurement"])
    assert (await client.post(path + "/preview", json=options)).status_code == 403
    assert (await client.post(path + "/confirm", json={**options, "digest": preview["digest"]})).status_code == 403
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0

async def test_primary_sources_block_closing_and_invalidate_review(client, db, book):
    from datetime import date

    from modules.accounting import reports, service
    from modules.accounting.models import Period
    from modules.accounting.schemas import CloseInput
    path, options = await source_options(client, db, book)
    period = await db.scalar(select(Period).where(Period.organization_id == book[0]))
    first_generation = period.generation
    assert first_generation == 1
    result = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert result["pending_documents"] == 1
    assert result["status"] == "preliminary"
    with pytest.raises(service.AccountingError, match="Unposted primary"):
        await service.close_period(db, book[0], "2026-09", CloseInput(expected_generation=first_generation, evidence={k: "checked" for k in service.CLOSE_STEPS}), "tester")
    preview = (await client.post(path + "/preview", json=options)).json()
    assert (await client.post(path + "/confirm", json={**options, "digest": preview["digest"]})).status_code == 201
    assert (await client.get(f"/accounting/organizations/{book[0]}/source-controls")).json() == []
    with pytest.raises(service.AccountingError, match="Data changed"):
        await service.close_period(db, book[0], "2026-09", CloseInput(expected_generation=first_generation, evidence={k: "checked" for k in service.CLOSE_STEPS}), "tester")
    await service.close_period(db, book[0], "2026-09", CloseInput(expected_generation=period.generation, evidence={k: "checked" for k in service.CLOSE_STEPS}), "tester")
    await db.commit()
    response = await client.post(path.rsplit("/", 1)[0], json={"key": "late-source", "document": document()})
    assert response.status_code == 409
    assert "closed period" in response.text
    assert len((await client.get(path.rsplit("/", 1)[0])).json()) == 1
