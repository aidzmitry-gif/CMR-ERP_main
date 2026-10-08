import hashlib
import importlib
import json
from copy import deepcopy
from decimal import Decimal

# pytest fixtures are intentionally re-exported into this module's namespace.
# ruff: noqa: F811
import pytest
from sqlalchemy import func, select

from modules.accounting.onec_purchase_import import (
    MAPPING_SCHEMA,
    SOURCE_MAPPING_SCHEMA,
    PurchaseImportError,
    UnmappedPurchaseDocuments,
    build_receipt_drafts,
    load_verified_cache,
    prepare_month_plan,
    write_month_plan,
)
from modules.procurement.receipt_documents import ReceiptCreate
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_procurement_receipt_drafts import source_options
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401

ENTITY = "Document_ПоступлениеТоваровУслуг"


@pytest.fixture
def mapping():
    return {
        "schema_version": MAPPING_SCHEMA,
        "entity": ENTITY,
        "organization_id": 17,
        "paths": {
            "document": {
                "number": "/Number",
                "document_date": "/Date",
                "operation_date": "/OperationDate",
                "supplier_ref": "/Контрагент_Key",
                "contract_ref": "/Договор_Key",
                "warehouse_ref": "/Склад_Key",
                "currency_ref": "/Валюта_Key",
                "lines": "/Товары",
            },
            "line": {
                "sku_ref": "/Номенклатура_Key",
                "quantity": "/Количество",
                "net_amount": "/СуммаБезНДС",
                "vat_rate": "/СтавкаНДС",
                "vat_amount": "/СуммаНДС",
                "vat_basis": "/ОснованиеНДС",
            },
        },
        "currency_refs": {"currency-byn": "BYN"},
        "suppliers": {
            "supplier-1": {"id": 301, "name": "Поставщик ООО", "unp": "123456789"},
        },
        "contracts": {"contract-1": {"id": 401, "number": "Д-2026/1"}},
        "warehouses": {"warehouse-1": {"id": 501, "code": "MINSK", "title": "Основной склад"}},
        "skus": {"sku-1": {"id": 601, "code": "SKU-01", "title": "Аккумулятор", "unit": "шт"}},
    }


@pytest.fixture
def source_doc():
    return {
        "Ref_Key": "receipt-ref-1",
        "Number": "ПН-00017",
        "Date": "2026-09-12T11:30:00",
        "OperationDate": "2026-09-12T00:00:00",
        "Контрагент_Key": "supplier-1",
        "Договор_Key": "contract-1",
        "Склад_Key": "warehouse-1",
        "Валюта_Key": "currency-byn",
        "Товары": [{
            "Номенклатура_Key": "sku-1",
            "Количество": "2.000",
            "СуммаБезНДС": "100.00",
            "СтавкаНДС": "20",
            "СуммаНДС": "20.00",
            "ОснованиеНДС": "ЭСЧФ-00017",
        }],
    }


@pytest.fixture
def metadata():
    return {
        "schema_version": "onec-purchase-cache-v1",
        "source_system": "onec",
        "entity": ENTITY,
        "date_from": "2026-09-01T00:00:00",
        "date_to": "2026-10-01T00:00:00",
        "record_count": 1,
        "source_sha256": "synthetic",
    }


def test_maps_complete_document_to_existing_procurement_receipt_payload(mapping, source_doc, metadata):
    drafts = build_receipt_drafts([source_doc], metadata, mapping)

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft["organization_id"] == 17
    assert draft["key"].startswith("onec:purchase:")
    assert len(draft["key"]) <= 160
    validated = ReceiptCreate.model_validate({"key": draft["key"], "document": draft["document"]})
    assert validated.document.document_date.isoformat() == "2026-09-12"
    assert validated.document.supplier_id == 301
    assert validated.document.contract_id == 401
    assert validated.document.warehouse_id == 501
    assert validated.document.items[0].sku_id == 601
    assert validated.document.items[0].net_amount == 100
    assert validated.document.items[0].vat_amount == 20
    assert draft["document"]["items"][0]["lot"] == "onec:receipt-ref-1:1"


def test_one_unmapped_reference_blocks_the_entire_month(mapping, source_doc, metadata):
    second = deepcopy(source_doc)
    second["Ref_Key"] = "receipt-ref-2"
    second["Контрагент_Key"] = "unknown-supplier"

    with pytest.raises(UnmappedPurchaseDocuments) as error:
        build_receipt_drafts([source_doc, second], metadata, mapping)

    assert len(error.value.issues) == 1
    assert error.value.issues[0]["source_ref"] == "receipt-ref-2"
    assert "exact supplier catalogue mapping" in error.value.issues[0]["reason"]


def test_unknown_currency_and_wrong_entity_fail_closed(mapping, source_doc, metadata):
    bad_currency = deepcopy(source_doc)
    bad_currency["Валюта_Key"] = "currency-unknown"
    with pytest.raises(UnmappedPurchaseDocuments, match="1 document"):
        build_receipt_drafts([bad_currency], metadata, mapping)

    with pytest.raises(PurchaseImportError, match="does not match"):
        build_receipt_drafts([source_doc], {**metadata, "entity": "Document_Other"}, mapping)


def test_wrong_vat_amount_is_reported_instead_of_recalculated(mapping, source_doc, metadata):
    bad = deepcopy(source_doc)
    bad["Товары"][0]["СуммаНДС"] = "19.99"

    with pytest.raises(UnmappedPurchaseDocuments) as error:
        build_receipt_drafts([bad], metadata, mapping)

    assert any("VAT amount does not match" in issue["reason"] for issue in error.value.issues)


def test_duplicate_source_identity_and_out_of_period_date_are_rejected(mapping, source_doc, metadata):
    with pytest.raises(UnmappedPurchaseDocuments) as error:
        build_receipt_drafts([source_doc, source_doc], metadata, mapping)
    assert any(issue["reason"] == "duplicate source key" for issue in error.value.issues)

    out_of_period = deepcopy(source_doc)
    out_of_period["Date"] = "2026-10-01T00:00:00"
    with pytest.raises(UnmappedPurchaseDocuments, match="1 document"):
        build_receipt_drafts([out_of_period], metadata, mapping)


def test_invalid_or_missing_amount_is_reported_not_defaulted(mapping, source_doc, metadata):
    bad = deepcopy(source_doc)
    del bad["Товары"][0]["СуммаБезНДС"]

    with pytest.raises(UnmappedPurchaseDocuments) as error:
        build_receipt_drafts([bad], metadata, mapping)
    assert "net_amount" in error.value.issues[0]["reason"]


def test_mapping_profile_rejects_non_byn_and_bad_pointer(mapping, source_doc, metadata):
    non_byn = deepcopy(mapping)
    non_byn["currency_refs"]["currency-rub"] = "RUB"
    with pytest.raises(PurchaseImportError, match="BYN only"):
        build_receipt_drafts([source_doc], metadata, non_byn)

    bad_pointer = deepcopy(mapping)
    bad_pointer["paths"]["line"]["quantity"] = "/bad~2pointer"
    with pytest.raises(PurchaseImportError, match="JSON Pointer"):
        build_receipt_drafts([source_doc], metadata, bad_pointer)


def test_cache_digest_is_verified_before_mapping(tmp_path, source_doc):
    payload = (json.dumps(source_doc, ensure_ascii=False) + "\n").encode("utf-8")
    (tmp_path / "onec_purchases.jsonl").write_bytes(payload)
    sidecar = {
        "schema_version": "onec-purchase-cache-v1", "source_system": "onec", "entity": ENTITY,
        "date_from": "2026-09-01T00:00:00", "date_to": "2026-10-01T00:00:00",
        "record_count": 1, "source_sha256": hashlib.sha256(payload).hexdigest(),
    }
    (tmp_path / "onec_purchases.meta.json").write_text(json.dumps(sidecar), encoding="utf-8")

    rows, metadata, _ = load_verified_cache(tmp_path)
    assert rows == [source_doc]
    assert metadata["record_count"] == 1
    (tmp_path / "onec_purchases.jsonl").write_bytes(payload + b" ")
    with pytest.raises(PurchaseImportError, match="digest"):
        load_verified_cache(tmp_path)


def test_verified_cache_preserves_exact_decimal_json_number(tmp_path):
    source = (
        '{"Ref_Key":"receipt-ref-precise","Amount":123456789012345678.9012}\n'
    ).encode("utf-8")
    (tmp_path / "onec_purchases.jsonl").write_bytes(source)
    metadata = {
        "schema_version": "onec-purchase-cache-v1", "source_system": "onec",
        "entity": ENTITY, "date_from": "2026-09-01T00:00:00",
        "date_to": "2026-10-01T00:00:00", "record_count": 1,
        "source_sha256": hashlib.sha256(source).hexdigest(),
    }
    (tmp_path / "onec_purchases.meta.json").write_text(json.dumps(metadata), encoding="utf-8")

    rows, _, _ = load_verified_cache(tmp_path)

    assert rows[0]["Amount"] == Decimal("123456789012345678.9012")
    with pytest.raises(PurchaseImportError, match="explicit decimal"):
        from modules.accounting.onec_purchase_import import _decimal

        _decimal(0.1, "amount")


def test_month_plan_is_digest_addressed_and_exact_replay_is_idempotent(
    tmp_path, mapping, source_doc,
):
    source_bytes = (json.dumps(source_doc, ensure_ascii=False) + "\n").encode("utf-8")
    (tmp_path / "onec_purchases.jsonl").write_bytes(source_bytes)
    metadata = {
        "schema_version": "onec-purchase-cache-v1", "source_system": "onec", "entity": ENTITY,
        "date_from": "2026-09-01T00:00:00", "date_to": "2026-10-01T00:00:00",
        "record_count": 1, "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    (tmp_path / "onec_purchases.meta.json").write_text(json.dumps(metadata), encoding="utf-8")
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")

    drafts, plan_meta = prepare_month_plan(tmp_path, mapping_path)
    data_path, meta_path = write_month_plan(tmp_path, drafts, plan_meta)
    replay_data_path, replay_meta_path = write_month_plan(tmp_path, drafts, plan_meta)

    assert data_path == replay_data_path and meta_path == replay_meta_path
    assert json.loads(meta_path.read_text(encoding="utf-8"))["posted"] is False
    assert json.loads(meta_path.read_text(encoding="utf-8"))["posting_previewed"] is False
    assert json.loads(data_path.read_text(encoding="utf-8"))["organization_id"] == 17


async def test_mapped_1c_document_uses_existing_postgres_receipt_preview(
    issuance_pg, pg_book, mapping, source_doc, metadata,
):
    """A mapped source becomes a procurement draft and reaches its real preview route."""
    from datetime import date

    from sqlalchemy import text

    from modules.accounting.models import Entry
    from modules.procurement.supplier_contracts import SupplierContract

    api, factory = issuance_pg
    api.headers["X-User"] = "tester"
    api.headers["X-User-Roles"] = "director"
    async with factory() as session:
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.account', 'id'), "
            "(SELECT max(id) FROM accounting.account))"
        ))
        _, options = await source_options(api, session, pg_book)
        contract = await session.scalar(select(SupplierContract).where(
            SupplierContract.organization_id == pg_book[0],
            SupplierContract.supplier_id == 1,
            SupplierContract.number == "D-2026/1",
        ))
        if contract is None:
            contract = SupplierContract(
                organization_id=pg_book[0], supplier_id=1, number="D-2026/1",
                title="Synthetic 1C supplier contract", signed_on=date(2026, 1, 1),
                evidence="Synthetic test fixture", created_by="test",
            )
            session.add(contract)
            await session.flush()
        contract_id = contract.id
        await session.commit()

    profile = deepcopy(mapping)
    profile["organization_id"] = pg_book[0]
    profile["suppliers"]["supplier-1"] = {"id": 1, "name": "supplier1", "unp": "190000001"}
    profile["contracts"]["contract-1"] = {"id": contract_id, "number": "D-2026/1"}
    profile["warehouses"]["warehouse-1"] = {
        "id": 1, "code": "warehouse1", "title": "Synthetic warehouse",
    }
    profile["skus"]["sku-1"] = {
        "id": 1, "code": "sku1", "title": "Synthetic receipt item", "unit": "шт",
    }
    source = deepcopy(source_doc)
    source["Товары"][0].update({"СтавкаНДС": "0", "СуммаНДС": "0.00"})
    draft = build_receipt_drafts([source], metadata, profile)[0]
    receipt_root = f"/procurement/organizations/{pg_book[0]}/receipt-documents"

    created = await api.post(receipt_root, json={"key": draft["key"], "document": draft["document"]})
    assert created.status_code == 201, created.text
    receipt_id = created.json()["id"]
    preview = await api.post(
        f"{receipt_root}/{receipt_id}/preview",
        json={**options, "expected_version": 1},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["normative_verified"] is True
    assert any(line["side"] == "debit" and line["amount"] == "100.00"
               for line in preview.json()["lines"])
    assert any(line["side"] == "credit" and line["amount"] == "100.00"
               for line in preview.json()["lines"])
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.source == f"procurement:receipt:{receipt_id}"
        )) == 0


async def test_mapped_1c_document_previews_through_existing_receipt_api(
    client, db, book, mapping, source_doc, metadata,
):
    from datetime import date

    from modules.accounting.models import Entry
    from modules.procurement.supplier_contracts import SupplierContract

    await source_options(client, db, book)
    contract = await db.scalar(select(SupplierContract).where(
        SupplierContract.organization_id == book[0],
        SupplierContract.supplier_id == 1,
        SupplierContract.number == "D-2026/1",
    ))
    if contract is None:
        contract = SupplierContract(
            organization_id=book[0], supplier_id=1, number="D-2026/1",
            title="Synthetic 1C supplier contract", signed_on=date(2026, 1, 1),
            evidence="Synthetic test fixture", created_by="test",
        )
        db.add(contract)
        await db.flush()

    profile = deepcopy(mapping)
    profile["organization_id"] = book[0]
    profile["suppliers"]["supplier-1"] = {"id": 1, "name": "supplier1", "unp": "190000001"}
    profile["contracts"]["contract-1"] = {"id": contract.id, "number": "D-2026/1"}
    profile["warehouses"]["warehouse-1"] = {
        "id": 1, "code": "warehouse1", "title": "Synthetic warehouse",
    }
    profile["skus"]["sku-1"] = {
        "id": 1, "code": "sku1", "title": "Synthetic receipt item", "unit": "шт",
    }
    source = deepcopy(source_doc)
    source["Товары"][0].update({"СтавкаНДС": "0", "СуммаНДС": "0.00"})
    draft = build_receipt_drafts([source], metadata, profile)[0]
    root = f"/procurement/organizations/{book[0]}/receipt-documents"
    created = await client.post(root, json={"key": draft["key"], "document": draft["document"]})
    assert created.status_code == 201, created.text

    options = {
        "expected_version": 1, "posting_date": "2026-09-12", "policy_id": book[1],
        "settlement_account": "60", "vat_account": None, "inventory_accounts": ["41.2"],
    }
    receipt_id = created.json()["id"]
    preview = await client.post(f"{root}/{receipt_id}/preview", json=options)
    assert preview.status_code == 200, preview.text
    assert any(line["side"] == "debit" and line["amount"] == "100.00"
               for line in preview.json()["lines"])
    assert any(line["side"] == "credit" and line["amount"] == "100.00"
               for line in preview.json()["lines"])
    assert await db.scalar(select(func.count()).select_from(Entry).where(
        Entry.source == f"procurement:receipt:{receipt_id}"
    )) == 0


def test_import_month_cli_builds_and_replays_the_mapped_draft_plan(
    tmp_path, monkeypatch, mapping, source_doc,
):
    importer = importlib.import_module("scripts.import_month")
    source_bytes = (json.dumps(source_doc, ensure_ascii=False) + "\n").encode("utf-8")
    (tmp_path / "onec_purchases.jsonl").write_bytes(source_bytes)
    sidecar = {
        "schema_version": "onec-purchase-cache-v1", "source_system": "onec", "entity": ENTITY,
        "date_from": "2026-09-01T00:00:00", "date_to": "2026-10-01T00:00:00",
        "record_count": 1, "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    (tmp_path / "onec_purchases.meta.json").write_text(
        json.dumps(sidecar), encoding="utf-8",
    )
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(tmp_path.resolve()))
    monkeypatch.setenv("IMPORT_ONEC_PURCHASE_MAPPING", str(mapping_path.resolve()))

    importer.map_onec_purchases()
    importer.map_onec_purchases()

    plan_paths = list(tmp_path.glob("onec_purchase_drafts_*.jsonl"))
    assert len(plan_paths) == 1
    request = json.loads(plan_paths[0].read_text(encoding="utf-8"))
    assert request["organization_id"] == 17
    assert request["document"]["invoice_reference"] == "ПН-00017"


def test_cli_unmapped_reference_writes_report_and_no_partial_draft_package(
    tmp_path, monkeypatch, mapping, source_doc,
):
    importer = importlib.import_module("scripts.import_month")
    bad_source = deepcopy(source_doc)
    bad_source["Контрагент_Key"] = "supplier-not-mapped"
    source_bytes = (json.dumps(bad_source, ensure_ascii=False) + "\n").encode("utf-8")
    (tmp_path / "onec_purchases.jsonl").write_bytes(source_bytes)
    sidecar = {
        "schema_version": "onec-purchase-cache-v1", "source_system": "onec", "entity": ENTITY,
        "date_from": "2026-09-01T00:00:00", "date_to": "2026-10-01T00:00:00",
        "record_count": 1, "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    (tmp_path / "onec_purchases.meta.json").write_text(json.dumps(sidecar), encoding="utf-8")
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(tmp_path.resolve()))
    monkeypatch.setenv("IMPORT_ONEC_PURCHASE_MAPPING", str(mapping_path.resolve()))

    with pytest.raises(RuntimeError, match="черновой пакет не создан"):
        importer.map_onec_purchases()

    assert not list(tmp_path.glob("onec_purchase_drafts_*.jsonl"))
    reports = list(tmp_path.glob("onec_purchase_unmapped_*.jsonl"))
    assert len(reports) == 1
    issue = json.loads(reports[0].read_text(encoding="utf-8"))
    assert issue["source_ref"] == "receipt-ref-1"
    assert "exact supplier catalogue mapping" in issue["reason"]


@pytest.fixture
def source_mapping(mapping):
    profile = deepcopy(mapping)
    profile["schema_version"] = SOURCE_MAPPING_SCHEMA
    profile["entity"] = "Document_ПриобретениеТоваровУслуг"
    paths = profile["paths"]["line"]
    paths["amount"] = "/Сумма"
    del paths["net_amount"]
    del paths["vat_basis"]
    profile["source_rules"] = {
        "price_includes_vat": "/ЦенаВключаетНДС",
        "gross_amount": "/СуммаСНДС",
        "vat_basis": "/НалогообложениеНДС",
        "vat_rates": {"НДС20": "20", "БезНДС": "0"},
        "amount_modes": {"false": "net", "true": "gross"},
    }
    return profile


@pytest.fixture
def source_receipt(source_doc):
    row = deepcopy(source_doc)
    row.update(DataVersion="synthetic-version-1", Posted=True, DeletionMark=False)
    row["ЦенаВключаетНДС"] = False
    row["НалогообложениеНДС"] = "synthetic-source-tax-mode"
    line = row["Товары"][0]
    line["Сумма"] = "100.00"
    line["СуммаСНДС"] = "120.00"
    line["СтавкаНДС"] = "НДС20"
    del line["СуммаБезНДС"]
    del line["ОснованиеНДС"]
    return row


@pytest.mark.parametrize("includes_vat,mode,amount", [
    (False, "net", "100.00"), (True, "gross", "120.00"),
    (True, "net", "100.00"), (False, "gross", "120.00"),
])
def test_source_v2_uses_only_explicit_amount_policy_and_preserves_source(
    source_mapping, source_receipt, metadata, includes_vat, mode, amount,
):
    source_receipt["ЦенаВключаетНДС"] = includes_vat
    source_receipt["Товары"][0]["Сумма"] = amount
    source_mapping["source_rules"]["amount_modes"][str(includes_vat).lower()] = mode
    original = deepcopy(source_receipt)
    profile_before = deepcopy(source_mapping)
    meta = {**metadata, "entity": source_mapping["entity"]}

    draft = build_receipt_drafts([source_receipt], meta, source_mapping)[0]

    assert source_receipt == original and source_mapping == profile_before
    item = draft["document"]["items"][0]
    assert Decimal(item["net_amount"]) == Decimal("100.00")
    assert Decimal(item["vat_amount"]) == Decimal("20.00")
    assert item["vat_basis"] == source_receipt["НалогообложениеНДС"]
    assert item["lot"] == "onec:receipt-ref-1:1"
    assert draft["key"] == "onec:purchase:" + hashlib.sha256(
        (source_mapping["entity"] + "\0receipt-ref-1").encode("utf-8")
    ).hexdigest()
    ReceiptCreate.model_validate({"key": draft["key"], "document": draft["document"]})


def test_source_v2_no_vat_is_explicit_not_a_missing_rate_default(source_mapping, source_receipt, metadata):
    line = source_receipt["Товары"][0]
    line.update({"СтавкаНДС": "БезНДС", "СуммаНДС": "0", "СуммаСНДС": "100"})
    item = build_receipt_drafts(
        [source_receipt], {**metadata, "entity": source_mapping["entity"]}, source_mapping,
    )[0]["document"]["items"][0]
    assert Decimal(item["vat_rate"]) == Decimal(item["vat_amount"]) == 0


@pytest.mark.parametrize("field,value,reason", [
    ("DataVersion", None, "DataVersion"), ("DataVersion", " ", "DataVersion"),
    ("Posted", False, "must be posted"), ("Posted", 1, "must be posted"),
    ("DeletionMark", True, "must be posted"), ("DeletionMark", 0, "must be posted"),
    ("ЦенаВключаетНДС", "false", "source boolean"),
    ("ЦенаВключаетНДС", 1, "source boolean"),
    ("НалогообложениеНДС", "", "vat_basis"),
    ("Валюта_Key", "unmapped-currency", "explicit BYN mapping"),
    ("Контрагент_Key", "unmapped-supplier", "exact supplier"),
    ("Договор_Key", "unmapped-contract", "exact contract"),
    ("Склад_Key", "unmapped-warehouse", "organization warehouse"),
])
def test_source_v2_invalid_document_blocks_whole_package(
    source_mapping, source_receipt, metadata, field, value, reason,
):
    bad = deepcopy(source_receipt)
    bad["Ref_Key"] = "receipt-ref-2"
    bad[field] = value
    with pytest.raises(UnmappedPurchaseDocuments) as error:
        build_receipt_drafts(
            [source_receipt, bad], {**metadata, "entity": source_mapping["entity"]}, source_mapping,
        )
    assert len(error.value.issues) == 1
    assert reason in error.value.issues[0]["reason"]


@pytest.mark.parametrize("field,value,reason", [
    ("СтавкаНДС", "НДС_СЕКРЕТ_99", "no explicit rate mapping"),
    ("СтавкаНДС", 20, "must be text"),
    ("СуммаСНДС", "119.99", "gross amount differs"),
    ("СуммаНДС", "19.99", "gross amount differs"),
    ("Сумма", "100.001", "exact to cents"),
    ("Сумма", 100.0, "explicit decimal"),
    ("Сумма", "1e18", "money range"),
    ("Сумма", "1e-21", "precision bounds"),
    ("Сумма", "NaN", "finite"),
    ("Сумма", "-1", "money range"),
    ("Номенклатура_Key", "unmapped-sku", "exact SKU"),
])
def test_source_v2_invalid_line_is_not_defaulted_or_rounded(
    source_mapping, source_receipt, metadata, field, value, reason,
):
    source_receipt["Товары"][0][field] = value
    with pytest.raises(UnmappedPurchaseDocuments) as error:
        build_receipt_drafts(
            [source_receipt], {**metadata, "entity": source_mapping["entity"]}, source_mapping,
        )
    assert reason in error.value.issues[0]["reason"]
    assert "НДС_СЕКРЕТ_99" not in str(error.value.issues)


def test_source_v2_consistent_gross_still_requires_correct_source_vat(source_mapping, source_receipt, metadata):
    source_receipt["Товары"][0].update({"СуммаНДС": "19.99", "СуммаСНДС": "119.99"})
    with pytest.raises(UnmappedPurchaseDocuments) as error:
        build_receipt_drafts(
            [source_receipt], {**metadata, "entity": source_mapping["entity"]}, source_mapping,
        )
    assert "VAT amount does not match" in error.value.issues[0]["reason"]


@pytest.mark.parametrize("mutation", ["missing_rules", "unknown_mode", "missing_mode", "unknown_rule",
                                        "invalid_pointer", "empty_rates", "negative_rate", "large_rate",
                                        "float_rate", "missing_unit"])
def test_source_v2_incomplete_profile_fails_before_document_mapping(source_mapping, metadata, mutation):
    rules = source_mapping["source_rules"]
    if mutation == "missing_rules":
        del source_mapping["source_rules"]
    elif mutation == "unknown_mode":
        rules["amount_modes"]["true"] = "auto"
    elif mutation == "missing_mode":
        del rules["amount_modes"]["false"]
    elif mutation == "unknown_rule":
        rules["guess_rate"] = True
    elif mutation == "invalid_pointer":
        rules["gross_amount"] = "/bad~2pointer"
    elif mutation == "empty_rates":
        rules["vat_rates"] = {}
    elif mutation in ("negative_rate", "large_rate", "float_rate"):
        rules["vat_rates"]["НДС20"] = {"negative_rate": "-1", "large_rate": "100.01", "float_rate": 20.0}[mutation]
    else:
        source_mapping["skus"]["sku-1"]["unit"] = ""
    with pytest.raises(PurchaseImportError):
        build_receipt_drafts([], {**metadata, "entity": source_mapping["entity"]}, source_mapping)


def test_source_v2_large_gross_subtraction_stays_exact_at_money_boundary(
    source_mapping, source_receipt, metadata,
):
    source_receipt["ЦенаВключаетНДС"] = True
    source_receipt["Товары"][0].update({
        "Сумма": "999999999999999999.98", "СуммаСНДС": "999999999999999999.98",
        "СуммаНДС": "166666666666666666.66",
    })
    item = build_receipt_drafts(
        [source_receipt], {**metadata, "entity": source_mapping["entity"]}, source_mapping,
    )[0]["document"]["items"][0]
    assert Decimal(item["net_amount"]) == Decimal("833333333333333333.32")
    assert Decimal(item["vat_amount"]) == Decimal("166666666666666666.66")


def test_source_v2_plan_preserves_raw_digest_identity_and_data_version(
    tmp_path, source_mapping, source_receipt, metadata,
):
    payload = (json.dumps(source_receipt, ensure_ascii=False) + "\n").encode("utf-8")
    cache = tmp_path / "onec_purchases.jsonl"
    cache.write_bytes(payload)
    (tmp_path / "onec_purchases.meta.json").write_text(json.dumps({
        **metadata, "entity": source_mapping["entity"], "source_sha256": hashlib.sha256(payload).hexdigest(),
    }), encoding="utf-8")
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(source_mapping, ensure_ascii=False), encoding="utf-8")

    drafts, plan = prepare_month_plan(tmp_path, mapping_path)
    data_path, meta_path = write_month_plan(tmp_path, drafts, plan)
    assert cache.read_bytes() == payload
    assert plan["source_sha256"] == hashlib.sha256(payload).hexdigest()
    assert plan["mapping_sha256"] == hashlib.sha256(mapping_path.read_bytes()).hexdigest()
    assert plan["mapping_schema_version"] == SOURCE_MAPPING_SCHEMA
    assert plan["source_documents"] == [{"ref_key": "receipt-ref-1", "data_version": "synthetic-version-1"}]
    assert plan["posted"] is plan["posting_previewed"] is False
    assert write_month_plan(tmp_path, drafts, plan) == (data_path, meta_path)
    saved = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved["source_documents"] == plan["source_documents"]
