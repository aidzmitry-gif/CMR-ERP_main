"""Безопасный load-only путь для локального кэша импорта Bitrix24/1С."""
from __future__ import annotations

import importlib
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _write_jsonl(root: Path, name: str, rows: list[dict]) -> None:
    (root / f"{name}.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_bitrix_product_sources(
    root: Path,
    rows: list[dict],
    *,
    deal_id: str = "30",
    product_id: str = "501",
    xml_id: str = "sku-1",
    onec_sku_rows: list[dict] | None = None,
) -> None:
    _write_jsonl(root, "bx_product_rows", [{"deal_id": deal_id, "rows": rows}])
    _write_jsonl(
        root,
        "bx_products",
        [{"ID": product_id, "XML_ID": xml_id, "CODE": "BX-PRODUCT-501",
          "NAME": "Synthetic Bitrix product"}],
    )
    if onec_sku_rows is not None:
        _write_jsonl(root, "onec_sku", onec_sku_rows)


def _write_bitrix_tasks(root: Path, rows: list[dict]) -> None:
    _write_jsonl(root, "bx_tasks", rows)


def _bitrix_task_row(*, task_id: str = "101", **changes) -> dict:
    return {
        "id": task_id,
        "title": "Synthetic task title",
        "description": "Synthetic task description",
        "descriptionInBbcode": "Y",
        "responsibleId": "7001",
        "status": "6",
        "deadline": "2024-11-02T13:00:00+03:00",
        "ufCrmTask": ["D_30", "L_80"],
        "ufTaskWebdavFiles": [],
        "ufMailMessage": None,
        **changes,
    }


def _write_bitrix_stage_history(root: Path, rows: list[dict]) -> None:
    _write_jsonl(root, "bx_stage_history", rows)


def _write_bitrix_timeline_comments(root: Path, rows: list[dict]) -> None:
    _write_jsonl(root, "bx_timeline_comments", rows)


def _timeline_comment_row(
    *, entity_type: str = "deal", entity_id: str = "30", comment_id: str = "77",
    created: str = "2024-11-02T13:00:00+03:00", body: str = "Synthetic timeline text",
    author_id: str = "1", files: object = None,
) -> dict:
    return {
        "ID": comment_id,
        "CREATED": created,
        "ENTITY_ID": entity_id,
        "ENTITY_TYPE": entity_type,
        "AUTHOR_ID": author_id,
        "COMMENT": body,
        "FILES": {} if files is None else files,
    }


def _write_comment_binary_bundle(
    root: Path,
    files: list[tuple[str, str, str, bytes, str | None, str]],
) -> None:
    links = []
    inventory_by_key = {}
    folder = root / "comment_binary_files"
    folder.mkdir(exist_ok=True)
    for prior_path in folder.iterdir():
        if prior_path.is_file() and not prior_path.is_symlink():
            prior_path.unlink()
        else:
            raise AssertionError("synthetic binary fixture is not a flat file tree")
    for deal_id, comment_id, file_id, content, name, content_type in files:
        key = f"disk:{file_id}"
        filename = hashlib.sha256(key.encode("ascii")).hexdigest() + ".bin"
        links.append({
            "source": "comment", "entity_type": "deal", "entity_id": deal_id,
            "source_id": comment_id, "file_id": file_id, "binary_key": key,
        })
        data = bytes(content)
        inventory_by_key[key] = {
            "key": key, "filename": filename, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_type": content_type, "name": name,
        }
        path = folder / filename
        if not path.exists():
            path.write_bytes(data)
    _write_jsonl(root, "bx_comment_binary_links", links)
    _write_jsonl(
        root, "bx_comment_binary_inventory",
        sorted(inventory_by_key.values(), key=lambda row: row["key"]),
    )


def _seal_private_cache_for_test(
    root: Path, *, binary_v2: bool = False, binary_v3: bool = False,
    ready: bool = True,
    include_tasks: bool = False,
    blocked: dict | None = None,
) -> None:
    if binary_v2 and binary_v3:
        raise AssertionError("choose one private cache format")
    binary_cache = binary_v2 or binary_v3
    names = {
        "bx_deals", "bx_contacts", "bx_leads", "bx_calls", "bx_users",
        "bx_companies", "bx_requisites", "onec_counterparties", "onec_sku",
        "bx_product_rows", "bx_products", "bx_stage_history", "bx_timeline_comments",
    }
    if binary_cache:
        names.update({"bx_comment_binary_links", "bx_comment_binary_inventory"})
    if binary_v3:
        names.update({"bx_call_binary_links", "bx_call_binary_inventory"})
    if include_tasks:
        names.add("bx_tasks")
    (root / "onec_sales.jsonl").unlink(missing_ok=True)
    for name in names:
        path = root / f"{name}.jsonl"
        if not path.exists():
            _write_jsonl(root, name, [])
    assert {path.stem for path in root.glob("*.jsonl")} == names
    entries = {}
    for name in names:
        data = (root / f"{name}.jsonl").read_bytes()
        entries[name] = {
            "records": len(data.splitlines()),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    cache_format = (
        "CRM-LIVE-001-private-cache-v3" if binary_v3
        else "CRM-LIVE-001-private-cache-v2" if binary_v2
        else "CRM-LIVE-001-private-cache-v1"
    )
    manifest = {
        "format": cache_format,
        "cache": entries,
        "ready_for_load": ready,
        "blocked_source_groups": blocked if blocked is not None else {},
    }
    if binary_cache:
        folder = root / "comment_binary_files"
        folder.mkdir(exist_ok=True)
        inventory = [
            json.loads(line)
            for line in (root / "bx_comment_binary_inventory.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        fingerprint = hashlib.sha256()
        total_bytes = 0
        for row in sorted(inventory, key=lambda item: item["filename"]):
            total_bytes += row["bytes"]
            fingerprint.update(
                f"{row['filename']}:{row['bytes']}:{row['sha256']}\n".encode("ascii")
            )
        manifest["source_manifests"] = {
            "bitrix": "a" * 64, "onec": "b" * 64, "binary": "c" * 64,
        }
        manifest["comment_binary_files"] = {
            "records": len(inventory), "bytes": total_bytes,
            "sha256": fingerprint.hexdigest(),
        }
    if binary_v3:
        folder = root / "call_binary_files"
        folder.mkdir(exist_ok=True)
        inventory = [
            json.loads(line)
            for line in (root / "bx_call_binary_inventory.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        fingerprint = hashlib.sha256()
        total_bytes = 0
        for row in sorted(inventory, key=lambda item: item["filename"]):
            body = (folder / row["filename"]).read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            total_bytes += len(body)
            fingerprint.update(
                f"{row['filename']}:{len(body)}:{digest}\n".encode("ascii")
            )
        manifest["call_binary_files"] = {
            "records": len(inventory), "bytes": total_bytes,
            "sha256": fingerprint.hexdigest(),
        }
    body = json.dumps(manifest).encode("utf-8")
    (root / "private-source-manifest.json").write_bytes(body)
    (root / "PRIVATE_CACHE_FORMAT").write_text(
        cache_format + ":" + hashlib.sha256(body).hexdigest() + "\n",
        encoding="ascii",
    )


def _stage_synthetic_v3_call_cache(root: Path) -> Path:
    root = root.resolve()
    root.mkdir()
    _make_cache(root)
    call = json.loads((root / "bx_calls.jsonl").read_text(encoding="utf-8").splitlines()[0])
    call.update({"CALL_ID": "call-50", "RECORD_FILE_ID": "42"})
    _write_jsonl(root, "bx_calls", [call])
    _write_comment_binary_bundle(root, [])

    key = "call:50"
    filename = hashlib.sha256(key.encode("ascii")).hexdigest() + ".bin"
    content = b"synthetic call recording bytes"
    call_folder = root / "call_binary_files"
    call_folder.mkdir()
    (call_folder / filename).write_bytes(content)
    _write_jsonl(root, "bx_call_binary_links", [{
        "source": "call", "source_id": "50", "call_id": "call-50",
        "record_file_id": "42", "entity_type": "CONTACT", "entity_id": "20",
        "portal_user_id": "1", "binary_key": key,
    }])
    _write_jsonl(root, "bx_call_binary_inventory", [{
        "key": key, "filename": filename, "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "content_type": "audio/wav",
    }])
    _seal_private_cache_for_test(
        root, binary_v3=True, ready=False, blocked={"call_recordings": 1},
    )
    return root


def _reseal_v3_manifest_for_test(root: Path, manifest: dict) -> None:
    manifest["cache"] = {}
    for path in sorted(root.glob("*.jsonl")):
        data = path.read_bytes()
        manifest["cache"][path.stem] = {
            "records": len(data.splitlines()),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    body = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    (root / "private-source-manifest.json").write_bytes(body)
    (root / "PRIVATE_CACHE_FORMAT").write_text(
        "CRM-LIVE-001-private-cache-v3:" + hashlib.sha256(body).hexdigest() + "\n",
        encoding="ascii",
    )


def _stage_synthetic_v2_import_cache(
    root: Path, *, tasks: list[dict] | None = None,
    product_rows: list[dict] | None = None,
    product_xml_id: str = "sku-1",
    expected_blocked: dict | None = None,
) -> Path:
    """Run the real offline stage writer over a complete synthetic v2 source set."""
    from scripts import export_bitrix_private as exporter

    root = root.resolve()
    bitrix_root = root / "bitrix-source"
    onec_root = root / "onec-source"
    binary_root = root / "binary-source"
    output = root / "staged-cache"
    bitrix_root.mkdir()
    onec_root.mkdir()
    binary_root.mkdir()

    bitrix_rows = {
        "deals": [{
            "ID": "30", "TITLE": "Synthetic staged deal", "STAGE_ID": "NEW",
            "CATEGORY_ID": "0", "OPPORTUNITY": "10", "CURRENCY_ID": "BYN",
            "COMPANY_ID": "10", "CONTACT_ID": "20", "ASSIGNED_BY_ID": "1",
            "DATE_CREATE": "2024-11-02T10:00:00",
        }],
        "contacts": [{
            "ID": "20", "NAME": "Synthetic", "LAST_NAME": "Contact",
            "COMPANY_ID": "10", "PHONE": [], "EMAIL": [],
        }],
        "leads": [{
            "ID": "40", "TITLE": "Synthetic lead", "STATUS_ID": "NEW",
            "SOURCE_ID": "WEB", "ASSIGNED_BY_ID": "1",
            "DATE_CREATE": "2024-11-02T10:00:00",
        }],
        "users": [{"ID": "1", "NAME": "Synthetic", "LAST_NAME": "User"}],
        "company_name_evidence": [{"ID": "10", "TITLE": "Synthetic Company"}],
        "requisites": [{"ID": "101", "ENTITY_ID": "10", "RQ_INN": "100000002"}],
        "deal_product_rows": [{
            "deal_id": "30", "rows": product_rows or [],
        }],
        "product_catalog_evidence": ([{
            "ID": "501", "XML_ID": product_xml_id,
            "CODE": "BX-PRODUCT-501", "NAME": "Synthetic Bitrix product",
        }] if product_rows else []),
        "tasks": tasks or [],
        "timeline_comments": [{
            "ID": "77", "ENTITY_TYPE": "deal", "ENTITY_ID": "30",
            "CREATED": "2024-11-02T13:00:00+03:00", "AUTHOR_ID": "1",
            "COMMENT": "Synthetic staged comment",
            "FILES": {"901": {"id": 901, "name": "synthetic.pdf"}},
        }],
    }
    bitrix_manifest = {}
    for name in sorted(exporter.PRIVATE_BITRIX_DATASETS):
        dataset = exporter.Dataset(bitrix_root, name)
        for index, row in enumerate(bitrix_rows.get(name, [])):
            identity = (
                str(row["deal_id"]) if name == "deal_product_rows"
                else f"deal:{row['ID']}:{index}" if name == "timeline_comments"
                else str(row.get("ID") or row.get("id") or row.get("ENTITY_ID") or index)
            )
            dataset.add(identity, row)
        bitrix_manifest[name] = dataset.summary()
    (bitrix_root / "manifest.json").write_text(
        json.dumps(bitrix_manifest), encoding="utf-8"
    )

    onec_rows = {
        "Catalog_Контрагенты": [{
            "Ref_Key": "cp-1", "Description": "Synthetic Company", "ИНН": "100000002",
        }],
        "Catalog_Номенклатура": [{
            "Ref_Key": "sku-1", "Code": "SKU-1", "Description": "Synthetic SKU",
            "DeletionMark": False,
        }],
    }
    onec_manifest = {}
    for name in sorted(exporter.PRIVATE_ONEC_DATASETS):
        dataset = exporter.Dataset(onec_root, name)
        for row in onec_rows[name]:
            dataset.add(row["Ref_Key"], row)
        onec_manifest[name] = dataset.summary()
    (onec_root / "manifest.json").write_text(
        json.dumps(onec_manifest), encoding="utf-8"
    )

    binary_files = binary_root / "binary_files"
    binary_files.mkdir()
    key = "disk:901"
    binary_filename = hashlib.sha256(key.encode("ascii")).hexdigest() + ".bin"
    content = b"synthetic staged binary bytes"
    digest = hashlib.sha256(content).hexdigest()
    (binary_files / binary_filename).write_bytes(content)
    inventory = exporter.Dataset(binary_root, "binary_inventory")
    inventory.add(key, {
        "key": key, "filename": binary_filename, "bytes": len(content),
        "sha256": digest, "content_type": "application/pdf", "name": "synthetic.pdf",
    })
    links = exporter.Dataset(binary_root, "binary_links")
    links.add("deal:30:77:901", {
        "source": "comment", "entity_type": "deal", "entity_id": "30",
        "source_id": "77", "file_id": "901", "binary_key": key,
    })
    binary_fingerprint = hashlib.sha256(
        f"{binary_filename}:{len(content)}:{digest}\n".encode("ascii")
    ).hexdigest()
    (binary_root / "manifest.json").write_text(json.dumps({
        "binary_files": {
            "records": 1, "bytes": len(content), "sha256": binary_fingerprint,
        },
        "binary_inventory": inventory.summary(),
        "binary_links": links.summary(),
        "unavailable_recordings": {"records": 0},
    }), encoding="utf-8")

    staged = exporter.stage_import_cache(
        bitrix_root, onec_root, output, binary_root
    )
    assert staged["format"] == "CRM-LIVE-001-private-cache-v2"
    assert staged["ready_for_load"] is (expected_blocked is None)
    assert staged["blocked_source_groups"] == (expected_blocked or {})
    assert len(staged["cache"]) == 16
    return output


def test_deal_item_source_key_keeps_manual_lines_and_rejects_duplicate_import():
    from sqlalchemy import create_engine, insert, select
    from sqlalchemy.exc import IntegrityError

    from modules.sales.models import DealItem

    engine = create_engine(
        "sqlite://", execution_options={"schema_translate_map": {"sales": None}}
    )
    DealItem.__table__.create(engine)
    source_ref = "bitrix:deal-product-row:30:61"
    with engine.begin() as connection:
        # Manual and legacy rows retain NULL; repeated SKU is a valid sale line.
        connection.execute(insert(DealItem), [
            {"deal_id": 1, "sku_id": 7, "source_ref": None},
            {"deal_id": 1, "sku_id": 7, "source_ref": None},
        ])
        connection.execute(insert(DealItem).values(
            deal_id=1, sku_id=7, source_ref=source_ref
        ))
        with pytest.raises(IntegrityError):
            connection.execute(insert(DealItem).values(
                deal_id=1, sku_id=7, source_ref=source_ref
            ))
        assert connection.execute(select(DealItem.source_ref)).all().count((source_ref,)) == 1


@pytest.mark.parametrize(
    ("value", "deleted"),
    [
        (True, True), (False, False), (1, True), (0, False),
        (" TRUE ", True), ("false", False), ("1", True), (" 0 ", False),
        ("", False), ("   ", False), (None, False),
    ],
)
def test_onec_deletion_mark_parser_accepts_only_defined_active_and_deleted_forms(value, deleted):
    assert _module()._onec_deletion_mark(value) is deleted


def _make_cache(root: Path) -> None:
    _write_jsonl(root, "bx_users", [{"ID": "1", "NAME": "Test", "LAST_NAME": "User"}])
    _write_jsonl(root, "bx_companies", [{"ID": "10", "TITLE": "Test Company"}])
    _write_jsonl(
        root,
        "bx_contacts",
        [{"ID": "20", "NAME": "Test", "LAST_NAME": "Contact", "COMPANY_ID": "10",
          "PHONE": [{"VALUE": "+375 29 123-45-67"}],
          "EMAIL": [{"VALUE": "test@example.invalid"}]}],
    )
    _write_jsonl(root, "bx_requisites", [{"ENTITY_ID": "10", "RQ_INN": "100000002"}])
    # A unique UNP match makes 1C, rather than the Bitrix title, the master source.
    _write_jsonl(
        root,
        "bx_deals",
        [
            {
                "ID": "30",
                "TITLE": "Test Deal",
                "STAGE_ID": "WON",
                "CATEGORY_ID": "0",
                "OPPORTUNITY": "10",
                "CURRENCY_ID": "BYN",
                "COMPANY_ID": "10",
                "CONTACT_ID": "20",
                "ASSIGNED_BY_ID": "1",
                "DATE_CREATE": "2024-11-02T10:00:00",
            }
        ],
    )
    _write_jsonl(
        root,
        "bx_leads",
        [
            {
                "ID": "40",
                "TITLE": "Test Lead",
                "STATUS_ID": "NEW",
                "SOURCE_ID": "WEB",
                "ASSIGNED_BY_ID": "1",
                "DATE_CREATE": "2024-11-02T10:00:00",
            }
        ],
    )
    _write_jsonl(
        root,
        "bx_calls",
        [
            {
                "ID": "50",
                "CALL_ID": "50",
                "CALL_START_DATE": "2024-11-02T10:00:00",
                "CALL_DURATION": "10",
                "CALL_FAILED_CODE": "200",
                "CALL_TYPE": "2",
                "CRM_ENTITY_TYPE": "CONTACT",
                "CRM_ENTITY_ID": "20",
                "PORTAL_USER_ID": "1",
            }
        ],
    )
    _write_jsonl(
        root,
        "onec_counterparties",
        [{"Ref_Key": "cp-1", "Description": "Test 1C Company", "ИНН": "100000002"}],
    )
    _write_jsonl(root, "onec_sku", [{"Ref_Key": "sku-1", "Code": "SKU-1", "Description": "Test SKU"}])
    _write_jsonl(
        root,
        "onec_sales",
        [
            {
                "Ref_Key": "sale-1",
                "Контрагент_Key": "cp-1",
                "Number": "S-1",
                "Date": "2024-11-03T10:00:00",
                "Posted": True,
                "СуммаДокумента": "10",
                "Товары": [
                    {
                        "Номенклатура_Key": "sku-1",
                        "Цена": "10",
                        "ЦенаСоСкидкой": "10",
                    }
                ],
            }
        ],
    )


def _make_counterparty_cache(
    root: Path,
    companies: list[dict],
    requisites: list[dict],
    onec_counterparties: list[dict],
) -> None:
    _write_jsonl(root, "bx_companies", companies)
    _write_jsonl(root, "bx_requisites", requisites)
    _write_jsonl(root, "onec_counterparties", onec_counterparties)


def _set_load_environment(monkeypatch, cache: Path, db_path: Path) -> None:
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(cache.resolve()))
    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")


async def _seed_existing_deal_directory(
    module, *, duplicate_clients: bool = False, preexisting_conflicting_link: bool = False
):
    """Add synthetic, already trusted CRM directory rows to a loaded pilot deal."""
    from decimal import Decimal

    from sqlalchemy import func, select

    from core.domain.models import CounterpartyAlias
    from modules.sales.models import CrmClient, CrmClientContact, Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        alias = (
            await session.execute(
                select(CounterpartyAlias).where(
                    CounterpartyAlias.source == "1c",
                    CounterpartyAlias.external_ref == "cp-1",
                )
            )
        ).scalar_one()
        clients = []
        for index in range(2 if duplicate_clients else 1):
            client = CrmClient(
                name=f"Synthetic CRM client {index + 1}",
                name_key=f"synthetic crm client {index + 1}",
                unp=None if duplicate_clients else "100000002",
                owner_id=901,
                counterparty_id=alias.counterparty_id,
                request_key=f"synthetic-client-{index + 1}",
                request_hash=f"{index + 1:064x}",
                created_by="synthetic test",
            )
            session.add(client)
            await session.flush()
            clients.append(client)

        if preexisting_conflicting_link:
            unrelated_client = CrmClient(
                name="Synthetic unrelated CRM client",
                name_key="synthetic unrelated crm client",
                unp=None,
                owner_id=901,
                counterparty_id=None,
                request_key="synthetic-unrelated-client",
                request_hash="b" * 64,
                created_by="synthetic test",
            )
            session.add(unrelated_client)
            await session.flush()
            clients.append(unrelated_client)

        contact = CrmClientContact(
            crm_client_id=clients[0].id,
            full_name="Test Contact",
            phone="+375291234567",
            email="test@example.invalid",
            contact_key="synthetic-contact-key",
            request_key="synthetic-contact-request",
            request_hash="a" * 64,
        )
        session.add(contact)
        deal = (
            await session.execute(select(Deal).where(Deal.number == "BX-30"))
        ).scalar_one()
        deal.owner_id = 901
        if preexisting_conflicting_link:
            deal.crm_client_id = clients[-1].id
        deal.title = "Manually maintained title"
        deal.counterparty = "Manually maintained display name"
        deal.amount = Decimal("77.50")
        deal.stage = "negotiation"
        deal.next_step = "Keep this manual next step"
        await session.commit()
        client_ids = [client.id for client in clients]
        contact_id = contact.id
        deal_id = deal.id
    await db.disconnect()
    return client_ids, contact_id, deal_id


def _module():
    return importlib.import_module("scripts.import_month")


@pytest.mark.asyncio
async def test_bitrix_product_rows_map_by_exact_1c_keys_and_are_idempotent(
    monkeypatch, tmp_path, capsys
):
    from decimal import Decimal

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [{
        "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
        "PRODUCT_ID": "501", "QUANTITY": "2.25", "PRICE": "999.99",
    }])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    first_output = capsys.readouterr().out
    assert "deal_item: 1" in first_output
    assert "Synthetic Bitrix product" not in first_output

    from sqlalchemy import func, select

    from core.domain.models import Sku
    from modules.sales.models import Deal, DealItem

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        sku = (await session.execute(select(Sku).where(Sku.code == "SKU-1"))).scalar_one()
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        item = (await session.execute(select(DealItem))).scalar_one()
        assert (item.deal_id, item.sku_id, item.qty, item.unit_price, item.source_ref) == (
            deal.id, sku.id, Decimal("2.25"), None,
            "bitrix:deal-product-row:30:61",
        )
        first_ids = (deal.id, sku.id, item.id)
        assert (await session.execute(select(func.count()).select_from(DealItem))).scalar_one() == 1
    await db.disconnect()

    await module.load()
    second_output = capsys.readouterr().out
    assert "deal_item: 0" in second_output
    assert "deal_item_existing: 1" in second_output
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        sku = (await session.execute(select(Sku).where(Sku.code == "SKU-1"))).scalar_one()
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        item = (await session.execute(select(DealItem))).scalar_one()
        assert (deal.id, sku.id, item.id) == first_ids
        assert (await session.execute(select(func.count()).select_from(DealItem))).scalar_one() == 1
    await db.disconnect()

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    product_gap = next(row for row in report["gaps"] if row["area"] == "bitrix_products")
    assert product_gap["status"] == "source_available"
    assert product_gap["source_rows"] == 1
    assert product_gap["destination_total_imported_rows"] == 1
    assert product_gap["source_ref_expected_keys"] == 1
    assert product_gap["source_ref_destination_keys"] == 1
    assert product_gap["source_ref_set_match"] is True
    assert product_gap["source_ref_semantic_match"] is True
    assert product_gap["source_ref_semantic_mismatches"] == 0
    assert product_gap["blocker"] is False
    assert "Synthetic Bitrix product" not in json.dumps(report)


@pytest.mark.asyncio
async def test_sealed_stage_imports_nonempty_tasks_and_products_repeatably(
    monkeypatch, tmp_path, capsys
):
    from decimal import Decimal

    module = _module()
    cache = _stage_synthetic_v2_import_cache(
        tmp_path,
        tasks=[_bitrix_task_row()],
        product_rows=[{
            "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
            "PRODUCT_ID": "501", "QUANTITY": "2.25", "PRICE": "999.99",
        }],
    )
    manifest = json.loads((cache / "private-source-manifest.json").read_text(encoding="utf-8"))
    assert manifest["ready_for_load"] is True
    assert manifest["blocked_source_groups"] == {}
    assert manifest["cache"]["bx_tasks"]["records"] == 1
    assert manifest["cache"]["bx_product_rows"]["records"] == 1

    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    first_output = capsys.readouterr().out

    from sqlalchemy import func, select

    from core.domain.models import Sku
    from modules.sales.models import Deal, DealItem, DealTask, DealTaskCrmLink

    async def snapshot():
        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            sku = (await session.execute(
                select(Sku).where(Sku.code == "SKU-1")
            )).scalar_one()
            deal = (await session.execute(
                select(Deal).where(Deal.number == "BX-30")
            )).scalar_one()
            item = (await session.execute(select(DealItem))).scalar_one()
            task = (await session.execute(
                select(DealTask).where(DealTask.source_ref == "bitrix:task:101")
            )).scalar_one()
            links = (await session.execute(
                select(DealTaskCrmLink)
                .where(DealTaskCrmLink.task_id == task.id)
                .order_by(DealTaskCrmLink.ordinal)
            )).scalars().all()
            values = (
                deal.id, sku.id, item.id, task.id,
                item.deal_id, item.sku_id, item.qty, item.unit_price, item.source_ref,
                task.deal_id, task.title, task.description,
                tuple((link.ordinal, link.raw_binding, link.entity_type, link.source_id,
                       link.deal_id) for link in links),
                await session.scalar(select(func.count()).select_from(DealItem)),
                await session.scalar(select(func.count()).select_from(DealTask)),
                await session.scalar(select(func.count()).select_from(DealTaskCrmLink)),
            )
        await db.disconnect()
        return values

    first_state = await snapshot()
    await module.load()
    second_output = capsys.readouterr().out
    second_state = await snapshot()
    assert second_state == first_state
    assert first_state[6:9] == (
        Decimal("2.25"), None, "bitrix:deal-product-row:30:61",
    )
    assert first_state[9:12] == (
        first_state[0], "Synthetic task title", "Synthetic task description",
    )
    assert first_state[12] == (
        (0, "D_30", "D", "30", first_state[0]),
        (1, "L_80", "L", "80", None),
    )
    assert first_state[13:] == (1, 1, 2)
    assert "Synthetic task title" not in first_output + second_output
    assert "Synthetic Bitrix product" not in first_output + second_output

    await module.reconcile()
    report_text = capsys.readouterr().out
    report = json.loads(report_text)
    task_gap = next(row for row in report["gaps"] if row["area"] == "bitrix_tasks")
    product_gap = next(row for row in report["gaps"] if row["area"] == "bitrix_products")
    for gap in (task_gap, product_gap):
        assert gap["status"] == "source_available"
        assert gap["source_ref_expected_keys"] == 1
        assert gap["source_ref_destination_keys"] == 1
        assert gap["source_ref_set_match"] is True
        assert gap["source_ref_semantic_match"] is True
        assert gap["blocker"] is False
    assert task_gap["source_rows"] == 1
    assert product_gap["source_rows"] == 1
    assert "Synthetic task title" not in report_text
    assert "Synthetic Bitrix product" not in report_text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("ufTaskWebdavFiles", ["n77"], "task_attachments_unimported"),
        ("ufMailMessage", {"id": "901"}, "task_mail_unimported"),
    ],
)
async def test_forged_ready_sealed_task_sidecars_fail_before_database_use(
    monkeypatch, tmp_path, field, value, blocker
):
    module = _module()
    cache = _stage_synthetic_v2_import_cache(
        tmp_path, tasks=[_bitrix_task_row(**{field: value})],
        expected_blocked={blocker: 1},
    )
    manifest_path = cache / "private-source-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["ready_for_load"] is False
    assert manifest["blocked_source_groups"]
    # Simulate an internally re-sealed manifest that tries to clear the stage blocker.
    manifest["ready_for_load"] = True
    manifest["blocked_source_groups"] = {}
    manifest_body = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, indent=2,
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_body)
    (cache / "PRIVATE_CACHE_FORMAT").write_text(
        "CRM-LIVE-001-private-cache-v2:"
        + hashlib.sha256(manifest_body).hexdigest() + "\n",
        encoding="ascii",
    )

    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    with pytest.raises(ValueError, match="BITRIX_TASK_INVALID"):
        await module.load()
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_sealed_cache_rejects_a_forged_unresolved_blocker(
    monkeypatch, tmp_path
):
    module = _module()
    cache = _stage_synthetic_v2_import_cache(
        tmp_path, tasks=[_bitrix_task_row()],
    )
    manifest_path = cache / "private-source-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["blocked_source_groups"] = {"unsupported_group": 1}
    manifest_body = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, indent=2,
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_body)
    (cache / "PRIVATE_CACHE_FORMAT").write_text(
        "CRM-LIVE-001-private-cache-v2:"
        + hashlib.sha256(manifest_body).hexdigest() + "\n",
        encoding="ascii",
    )

    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_NOT_LOADABLE"):
        await module.load()
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_sealed_v3_call_cache_is_verified_but_blocked_before_database_use(
    monkeypatch, tmp_path
):
    module = _module()
    cache = _stage_synthetic_v3_call_cache(tmp_path / "cache")
    manifest = json.loads((cache / "private-source-manifest.json").read_bytes())
    assert manifest["format"] == "CRM-LIVE-001-private-cache-v3"
    assert manifest["ready_for_load"] is False
    assert manifest["blocked_source_groups"] == {"call_recordings": 1}
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    with pytest.raises(RuntimeError, match="BITRIX_CALL_RECORDINGS_UNSUPPORTED"):
        await module.load()
    assert not db_path.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_id", "51"),
        ("call_id", "call-drift"),
        ("record_file_id", "43"),
        ("entity_type", "DEAL"),
        ("entity_id", "21"),
        ("portal_user_id", "2"),
        ("binary_key", "call:51"),
    ],
)
def test_sealed_v3_call_links_must_match_source_call_identity(
    tmp_path, field, value
):
    module = _module()
    cache = _stage_synthetic_v3_call_cache(tmp_path / "cache")
    links_path = cache / "bx_call_binary_links.jsonl"
    links = [json.loads(line) for line in links_path.read_text(encoding="utf-8").splitlines()]
    links[0][field] = value
    _write_jsonl(cache, "bx_call_binary_links", links)
    manifest = json.loads((cache / "private-source-manifest.json").read_bytes())
    _reseal_v3_manifest_for_test(cache, manifest)

    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        module._verify_private_cache(cache)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ID", "51"),
        ("CALL_ID", "call-drift"),
        ("RECORD_FILE_ID", "43"),
        ("CRM_ENTITY_TYPE", "DEAL"),
        ("CRM_ENTITY_ID", "21"),
        ("PORTAL_USER_ID", "2"),
        ("CALL_RECORD_URL", "https://example.invalid/synthetic.wav"),
    ],
)
def test_sealed_v3_source_call_identity_and_url_are_rechecked(
    tmp_path, field, value
):
    module = _module()
    cache = _stage_synthetic_v3_call_cache(tmp_path / "cache")
    calls_path = cache / "bx_calls.jsonl"
    calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
    calls[0][field] = value
    _write_jsonl(cache, "bx_calls", calls)
    manifest = json.loads((cache / "private-source-manifest.json").read_bytes())
    _reseal_v3_manifest_for_test(cache, manifest)

    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        module._verify_private_cache(cache)


def test_sealed_v3_call_identity_preserves_source_identifier_spelling(tmp_path):
    module = _module()
    cache = _stage_synthetic_v3_call_cache(tmp_path / "cache")
    calls_path = cache / "bx_calls.jsonl"
    calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
    calls[0]["RECORD_FILE_ID"] = "042"
    _write_jsonl(cache, "bx_calls", calls)
    links_path = cache / "bx_call_binary_links.jsonl"
    links = [json.loads(line) for line in links_path.read_text(encoding="utf-8").splitlines()]
    links[0]["record_file_id"] = "042"
    _write_jsonl(cache, "bx_call_binary_links", links)
    manifest = json.loads((cache / "private-source-manifest.json").read_bytes())
    _reseal_v3_manifest_for_test(cache, manifest)

    with pytest.raises(RuntimeError, match="BITRIX_CALL_RECORDINGS_UNSUPPORTED"):
        module._verify_private_cache(cache)


def test_sealed_v3_call_semantics_use_manifest_bound_jsonl_bytes(monkeypatch, tmp_path):
    module = _module()
    cache = _stage_synthetic_v3_call_cache(tmp_path / "cache")
    original = module._verify_private_call_binary_files

    def mutate_after_manifest_digest(cache_dir, manifest, snapshot):
        calls_path = cache_dir / "bx_calls.jsonl"
        calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
        calls[0]["RECORD_FILE_ID"] = "43"
        _write_jsonl(cache_dir, "bx_calls", calls)
        links_path = cache_dir / "bx_call_binary_links.jsonl"
        links = [json.loads(line) for line in links_path.read_text(encoding="utf-8").splitlines()]
        links[0]["record_file_id"] = "43"
        _write_jsonl(cache_dir, "bx_call_binary_links", links)
        return original(cache_dir, manifest, snapshot)

    monkeypatch.setattr(module, "_verify_private_call_binary_files", mutate_after_manifest_digest)
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        module._verify_private_cache(cache)


@pytest.mark.parametrize("late_file", ["binary", "root"])
def test_sealed_v3_rechecks_file_tree_after_binary_read(monkeypatch, tmp_path, late_file):
    module = _module()
    cache = _stage_synthetic_v3_call_cache(tmp_path / "cache")
    call_file = next((cache / "call_binary_files").iterdir())
    original_open = Path.open
    injected = False

    def open_with_late_file(path, *args, **kwargs):
        nonlocal injected
        if path == call_file and not injected:
            injected = True
            if late_file == "binary":
                (cache / "call_binary_files" / ("f" * 64 + ".bin")).write_bytes(b"late")
            else:
                (cache / "extra.txt").write_text("late", encoding="utf-8")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_with_late_file)
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        module._verify_private_cache(cache)
    assert injected


@pytest.mark.parametrize("tamper", ["file_bytes", "extra_file", "inventory_digest", "summary_bytes"])
def test_sealed_v3_call_binary_tree_and_summary_are_exact(tmp_path, tamper):
    module = _module()
    cache = _stage_synthetic_v3_call_cache(tmp_path / "cache")
    manifest = json.loads((cache / "private-source-manifest.json").read_bytes())
    if tamper == "file_bytes":
        call_file = next((cache / "call_binary_files").iterdir())
        call_file.write_bytes(call_file.read_bytes() + b"changed")
    elif tamper == "extra_file":
        (cache / "call_binary_files" / ("f" * 64 + ".bin")).write_bytes(b"extra")
    elif tamper == "inventory_digest":
        inventory_path = cache / "bx_call_binary_inventory.jsonl"
        inventory = [
            json.loads(line) for line in inventory_path.read_text(encoding="utf-8").splitlines()
        ]
        inventory[0]["sha256"] = "0" * 64
        _write_jsonl(cache, "bx_call_binary_inventory", inventory)
        _reseal_v3_manifest_for_test(cache, manifest)
    else:
        manifest["call_binary_files"]["bytes"] += 1
        _reseal_v3_manifest_for_test(cache, manifest)

    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        module._verify_private_cache(cache)


@pytest.mark.asyncio
async def test_forged_ready_v3_manifest_stays_blocked_before_database_use(
    monkeypatch, tmp_path
):
    module = _module()
    cache = _stage_synthetic_v3_call_cache(tmp_path / "cache")
    manifest = json.loads((cache / "private-source-manifest.json").read_bytes())
    manifest["ready_for_load"] = True
    manifest["blocked_source_groups"] = {}
    _reseal_v3_manifest_for_test(cache, manifest)

    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_NOT_LOADABLE"):
        await module.load()
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_sealed_product_rows_with_unresolved_1c_sku_fail_before_database_use(
    monkeypatch, tmp_path
):
    module = _module()
    cache = _stage_synthetic_v2_import_cache(
        tmp_path,
        product_rows=[{
            "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
            "PRODUCT_ID": "501", "QUANTITY": "2.25",
        }],
        product_xml_id="missing-1c-ref",
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    with pytest.raises(ValueError, match="BITRIX_PRODUCT_ROWS_INVALID"):
        await module.load()
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_sealed_source_drift_blocks_replay_without_mutation(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = _stage_synthetic_v2_import_cache(
        tmp_path,
        tasks=[_bitrix_task_row()],
        product_rows=[{
            "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
            "PRODUCT_ID": "501", "QUANTITY": "2.25",
        }],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    task = _bitrix_task_row(description="Changed synthetic source")
    _write_bitrix_tasks(cache, [task])
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        await module.load()

    from sqlalchemy import func, select

    from modules.sales.models import DealItem, DealTask

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        task = (await session.execute(select(DealTask))).scalar_one()
        assert task.description == "Synthetic task description"
        assert await session.scalar(select(func.count()).select_from(DealTask)) == 1
        assert await session.scalar(select(func.count()).select_from(DealItem)) == 1
    await db.disconnect()


@pytest.mark.asyncio
async def test_sealed_task_and_product_import_rolls_back_on_late_failure(
    monkeypatch, tmp_path
):
    module = _module()
    cache = _stage_synthetic_v2_import_cache(
        tmp_path,
        tasks=[_bitrix_task_row()],
        product_rows=[{
            "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
            "PRODUCT_ID": "501", "QUANTITY": "2.25",
        }],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    async def fail_late(*args, **kwargs):
        raise RuntimeError("synthetic sealed late failure")

    monkeypatch.setattr(module, "_load_sales_prices", fail_late)
    with pytest.raises(RuntimeError, match="synthetic sealed late failure"):
        await module.load()

    from sqlalchemy import func, select

    from modules.sales.models import Deal, DealItem, DealTask, DealTaskCrmLink

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        for model in (Deal, DealItem, DealTask, DealTaskCrmLink):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
    await db.disconnect()


def _stage_history_row(
    row_id: str = "101", *, stage: str = "NEW", semantic: str = "P",
    created: str = "2024-11-02T10:00:00+03:00", owner: str = "30",
    category: str = "0", type_id: str = "2",
) -> dict:
    return {
        "ID": row_id,
        "TYPE_ID": type_id,
        "OWNER_ID": owner,
        "CREATED_TIME": created,
        "CATEGORY_ID": category,
        "STAGE_SEMANTIC_ID": semantic,
        "STAGE_ID": stage,
    }


def test_category_seven_history_requires_an_explicit_mapper_branch():
    module = _module()
    prepared = module._prepare_bitrix_stage_history(
        [{"ID": "70", "CATEGORY_ID": "7"}],
        [
            _stage_history_row(
                "701", stage="C7:WON", semantic="F", owner="70", category="7"
            ),
            _stage_history_row(
                "702", stage="C7:PREPARATION", semantic="P", owner="70",
                category="7", created="2024-11-03T10:00:00+03:00",
            ),
        ],
    )
    events = sorted(prepared["events"], key=lambda row: row["row_id"])
    assert [(row["from_stage"], row["to_stage"]) for row in events] == [
        (None, "rp_won"), ("rp_won", "rp_invoice"),
    ]


@pytest.mark.parametrize(
    "stage", ["C7:NOTWON", "C7:NOINVOICE", "C7:UNKNOWN_WON_SUFFIX"]
)
def test_category_seven_substrings_are_not_treated_as_known_stages(stage):
    module = _module()
    with pytest.raises(ValueError, match="BITRIX_STAGE_HISTORY_INVALID"):
        module._prepare_bitrix_stage_history(
            [{"ID": "70", "CATEGORY_ID": "7"}],
            [_stage_history_row(
                "703", stage=stage, semantic="P", owner="70", category="7"
            )],
        )


def test_stage_history_preserves_funnel_change_and_normalizes_utc_order():
    from datetime import datetime

    module = _module()
    prepared = module._prepare_bitrix_stage_history(
        # The deal's current category may differ from an earlier stage-history row.
        [{"ID": "70", "CATEGORY_ID": "7"}],
        [
            _stage_history_row(
                "702", stage="C7:PREPARATION", semantic="P", owner="70",
                category="7", created="2024-11-02T08:30:00+00:00",
            ),
            _stage_history_row(
                "701", stage="C0:WON", semantic="F", owner="70",
                category="0", type_id="5", created="2024-11-02T10:00:00+03:00",
            ),
        ],
    )
    by_id = {row["row_id"]: row for row in prepared["events"]}
    assert by_id["701"]["changed_at"] == datetime(2024, 11, 2, 7, 0)
    assert by_id["702"]["changed_at"] == datetime(2024, 11, 2, 8, 30)
    assert (by_id["701"]["from_stage"], by_id["701"]["to_stage"]) == (None, "won")
    assert (by_id["702"]["from_stage"], by_id["702"]["to_stage"]) == (
        "won", "rp_invoice",
    )
    assert by_id["701"]["source_category_id"] == "0"
    assert by_id["701"]["source_type_id"] == 5
    assert by_id["702"]["source_category_id"] == "7"


@pytest.mark.asyncio
async def test_bitrix_stage_history_loads_two_events_and_replays_idempotently(
    monkeypatch, tmp_path, capsys
):
    from sqlalchemy import func, select

    from modules.sales.models import DealStageEvent

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    source_deal = _load_source_deal(cache)
    _write_jsonl(cache, "bx_deals", [{**source_deal, "CATEGORY_ID": "7"}])
    _write_bitrix_stage_history(cache, [
        _stage_history_row(
            "102", stage="C7:PREPARATION", semantic="P", category="7",
            created="2024-11-02T08:30:00+00:00",
        ),
        _stage_history_row(
            "101", stage="C0:WON", semantic="F", category="0", type_id="5",
            created="2024-11-02T10:00:00+03:00",
        ),
    ])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    first_output = capsys.readouterr().out
    assert "stage_event: 2" in first_output
    assert "BX-30" not in first_output

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        events = (await session.execute(
            select(DealStageEvent).order_by(DealStageEvent.id)
        )).scalars().all()
        assert [row.source_ref for row in events] == [
            "bitrix:deal-stage:30:101", "bitrix:deal-stage:30:102",
        ]
        assert [(row.from_stage, row.to_stage) for row in events] == [
            (None, "won"), ("won", "rp_invoice"),
        ]
        assert [(row.source_stage_id, row.source_type_id, row.source_semantic_id) for row in events] == [
            ("C0:WON", 5, "F"), ("C7:PREPARATION", 2, "P"),
        ]
        assert [row.source_category_id for row in events] == ["0", "7"]
        assert all(row.changed_by == "" for row in events)
        first_ids = [row.id for row in events]
        assert (await session.execute(
            select(func.count()).select_from(DealStageEvent)
        )).scalar_one() == 2
    await db.disconnect()

    await module.load()
    second_output = capsys.readouterr().out
    assert "stage_event: 0" in second_output
    assert "stage_event_existing: 2" in second_output
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        events = (await session.execute(
            select(DealStageEvent).order_by(DealStageEvent.changed_at, DealStageEvent.source_ref)
        )).scalars().all()
        assert [row.id for row in events] == first_ids
        assert (await session.execute(
            select(func.count()).select_from(DealStageEvent)
        )).scalar_one() == 2
    await db.disconnect()

    await module.reconcile()
    report_text = capsys.readouterr().out
    report = json.loads(report_text)
    history_gap = next(row for row in report["gaps"] if row["area"] == "bitrix_stage_history")
    assert history_gap["status"] == "source_available"
    assert history_gap["source_rows"] == 2
    assert history_gap["source_ref_expected_keys"] == 2
    assert history_gap["source_ref_destination_keys"] == 2
    assert history_gap["source_ref_set_match"] is True
    assert history_gap["source_ref_semantic_match"] is True
    assert history_gap["blocker"] is False
    assert "bitrix:deal-stage:" not in report_text
    assert "Test Company" not in report_text


@pytest.mark.parametrize("binary_v2", [False, True])
@pytest.mark.asyncio
async def test_missing_sealed_stage_history_after_gate_fails_before_database_open(
    monkeypatch, tmp_path, capsys, binary_v2
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    _write_bitrix_stage_history(cache, [_stage_history_row("901")])
    if binary_v2:
        _write_bitrix_timeline_comments(cache, [])
        _write_comment_binary_bundle(cache, [])
    _seal_private_cache_for_test(cache, binary_v2=binary_v2)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    verify = module._verify_private_cache

    def verify_then_remove_stage_history(cache_dir):
        snapshot = verify(cache_dir)
        if cache_dir == cache:
            (cache / "bx_stage_history.jsonl").unlink()
        return snapshot

    monkeypatch.setattr(module, "_verify_private_cache", verify_then_remove_stage_history)
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        await module.load()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_sealed_timeline_comments_use_verified_rows_after_path_disappears(
    monkeypatch, tmp_path, capsys
):
    from sqlalchemy import select

    from modules.sales import timeline_storage
    from modules.sales.models import CrmTimelineAttachment, CrmTimelineComment

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    _write_bitrix_timeline_comments(cache, [
        _timeline_comment_row(files={"901": {"id": "901"}})
    ])
    _write_comment_binary_bundle(
        cache, [("30", "77", "901", b"snapshot comment attachment", "snapshot.pdf", "application/pdf")]
    )
    _seal_private_cache_for_test(cache, binary_v2=True)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    store_root = (tmp_path / "private-attachment-store").resolve()
    monkeypatch.setattr(timeline_storage, "storage_root", lambda: store_root)
    _set_load_environment(monkeypatch, cache, db_path)

    load_jsonl = module._load_jsonl

    def read_then_remove_comments(name, cache_snapshot=None):
        rows = load_jsonl(name, cache_snapshot)
        if name == "bx_timeline_comments":
            (cache / "bx_timeline_comments.jsonl").unlink()
        return rows

    monkeypatch.setattr(module, "_load_jsonl", read_then_remove_comments)
    await module.load()
    output = capsys.readouterr().out
    assert "timeline_comment: 1" in output
    assert "timeline_attachment: 1" in output

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert len((await session.execute(
            select(CrmTimelineComment)
        )).scalars().all()) == 1
        assert len((await session.execute(
            select(CrmTimelineAttachment)
        )).scalars().all()) == 1
    await db.disconnect()


@pytest.mark.parametrize(
    "rows",
    [
        [_stage_history_row(owner="999")],
        [_stage_history_row(), _stage_history_row()],
        [_stage_history_row(stage="UNKNOWN")],
        [_stage_history_row(type_id="4")],
        [_stage_history_row(semantic="")],
        [_stage_history_row(created="not-a-date")],
        [_stage_history_row(stage="C7:WON")],
    ],
    ids=["orphan", "duplicate-id", "unknown-stage", "unknown-type", "unknown-semantic", "bad-time", "category-prefix"],
)
@pytest.mark.asyncio
async def test_invalid_bitrix_stage_history_fails_before_database_open(
    monkeypatch, tmp_path, capsys, rows
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_stage_history(cache, rows)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    with pytest.raises(ValueError, match="BITRIX_STAGE_HISTORY_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()


@pytest.mark.parametrize("created", ["2091-12-30T10:00:00", "2091-12-30"])
@pytest.mark.asyncio
async def test_stage_history_requires_explicit_timezone_before_database_open(
    monkeypatch, tmp_path, capsys, created
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_stage_history(cache, [_stage_history_row(created=created)])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    with pytest.raises(ValueError, match="BITRIX_STAGE_HISTORY_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_changed_or_removed_bitrix_stage_history_blocks_load_and_reconcile(
    monkeypatch, tmp_path, capsys
):
    from sqlalchemy import func, select

    from modules.sales.models import Deal, DealStageEvent

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_stage_history(cache, [
        _stage_history_row(stage="WON", semantic="F"),
    ])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    _write_bitrix_stage_history(cache, [
        _stage_history_row(stage="NEW", semantic="P"),
    ])
    with pytest.raises(ValueError, match="BITRIX_STAGE_HISTORY_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""

    await module.reconcile()
    changed_report_text = capsys.readouterr().out
    changed_report = json.loads(changed_report_text)
    changed_gap = next(row for row in changed_report["gaps"] if row["area"] == "bitrix_stage_history")
    assert changed_gap["status"] == "source_semantic_mismatch"
    assert changed_gap["blocker"] is True
    assert changed_gap["source_ref_set_match"] is True
    assert changed_gap["source_ref_semantic_match"] is False
    assert "bitrix:deal-stage:" not in changed_report_text

    _write_bitrix_stage_history(cache, [])
    with pytest.raises(ValueError, match="BITRIX_STAGE_HISTORY_INVALID"):
        await module.load()
    capsys.readouterr()
    await module.reconcile()
    removed_report = json.loads(capsys.readouterr().out)
    removed_gap = next(row for row in removed_report["gaps"] if row["area"] == "bitrix_stage_history")
    assert removed_gap["status"] == "source_ref_mismatch"
    assert removed_gap["source_ref_set_match"] is False
    assert removed_gap["blocker"] is True

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(Deal))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(DealStageEvent))).scalar_one() == 1
    await db.disconnect()


@pytest.mark.asyncio
async def test_invalid_stage_history_reconcile_is_aggregate_blocker(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    private_stage_id = "private-stage-id"
    _write_bitrix_stage_history(cache, [
        _stage_history_row(stage=private_stage_id),
    ])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.reconcile()
    report_text = capsys.readouterr().out
    report = json.loads(report_text)
    history_gap = next(row for row in report["gaps"] if row["area"] == "bitrix_stage_history")
    assert history_gap["status"] == "invalid_source"
    assert history_gap["blocker"] is True
    assert history_gap["source_ref_expected_keys"] is None
    assert private_stage_id not in report_text
    assert "bitrix:deal-stage:" not in report_text


@pytest.mark.parametrize("created", ["2091-12-30T10:00:00", "2091-12-30"])
@pytest.mark.asyncio
async def test_naive_stage_history_reconcile_is_aggregate_blocker_without_value(
    monkeypatch, tmp_path, capsys, created
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_stage_history(cache, [_stage_history_row(created=created)])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.reconcile()
    report_text = capsys.readouterr().out
    report = json.loads(report_text)
    history_gap = next(row for row in report["gaps"] if row["area"] == "bitrix_stage_history")
    assert history_gap["status"] == "invalid_source"
    assert history_gap["blocker"] is True
    assert history_gap["source_ref_expected_keys"] is None
    assert created not in report_text
    assert "bitrix:deal-stage:" not in report_text


@pytest.mark.asyncio
async def test_empty_stage_history_allows_unsupported_deal_and_rolls_back_late_failure(
    monkeypatch, tmp_path, capsys
):
    from sqlalchemy import func, select

    from core.domain.models import Sku
    from modules.sales.models import Deal, DealStageEvent

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    original_deal = _load_source_deal(cache)
    _write_jsonl(cache, "bx_deals", [{**original_deal, "CATEGORY_ID": "5"}])
    _write_bitrix_stage_history(cache, [])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    assert "deal: 0" in capsys.readouterr().out
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(Deal))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(DealStageEvent))).scalar_one() == 0
        sku_baseline = (await session.execute(
            select(func.count()).select_from(Sku)
        )).scalar_one()
        assert sku_baseline == 1
    await db.disconnect()

    # Restore a supported deal and force a late failure after all ordinary writes.
    _write_jsonl(cache, "bx_deals", [original_deal])
    _write_bitrix_stage_history(cache, [_stage_history_row()])
    original_import = module._import_bitrix_stage_history

    async def fail_after_stage_insert(session, prepared, stats):
        await original_import(session, prepared, stats)
        raise RuntimeError("synthetic late stage-history failure")

    monkeypatch.setattr(module, "_import_bitrix_stage_history", fail_after_stage_insert)
    with pytest.raises(RuntimeError, match="synthetic late stage-history failure"):
        await module.load()

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(Deal))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(Sku))).scalar_one() == sku_baseline
        assert (await session.execute(select(func.count()).select_from(DealStageEvent))).scalar_one() == 0
    await db.disconnect()


@pytest.mark.asyncio
async def test_bitrix_timeline_comments_load_by_entity_and_replay_without_duplicates(
    monkeypatch, tmp_path, capsys
):
    from datetime import datetime

    from sqlalchemy import select

    from modules.leads.models import Lead
    from modules.sales.models import CrmTimelineComment, Deal

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    _write_bitrix_timeline_comments(cache, [
        _timeline_comment_row(entity_type="deal", comment_id="77"),
        _timeline_comment_row(
            entity_type="lead", entity_id="40", comment_id="77",
            body="Synthetic lead timeline text",
        ),
    ])
    _seal_private_cache_for_test(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    first_output = capsys.readouterr().out
    assert "timeline_comment: 2" in first_output
    assert "Synthetic timeline text" not in first_output
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        rows = (await session.execute(
            select(CrmTimelineComment, Deal.number, Lead.message)
            .outerjoin(Deal, Deal.id == CrmTimelineComment.deal_id)
            .outerjoin(Lead, Lead.id == CrmTimelineComment.lead_id)
            .order_by(CrmTimelineComment.entity_type)
        )).all()
        assert len(rows) == 2
        first_ids = {comment.entity_type: comment.id for comment, _, _ in rows}
        by_type = {comment.entity_type: (comment, deal_number, lead_message)
                   for comment, deal_number, lead_message in rows}
        deal_comment, deal_number, _ = by_type["deal"]
        lead_comment, _, lead_message = by_type["lead"]
        assert deal_number == "BX-30"
        assert lead_message == module.LEAD_IMPORT_MARKER + "40"
        assert deal_comment.source_ref == "bitrix:timeline-comment:deal:77"
        assert lead_comment.source_ref == "bitrix:timeline-comment:lead:77"
        assert deal_comment.source_entity_id == "30"
        assert deal_comment.author_source_id == "1"
        assert deal_comment.author_display == "Test User"
        assert deal_comment.body == "Synthetic timeline text"
        assert deal_comment.created_at == datetime(2024, 11, 2, 10, 0)
    await db.disconnect()

    await module.load()
    second_output = capsys.readouterr().out
    assert "timeline_comment: 0" in second_output
    assert "timeline_comment_existing: 2" in second_output
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        rows = (await session.execute(select(CrmTimelineComment))).scalars().all()
        assert len(rows) == 2
        assert {row.entity_type: row.id for row in rows} == first_ids
    await db.disconnect()


def test_v2_private_cache_requires_loadable_exact_binary_snapshot(tmp_path):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    _write_bitrix_timeline_comments(cache, [
        _timeline_comment_row(files={"901": {"id": "901"}})
    ])
    _write_comment_binary_bundle(
        cache, [("30", "77", "901", b"synthetic bytes", "synthetic.pdf", "application/pdf")]
    )
    _seal_private_cache_for_test(
        cache, binary_v2=True, ready=False,
        blocked={"binary_cache_import_pending": 1},
    )
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_NOT_LOADABLE"):
        module._verify_private_cache(cache)

    _seal_private_cache_for_test(cache, binary_v2=True)
    (cache / "comment_binary_files" / "unexpected.bin").write_bytes(b"extra")
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        module._verify_private_cache(cache)
    (cache / "comment_binary_files" / "unexpected.bin").unlink()
    inventory = json.loads(
        (cache / "bx_comment_binary_inventory.jsonl").read_text(encoding="utf-8")
    )
    (cache / "comment_binary_files" / inventory["filename"]).write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        module._verify_private_cache(cache)
    (cache / "PRIVATE_CACHE_FORMAT").unlink()
    (cache / "private-source-manifest.json").unlink()
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_NOT_LOADABLE"):
        module._verify_private_cache(cache)


@pytest.mark.asyncio
async def test_v2_timeline_attachments_load_and_replay_with_full_owner_identity(
    monkeypatch, tmp_path, capsys
):
    from sqlalchemy import select

    from modules.sales import timeline_storage
    from modules.sales.models import CrmTimelineAttachment, CrmTimelineComment

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    _write_bitrix_timeline_comments(cache, [
        _timeline_comment_row(files={"901": {"id": "901"}}),
        _timeline_comment_row(
            entity_type="lead", entity_id="40", comment_id="77",
            body="Synthetic lead timeline text",
        ),
    ])
    content = b"private synthetic attachment bytes"
    _write_comment_binary_bundle(
        cache, [("30", "77", "901", content, "synthetic.pdf", "application/pdf")]
    )
    _seal_private_cache_for_test(cache, binary_v2=True)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    store_root = (tmp_path / "private-attachment-store").resolve()
    monkeypatch.setattr(timeline_storage, "storage_root", lambda: store_root)
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    first_output = capsys.readouterr().out
    assert "timeline_attachment: 1" in first_output
    assert "synthetic.pdf" not in first_output
    assert content.decode() not in first_output
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        comments = (await session.execute(select(CrmTimelineComment))).scalars().all()
        comments_by_ref = {row.source_ref: row for row in comments}
        attachment_rows = (await session.execute(
            select(CrmTimelineAttachment)
        )).scalars().all()
        assert len(comments) == 2
        assert len(attachment_rows) == 1
        attachment = attachment_rows[0]
        assert attachment.id is not None
        assert attachment.source_ref == "bitrix:timeline-file:deal:30:77:901"
        assert attachment.comment_id == comments_by_ref[
            "bitrix:timeline-comment:deal:77"
        ].id
        assert attachment.comment_id != comments_by_ref[
            "bitrix:timeline-comment:lead:77"
        ].id
        assert attachment.sha256 == hashlib.sha256(content).hexdigest()
        assert attachment.size_bytes == len(content)
        assert attachment.filename == "synthetic.pdf"
        assert attachment.content_type == "application/pdf"
        first_ids = (attachment.id, attachment.comment_id)
    await db.disconnect()

    await module.reconcile()
    report_output = capsys.readouterr().out
    report = json.loads(report_output)
    gap = next(row for row in report["gaps"] if row["area"] == "bitrix_timeline_attachments")
    assert gap["status"] == "source_available"
    assert gap["source_ref_expected_keys"] == 1
    assert gap["source_ref_destination_keys"] == 1
    assert gap["source_ref_set_match"] is True
    assert gap["source_ref_semantic_match"] is True
    assert gap["orphan_destination_rows"] == 0
    assert gap["blocker"] is False
    files_gap = next(row for row in report["gaps"] if row["area"] == "files")
    assert "deal-comment attachments" in files_gap["reason"]
    assert "lead/task/call/CRM-field files remain blocked" in files_gap["reason"]
    comment_gap = next(
        row for row in report["gaps"] if row["area"] == "bitrix_timeline_comments"
    )
    assert "ready-v2 deal-comment attachments are imported" in comment_gap["reason"]
    assert "synthetic.pdf" not in report_output
    assert "bitrix:timeline-file:" not in report_output

    await module.load()
    replay_output = capsys.readouterr().out
    assert "timeline_attachment: 0" in replay_output
    assert "timeline_attachment_existing: 1" in replay_output
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        attachment_rows = (await session.execute(
            select(CrmTimelineAttachment)
        )).scalars().all()
        assert len(attachment_rows) == 1
        assert (attachment_rows[0].id, attachment_rows[0].comment_id) == first_ids
    await db.disconnect()


@pytest.mark.parametrize(("binary_v2", "phase"), [
    (False, "load"), (False, "reconcile"),
    (True, "load"), (True, "reconcile"),
])
@pytest.mark.asyncio
async def test_sealed_jsonl_drift_after_gate_is_rejected_before_database_access(
    monkeypatch, tmp_path, capsys, binary_v2, phase
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    _write_bitrix_timeline_comments(cache, [
        _timeline_comment_row(body="Original synthetic body")
    ])
    if binary_v2:
        _write_comment_binary_bundle(cache, [])
    _seal_private_cache_for_test(cache, binary_v2=binary_v2)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    verify = module._verify_private_cache

    def verify_then_mutate(cache_dir):
        snapshot = verify(cache_dir)
        if cache_dir == cache:
            rows = _load_jsonl_for_test(cache, "bx_timeline_comments")
            rows[0]["COMMENT"] = "Changed after sealed-cache gate"
            _write_jsonl(cache, "bx_timeline_comments", rows)
        return snapshot

    monkeypatch.setattr(module, "_verify_private_cache", verify_then_mutate)
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        if phase == "load":
            await module.load()
        else:
            await module.reconcile()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()


@pytest.mark.parametrize("invalid_kind", ["duplicate_key", "blank_line"])
@pytest.mark.asyncio
async def test_sealed_jsonl_rejects_duplicate_keys_and_blank_lines(
    monkeypatch, tmp_path, capsys, invalid_kind
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    comment = _timeline_comment_row(body="Private synthetic body")
    _write_bitrix_timeline_comments(cache, [comment])
    if invalid_kind == "duplicate_key":
        line = json.dumps(comment, ensure_ascii=False)
        assert '"ENTITY_ID": "30"' in line
        line = line.replace(
            '"ENTITY_ID": "30"', '"ENTITY_ID": "999", "ENTITY_ID": "30"', 1
        )
        (cache / "bx_timeline_comments.jsonl").write_text(line + "\n", encoding="utf-8")
    else:
        path = cache / "bx_timeline_comments.jsonl"
        path.write_bytes(path.read_bytes() + b"\n")
    _seal_private_cache_for_test(cache)
    assert module._verify_private_cache(cache) is not None

    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        await module.load()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()

    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        await module.reconcile()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_real_offline_v2_stage_loads_directly_and_replays(
    monkeypatch, tmp_path, capsys
):
    from sqlalchemy import select

    from modules.sales import timeline_storage
    from modules.sales.models import CrmTimelineAttachment

    module = _module()
    cache = _stage_synthetic_v2_import_cache(tmp_path.resolve())
    manifest = json.loads((cache / "private-source-manifest.json").read_bytes())
    assert manifest["ready_for_load"] is True
    assert manifest["blocked_source_groups"] == {}
    module._verify_private_cache(cache)

    db_path = (tmp_path / "isolated.sqlite3").resolve()
    store_root = (tmp_path / "private-attachment-store").resolve()
    monkeypatch.setattr(timeline_storage, "storage_root", lambda: store_root)
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    first_output = capsys.readouterr().out
    assert "timeline_attachment: 1" in first_output
    await module.load()
    second_output = capsys.readouterr().out
    assert "timeline_attachment_existing: 1" in second_output
    await module.reconcile()
    report_output = capsys.readouterr().out
    report = json.loads(report_output)
    gap = next(row for row in report["gaps"] if row["area"] == "bitrix_timeline_attachments")
    assert gap["status"] == "source_available"
    assert gap["source_ref_set_match"] is True
    assert gap["source_ref_semantic_match"] is True
    assert gap["blocker"] is False
    assert "synthetic.pdf" not in report_output
    assert "bitrix:timeline-file:" not in report_output
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert len((await session.execute(
            select(CrmTimelineAttachment)
        )).scalars().all()) == 1
    await db.disconnect()


@pytest.mark.parametrize("invalid_kind", [
    "wrong_owner", "duplicate_link", "missing_link", "orphan_comment", "bad_file_id",
])
@pytest.mark.asyncio
async def test_v2_bad_comment_binary_links_fail_before_database_open(
    monkeypatch, tmp_path, capsys, invalid_kind
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    file_mapping = {"901": {"id": "901"}}
    if invalid_kind == "bad_file_id":
        file_mapping = {"902": {"id": "901"}}
    _write_bitrix_timeline_comments(cache, [
        _timeline_comment_row(files=file_mapping)
    ])
    _write_comment_binary_bundle(
        cache,
        [] if invalid_kind == "missing_link" else [
            ("30", "77", "901", b"synthetic bytes", "synthetic.pdf", "application/pdf")
        ],
    )
    if invalid_kind == "wrong_owner":
        links = _load_jsonl_for_test(cache, "bx_comment_binary_links")
        links[0]["entity_id"] = "999"
        _write_jsonl(cache, "bx_comment_binary_links", links)
    elif invalid_kind == "duplicate_link":
        links = _load_jsonl_for_test(cache, "bx_comment_binary_links")
        links.append(dict(links[0]))
        _write_jsonl(cache, "bx_comment_binary_links", links)
    elif invalid_kind == "orphan_comment":
        links = _load_jsonl_for_test(cache, "bx_comment_binary_links")
        links[0]["source_id"] = "78"
        _write_jsonl(cache, "bx_comment_binary_links", links)
    _seal_private_cache_for_test(cache, binary_v2=True)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    expected_error = (
        "BITRIX_TIMELINE_COMMENTS_INVALID"
        if invalid_kind == "bad_file_id"
        else "BITRIX_TIMELINE_ATTACHMENTS_INVALID"
    )
    with pytest.raises(ValueError, match=expected_error):
        await module.load()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(row for row in report["gaps"] if row["area"] == "bitrix_timeline_attachments")
    assert gap["status"] == "invalid_source"
    assert gap["blocker"] is True
    assert "synthetic.pdf" not in output
    assert "bitrix:timeline-file:" not in output


@pytest.mark.parametrize("drift_kind", ["removed", "changed"])
@pytest.mark.asyncio
async def test_v2_stale_or_changed_binary_blocks_load_and_reconcile_aggregately(
    monkeypatch, tmp_path, capsys, drift_kind
):
    from sqlalchemy import select

    from modules.sales import timeline_storage
    from modules.sales.models import CrmTimelineAttachment

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    original_comment = _timeline_comment_row(files={"901": {"id": "901"}})
    _write_bitrix_timeline_comments(cache, [original_comment])
    _write_comment_binary_bundle(
        cache, [("30", "77", "901", b"original bytes", "synthetic.pdf", "application/pdf")]
    )
    _seal_private_cache_for_test(cache, binary_v2=True)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    store_root = (tmp_path / "private-attachment-store").resolve()
    monkeypatch.setattr(timeline_storage, "storage_root", lambda: store_root)
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    if drift_kind == "removed":
        _write_bitrix_timeline_comments(cache, [{**original_comment, "FILES": {}}])
        _write_comment_binary_bundle(cache, [])
    else:
        _write_bitrix_timeline_comments(cache, [original_comment])
        _write_comment_binary_bundle(
            cache, [("30", "77", "901", b"changed bytes", "synthetic.pdf", "application/pdf")]
        )
    _seal_private_cache_for_test(cache, binary_v2=True)
    with pytest.raises(ValueError, match="BITRIX_TIMELINE_ATTACHMENTS_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        rows = (await session.execute(select(CrmTimelineAttachment))).scalars().all()
        assert len(rows) == 1
        assert rows[0].sha256 == hashlib.sha256(b"original bytes").hexdigest()
    await db.disconnect()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(row for row in report["gaps"] if row["area"] == "bitrix_timeline_attachments")
    if drift_kind == "removed":
        assert gap["status"] == "source_ref_mismatch"
        assert gap["source_ref_expected_keys"] == 0
        assert gap["source_ref_destination_keys"] == 1
    else:
        assert gap["status"] == "source_semantic_mismatch"
        assert gap["source_ref_expected_keys"] == 1
        assert gap["source_ref_destination_keys"] == 1
        assert gap["source_ref_set_match"] is True
        assert gap["source_ref_semantic_match"] is False
    assert gap["blocker"] is True
    assert "synthetic.pdf" not in output
    assert "bitrix:timeline-file:" not in output
    assert "original bytes" not in output
    assert "changed bytes" not in output


@pytest.mark.asyncio
async def test_orphaned_imported_attachment_blocks_load_before_new_rows_and_reconcile(
    monkeypatch, tmp_path, capsys
):
    from sqlalchemy import func, select

    from modules.leads.models import Lead
    from modules.sales import timeline_storage
    from modules.sales.models import CrmTimelineAttachment

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    _write_bitrix_timeline_comments(cache, [
        _timeline_comment_row(files={"901": {"id": "901"}})
    ])
    _write_comment_binary_bundle(
        cache, [("30", "77", "901", b"orphan audit bytes", "synthetic.pdf", "application/pdf")]
    )
    _seal_private_cache_for_test(cache, binary_v2=True)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    store_root = (tmp_path / "private-attachment-store").resolve()
    monkeypatch.setattr(timeline_storage, "storage_root", lambda: store_root)
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        attachment = (await session.execute(
            select(CrmTimelineAttachment)
        )).scalar_one()
        attachment.comment_id = 999999
        await session.commit()
    await db.disconnect()

    lead_rows = _load_jsonl_for_test(cache, "bx_leads")
    lead_rows.append({
        **lead_rows[0], "ID": "41", "TITLE": "New synthetic lead",
    })
    _write_jsonl(cache, "bx_leads", lead_rows)
    _write_bitrix_timeline_comments(cache, [
        _timeline_comment_row(files={})
    ])
    _write_comment_binary_bundle(cache, [])
    _seal_private_cache_for_test(cache, binary_v2=True)

    with pytest.raises(ValueError, match="BITRIX_TIMELINE_ATTACHMENTS_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Lead)) == 1
        assert await session.scalar(
            select(Lead.id).where(Lead.message == module.LEAD_IMPORT_MARKER + "41")
        ) is None
        assert await session.scalar(
            select(func.count()).select_from(CrmTimelineAttachment)
        ) == 1
    await db.disconnect()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(row for row in report["gaps"] if row["area"] == "bitrix_timeline_attachments")
    assert gap["status"] == "destination_orphan"
    assert gap["orphan_destination_rows"] == 1
    assert gap["source_ref_expected_keys"] == 0
    assert gap["source_ref_destination_keys"] == 1
    assert gap["blocker"] is True
    assert "synthetic.pdf" not in output
    assert "bitrix:timeline-file:" not in output


@pytest.mark.asyncio
async def test_late_v2_attachment_failure_rolls_back_rows_and_leaves_only_blob(
    monkeypatch, tmp_path, capsys
):
    from sqlalchemy import func, select

    from core.domain.models import Sku
    from modules.leads.models import Lead
    from modules.sales import timeline_storage
    from modules.sales.models import CrmTimelineAttachment, CrmTimelineComment, Deal

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    content = b"rollback attachment bytes"
    _write_bitrix_timeline_comments(cache, [
        _timeline_comment_row(files={"901": {"id": "901"}})
    ])
    _write_comment_binary_bundle(
        cache, [("30", "77", "901", content, "synthetic.pdf", "application/pdf")]
    )
    _seal_private_cache_for_test(cache, binary_v2=True)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    store_root = (tmp_path / "private-attachment-store").resolve()
    monkeypatch.setattr(timeline_storage, "storage_root", lambda: store_root)
    _set_load_environment(monkeypatch, cache, db_path)
    original_import = module._import_bitrix_timeline_attachments

    async def fail_after_attachment_insert(session, prepared, stored, stats):
        await original_import(session, prepared, stored, stats)
        raise RuntimeError("synthetic late binary import failure")

    monkeypatch.setattr(
        module, "_import_bitrix_timeline_attachments", fail_after_attachment_insert
    )
    with pytest.raises(RuntimeError, match="synthetic late binary import failure"):
        await module.load()
    assert capsys.readouterr().out == ""

    digest = hashlib.sha256(content).hexdigest()
    assert (store_root / digest[:2] / digest[2:4] / digest).read_bytes() == content
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        for model in (CrmTimelineAttachment, CrmTimelineComment, Deal, Lead, Sku):
            assert (await session.execute(
                select(func.count()).select_from(model)
            )).scalar_one() == 0
    await db.disconnect()


@pytest.mark.asyncio
async def test_category_change_to_unsupported_keeps_stale_comment_in_audit_scope(
    monkeypatch, tmp_path, capsys
):
    from sqlalchemy import select

    from modules.leads.models import Lead
    from modules.sales.models import CrmTimelineComment, Deal

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "bx_deals", [{**_load_source_deal(cache), "ID": "70"}])
    source_lead = _load_jsonl_for_test(cache, "bx_leads")[0]
    _write_jsonl(cache, "bx_leads", [{**source_lead, "ID": "80"}])
    _write_bitrix_product_sources(cache, [], deal_id="70")
    deal_comment = _timeline_comment_row(entity_id="70", comment_id="77")
    lead_comment = _timeline_comment_row(
        entity_type="lead", entity_id="80", comment_id="77",
        body="Synthetic surviving lead comment",
    )
    _write_bitrix_timeline_comments(cache, [deal_comment, lead_comment])
    _seal_private_cache_for_test(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()
    await module.load()
    capsys.readouterr()

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        rows = (await session.execute(
            select(CrmTimelineComment).order_by(CrmTimelineComment.source_ref)
        )).scalars().all()
        assert len(rows) == 2
        before = {
            row.source_ref: (row.id, row.entity_type, row.source_entity_id, row.body)
            for row in rows
        }
        assert set(before) == {
            "bitrix:timeline-comment:deal:77",
            "bitrix:timeline-comment:lead:77",
        }
        assert (await session.scalar(
            select(Deal.id).where(Deal.number == "BX-70")
        )) is not None
        assert (await session.scalar(
            select(Lead.id).where(Lead.message == module.LEAD_IMPORT_MARKER + "80")
        )) is not None
    await db.disconnect()

    _write_jsonl(cache, "bx_deals", [{
        **_load_source_deal(cache), "ID": "70", "CATEGORY_ID": "5",
    }])
    _write_bitrix_product_sources(cache, [], deal_id="70")
    _write_bitrix_timeline_comments(cache, [lead_comment])
    _seal_private_cache_for_test(cache)
    with pytest.raises(ValueError, match="BITRIX_TIMELINE_COMMENTS_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        rows = (await session.execute(
            select(CrmTimelineComment).order_by(CrmTimelineComment.source_ref)
        )).scalars().all()
        after = {
            row.source_ref: (row.id, row.entity_type, row.source_entity_id, row.body)
            for row in rows
        }
        assert after == before
    await db.disconnect()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(row for row in report["gaps"] if row["area"] == "bitrix_timeline_comments")
    assert gap["status"] == "source_ref_mismatch"
    assert gap["source_ref_expected_keys"] == 1
    assert gap["source_ref_destination_keys"] == 2
    assert gap["source_ref_set_match"] is False
    assert gap["blocker"] is True
    assert "Synthetic surviving lead comment" not in output
    assert "bitrix:timeline-comment:" not in output


@pytest.mark.asyncio
async def test_new_unsupported_category_without_comments_is_not_blocked(
    monkeypatch, tmp_path, capsys
):
    from sqlalchemy import select

    from modules.sales.models import CrmTimelineComment, Deal

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "bx_deals", [{
        **_load_source_deal(cache), "ID": "70", "CATEGORY_ID": "5",
    }])
    _write_bitrix_product_sources(cache, [], deal_id="70")
    _write_bitrix_timeline_comments(cache, [])
    _seal_private_cache_for_test(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    assert "deal: 0" in capsys.readouterr().out
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert await session.scalar(
            select(CrmTimelineComment.id)
        ) is None
        assert await session.scalar(
            select(Deal.id).where(Deal.number == "BX-70")
        ) is None
    await db.disconnect()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(row for row in report["gaps"] if row["area"] == "bitrix_timeline_comments")
    assert gap["status"] == "source_available"
    assert gap["source_ref_set_match"] is True
    assert gap["blocker"] is False


@pytest.mark.parametrize("invalid_kind", [
    "orphan_owner", "naive_created", "duplicate_identity", "files_list",
    "missing_files", "unsupported_deal_owner",
])
@pytest.mark.asyncio
async def test_invalid_bitrix_timeline_comments_fail_before_database_open(
    monkeypatch, tmp_path, capsys, invalid_kind
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    row = _timeline_comment_row(body="Private synthetic comment")
    rows = [row]
    if invalid_kind == "orphan_owner":
        rows[0] = {**row, "ENTITY_ID": "999"}
    elif invalid_kind == "naive_created":
        rows[0] = {**row, "CREATED": "2024-11-02T13:00:00"}
    elif invalid_kind == "duplicate_identity":
        rows.append(dict(row))
    elif invalid_kind == "files_list":
        rows[0] = {**row, "FILES": []}
    elif invalid_kind == "missing_files":
        rows[0] = {key: value for key, value in row.items() if key != "FILES"}
    else:
        _write_jsonl(cache, "bx_deals", [{
            **_load_source_deal(cache), "CATEGORY_ID": "5",
        }])
    _write_bitrix_timeline_comments(cache, rows)
    _seal_private_cache_for_test(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    with pytest.raises(ValueError, match="BITRIX_TIMELINE_COMMENTS_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_changed_timeline_comment_source_blocks_load_and_reconcile_without_values(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    original = _timeline_comment_row(body="Private original comment text")
    _write_bitrix_timeline_comments(cache, [original])
    _seal_private_cache_for_test(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()
    changed = {**original, "COMMENT": "Private changed comment text"}
    _write_bitrix_timeline_comments(cache, [changed])
    _seal_private_cache_for_test(cache)
    with pytest.raises(ValueError, match="BITRIX_TIMELINE_COMMENTS_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(row for row in report["gaps"] if row["area"] == "bitrix_timeline_comments")
    assert gap["status"] == "source_semantic_mismatch"
    assert gap["source_ref_set_match"] is True
    assert gap["source_ref_semantic_match"] is False
    assert gap["blocker"] is True
    assert "Private original comment text" not in output
    assert "Private changed comment text" not in output
    assert "bitrix:timeline-comment:" not in output

    changed_id = {**original, "ID": "78"}
    _write_bitrix_timeline_comments(cache, [changed_id])
    _seal_private_cache_for_test(cache)
    with pytest.raises(ValueError, match="BITRIX_TIMELINE_COMMENTS_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""
    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(row for row in report["gaps"] if row["area"] == "bitrix_timeline_comments")
    assert gap["status"] == "source_ref_mismatch"
    assert gap["source_ref_expected_keys"] == 1
    assert gap["source_ref_destination_keys"] == 1
    assert gap["source_ref_set_match"] is False
    assert gap["blocker"] is True
    assert "Private original comment text" not in output
    assert "bitrix:timeline-comment:" not in output


@pytest.mark.asyncio
async def test_invalid_timeline_comment_reconcile_is_aggregate_blocker_without_values(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    bad_created = "2024-11-02T13:00:00"
    _write_bitrix_timeline_comments(cache, [
        _timeline_comment_row(created=bad_created, body="Private malformed comment")
    ])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(row for row in report["gaps"] if row["area"] == "bitrix_timeline_comments")
    assert gap["status"] == "invalid_source"
    assert gap["blocker"] is True
    assert gap["source_ref_expected_keys"] is None
    assert bad_created not in output
    assert "Private malformed comment" not in output
    assert "bitrix:timeline-comment:" not in output


@pytest.mark.asyncio
async def test_late_timeline_comment_failure_rolls_back_imported_owner_rows(
    monkeypatch, tmp_path, capsys
):
    from sqlalchemy import func, select

    from core.domain.models import Sku
    from modules.leads.models import Lead
    from modules.sales.models import CrmTimelineComment, Deal

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    _write_bitrix_timeline_comments(cache, [_timeline_comment_row()])
    _seal_private_cache_for_test(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    original_import = module._import_bitrix_timeline_comments

    async def fail_after_comment_insert(session, prepared, stats):
        await original_import(session, prepared, stats)
        raise RuntimeError("synthetic late timeline-comment failure")

    monkeypatch.setattr(
        module, "_import_bitrix_timeline_comments", fail_after_comment_insert
    )
    with pytest.raises(RuntimeError, match="synthetic late timeline-comment failure"):
        await module.load()

    assert capsys.readouterr().out == ""
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        for model in (CrmTimelineComment, Deal, Lead, Sku):
            assert (await session.execute(
                select(func.count()).select_from(model)
            )).scalar_one() == 0
    await db.disconnect()


@pytest.mark.parametrize("loader", ["load", "load_onec"])
@pytest.mark.asyncio
async def test_global_duplicate_active_onec_code_fails_before_database_open(
    monkeypatch, tmp_path, capsys, loader
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "onec_sku", [
        {"Ref_Key": "private-ref-a", "Code": "PRIVATE-DUPLICATE-CODE"},
        {"Ref_Key": "private-ref-b", "Code": "PRIVATE-DUPLICATE-CODE"},
    ])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    monkeypatch.setattr(
        module, "_isolated_database", lambda: pytest.fail("database opened before catalog preflight")
    )

    with pytest.raises(ValueError, match="ONEC_SKU_IDENTITY_INVALID"):
        await getattr(module, loader)()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_deleted_and_active_rows_may_share_code_but_only_active_identity_is_imported(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "onec_sku", [
        {"Ref_Key": "private-deleted-ref", "Code": "PRIVATE-SHARED-CODE", "DeletionMark": " TRUE "},
        {"Ref_Key": "private-active-ref", "Code": "PRIVATE-SHARED-CODE", "DeletionMark": "false"},
    ])
    _write_jsonl(cache, "onec_sales", [])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load_onec()
    first_output = capsys.readouterr().out
    await module.load_onec()
    second_output = capsys.readouterr().out

    from sqlalchemy import func, select

    from core.domain.models import Sku

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        rows = (await session.execute(select(Sku))).scalars().all()
        assert len(rows) == 1
        sku = rows[0]
        expected_digest = hashlib.sha256(b"private-active-ref").hexdigest()
        assert sku.code == "PRIVATE-SHARED-CODE"
        assert sku.is_active is True
        assert sku.provenance["onec_identity"] == {
            "source": "1c", "ref_key_sha256": expected_digest,
        }
        assert "private-active-ref" not in json.dumps(sku.provenance)
        assert "private-deleted-ref" not in json.dumps(sku.provenance)
        assert (await session.execute(select(func.count()).select_from(Sku))).scalar_one() == 1
    await db.disconnect()
    assert "sku: 1" in first_output
    assert "sku: 0" in second_output
    assert "PRIVATE-SHARED-CODE" not in first_output + second_output


@pytest.mark.asyncio
async def test_deleted_onec_ref_cannot_resolve_bitrix_product_xml_id(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [{
        "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
        "PRODUCT_ID": "501", "QUANTITY": "1",
    }], onec_sku_rows=[{
        "Ref_Key": "sku-1", "Code": "SKU-1", "DeletionMark": True,
    }])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    with pytest.raises(ValueError, match="BITRIX_PRODUCT_ROWS_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()


@pytest.mark.parametrize("loader", ["load", "load_onec"])
@pytest.mark.parametrize("deletion_mark", ["yes", 0.0, {"unknown": True}])
@pytest.mark.asyncio
async def test_unknown_onec_deletion_mark_fails_before_database_open(
    monkeypatch, tmp_path, capsys, loader, deletion_mark
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "onec_sku", [{
        "Ref_Key": "private-ref", "Code": "PRIVATE-CODE", "DeletionMark": deletion_mark,
    }])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    monkeypatch.setattr(
        module, "_isolated_database", lambda: pytest.fail("database opened before catalog preflight")
    )

    with pytest.raises(ValueError, match="ONEC_SKU_IDENTITY_INVALID"):
        await getattr(module, loader)()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()


@pytest.mark.parametrize("loader", ["load", "load_onec"])
@pytest.mark.parametrize("legacy_provenance", [False, True])
@pytest.mark.asyncio
async def test_manual_or_legacy_sku_code_collision_is_not_adopted(
    monkeypatch, tmp_path, capsys, loader, legacy_provenance
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    from sqlalchemy import select

    from core.domain.models import Sku
    from modules.leads.models import Lead
    from modules.sales.models import Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        provenance = (
            {"title": {"source": "1c", "at": "legacy"}}
            if legacy_provenance else {"title": {"source": "manual"}}
        )
        session.add(Sku(code="SKU-1", title="Manual protected SKU", provenance=provenance))
        await session.commit()
    await db.disconnect()

    with pytest.raises(ValueError, match="ONEC_SKU_IDENTITY_CONFLICT"):
        await getattr(module, loader)()
    assert capsys.readouterr().out == ""
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        sku = (await session.execute(select(Sku))).scalar_one()
        assert sku.title == "Manual protected SKU"
        assert "onec_identity" not in (sku.provenance or {})
        assert await session.scalar(select(Lead.id)) is None
        assert await session.scalar(select(Deal.id)) is None
    await db.disconnect()


@pytest.mark.asyncio
async def test_onec_sku_identity_repeat_is_idempotent_and_ref_change_fails_closed(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "onec_sales", [])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load_onec()
    first_output = capsys.readouterr().out
    await module.load_onec()
    second_output = capsys.readouterr().out
    from sqlalchemy import select

    from core.domain.models import Sku

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        first = (await session.execute(select(Sku))).scalar_one()
        first_id = first.id
        first_digest = first.provenance["onec_identity"]["ref_key_sha256"]
    await db.disconnect()
    assert "sku: 1" in first_output
    assert "sku: 0" in second_output

    _write_jsonl(cache, "onec_sku", [{
        "Ref_Key": "changed-private-ref", "Code": "SKU-1", "Description": "Test SKU",
    }])
    with pytest.raises(ValueError, match="ONEC_SKU_IDENTITY_CONFLICT"):
        await module.load_onec()
    assert capsys.readouterr().out == ""
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        current = (await session.execute(select(Sku))).scalar_one()
        assert current.id == first_id
        assert current.provenance["onec_identity"]["ref_key_sha256"] == first_digest
        assert first_digest == hashlib.sha256(b"sku-1").hexdigest()
    await db.disconnect()


@pytest.mark.parametrize(
    "blocker", ["duplicate_code", "unknown_mark", "missing_identity", "unknown_destination"]
)
@pytest.mark.asyncio
async def test_onec_sku_reconcile_reports_aggregate_identity_blockers_without_source_keys(
    monkeypatch, tmp_path, capsys, blocker
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    if blocker == "duplicate_code":
        _write_jsonl(cache, "onec_sku", [
            {"Ref_Key": "private-ref-a", "Code": "PRIVATE-CODE"},
            {"Ref_Key": "private-ref-b", "Code": "PRIVATE-CODE"},
        ])
    elif blocker == "unknown_mark":
        _write_jsonl(cache, "onec_sku", [{
            "Ref_Key": "private-ref", "Code": "PRIVATE-CODE", "DeletionMark": "unknown",
        }])
    else:
        _write_jsonl(cache, "onec_sku", [{
            "Ref_Key": "private-ref", "Code": "PRIVATE-CODE", "Description": "Private title",
        }])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    if blocker in {"missing_identity", "unknown_destination"}:
        from core.domain.models import Sku

        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            provenance = (
                {"onec_identity": {"source": "1c", "ref_key_sha256": "f" * 64}}
                if blocker == "unknown_destination" else {}
            )
            session.add(Sku(code="PRIVATE-CODE", title="Legacy SKU", provenance=provenance))
            await session.commit()
        await db.disconnect()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    sku_gap = next(row for row in report["gaps"] if row["area"] == "onec_sku_identity")
    assert sku_gap["blocker"] is True
    assert sku_gap["status"] == "identity_mismatch"
    assert "PRIVATE-CODE" not in output
    assert "private-ref" not in output
    if blocker == "duplicate_code":
        assert sku_gap["duplicate_active_code_groups"] == 1
    elif blocker == "unknown_mark":
        assert sku_gap["unknown_deletion_mark_rows"] == 1
    elif blocker == "unknown_destination":
        assert sku_gap["destination_unknown_identity_rows"] == 1
        assert sku_gap["destination_identity_conflicts"] == 1
    else:
        assert sku_gap["destination_missing_identity_rows"] == 1
        assert sku_gap["destination_missing_source_rows"] == 1


@pytest.mark.parametrize(
    "invalid_case",
    [
        "noncanonical_row_id", "duplicate_row_id", "wrong_owner", "wrong_deal",
        "zero_quantity", "excess_scale", "quantity_overflow", "unsupported_category",
        "unknown_product", "name_only_match", "duplicate_linked_code",
        "duplicate_catalog_id",
    ],
)
@pytest.mark.asyncio
async def test_invalid_bitrix_product_rows_fail_before_database_mutation(
    monkeypatch, tmp_path, capsys, invalid_case
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    row = {
        "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
        "PRODUCT_ID": "501", "QUANTITY": "2.25",
    }
    rows = [row]
    product_id = "501"
    xml_id = "sku-1"
    sku_rows = [{"Ref_Key": "sku-1", "Code": "SKU-1", "Description": "Test SKU"}]
    if invalid_case == "noncanonical_row_id":
        row["ID"] = "061"
    elif invalid_case == "duplicate_row_id":
        rows.append({**row, "PRODUCT_ID": "502"})
    elif invalid_case == "wrong_owner":
        row["OWNER_ID"] = "31"
    elif invalid_case == "wrong_deal":
        _write_jsonl(cache, "bx_deals", [{**_load_source_deal(cache), "ID": "31"}])
    elif invalid_case == "zero_quantity":
        row["QUANTITY"] = "0"
    elif invalid_case == "excess_scale":
        row["QUANTITY"] = "1.001"
    elif invalid_case == "quantity_overflow":
        row["QUANTITY"] = "1000000000000.00"
    elif invalid_case == "unsupported_category":
        _write_jsonl(cache, "bx_deals", [{**_load_source_deal(cache), "CATEGORY_ID": "5"}])
    elif invalid_case == "unknown_product":
        row["PRODUCT_ID"] = "502"
    elif invalid_case == "name_only_match":
        xml_id = "missing-ref"
    elif invalid_case == "duplicate_linked_code":
        sku_rows.append({"Ref_Key": "sku-2", "Code": "SKU-1", "Description": "Other"})

    _write_bitrix_product_sources(
        cache, rows, product_id=product_id, xml_id=xml_id, onec_sku_rows=sku_rows
    )
    if invalid_case == "duplicate_catalog_id":
        _write_jsonl(cache, "bx_products", [
            {"ID": "501", "XML_ID": "sku-1", "CODE": "BX-A", "NAME": "A"},
            {"ID": "501", "XML_ID": "sku-1", "CODE": "BX-B", "NAME": "B"},
        ])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    expected_error = (
        "ONEC_SKU_IDENTITY_INVALID"
        if invalid_case == "duplicate_linked_code"
        else "BITRIX_PRODUCT_ROWS_INVALID"
    )
    with pytest.raises(ValueError, match=expected_error):
        await module.load()
    output = capsys.readouterr().out
    assert "Test SKU" not in output
    assert not db_path.exists()


def _load_source_deal(cache: Path) -> dict:
    return json.loads((cache / "bx_deals.jsonl").read_text(encoding="utf-8").splitlines()[0])


def test_sealed_bitrix_product_rows_require_canonical_complete_deal_envelopes():
    module = _module()
    deals = [{"ID": "30", "CATEGORY_ID": "0"}]
    with pytest.raises(ValueError, match="BITRIX_PRODUCT_ROWS_INVALID"):
        module._prepare_bitrix_deal_items(deals, [], [], [], require_complete=True)
    with pytest.raises(ValueError, match="BITRIX_PRODUCT_ROWS_INVALID"):
        module._prepare_bitrix_deal_items(
            deals, [{"deal_id": "030", "rows": []}], [], [], require_complete=True
        )
    prepared = module._prepare_bitrix_deal_items(
        deals, [{"deal_id": "30", "rows": []}], [], [], require_complete=True
    )
    assert prepared == {
        "deal_ids": {"30"}, "scope_deal_ids": {"30"}, "items": [],
    }


@pytest.mark.asyncio
async def test_legacy_product_row_file_requires_complete_deal_envelopes(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "bx_product_rows", [])
    _write_jsonl(cache, "bx_products", [])
    assert not (cache / "private-source-manifest.json").exists()
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    with pytest.raises(ValueError, match="BITRIX_PRODUCT_ROWS_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_unsupported_empty_product_envelope_is_complete_but_out_of_import_scope(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "bx_deals", [{
        **_load_source_deal(cache), "CATEGORY_ID": "5",
    }])
    _write_bitrix_product_sources(cache, [])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    output = capsys.readouterr().out
    assert "deal_item: 0" in output

    from sqlalchemy import select

    from modules.sales.models import Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert await session.scalar(
            select(Deal.id).where(Deal.number == "BX-30")
        ) is None
    await db.disconnect()


@pytest.mark.asyncio
async def test_sealed_unsupported_transition_with_stale_row_blocks_before_writes_and_reconciles(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    original_row = {
        "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
        "PRODUCT_ID": "501", "QUANTITY": "2.25",
    }
    _write_bitrix_product_sources(cache, [original_row])
    _seal_private_cache_for_test(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from modules.leads.models import Lead
    from modules.sales.models import Deal, DealItem

    async def counts():
        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            values = []
            for model in (Lead, Deal, DealItem):
                values.append(
                    (await session.execute(
                        select(func.count()).select_from(model)
                    )).scalar_one()
                )
            result = tuple(values)
        await db.disconnect()
        return result

    before = await counts()
    _write_jsonl(cache, "bx_deals", [{
        **_load_source_deal(cache), "CATEGORY_ID": "5",
    }])
    _write_bitrix_product_sources(cache, [])
    _write_jsonl(cache, "bx_leads", [
        *_load_jsonl_for_test(cache, "bx_leads"),
        {"ID": "41", "TITLE": "Synthetic transition lead", "STATUS_ID": "NEW",
         "SOURCE_ID": "WEB", "ASSIGNED_BY_ID": "1", "DATE_CREATE": "2024-11-03T10:00:00"},
    ])
    _seal_private_cache_for_test(cache)

    with pytest.raises(ValueError, match="BITRIX_PRODUCT_ROWS_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""
    assert await counts() == before
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert await session.scalar(
            select(func.count()).select_from(Lead).where(
                Lead.message == module.LEAD_IMPORT_MARKER + "41"
            )
        ) == 0
    await db.disconnect()

    await module.reconcile()
    report_output = capsys.readouterr().out
    report = json.loads(report_output)
    product_gap = next(row for row in report["gaps"] if row["area"] == "bitrix_products")
    assert product_gap["source_rows"] == 0
    assert product_gap["destination_total_imported_rows"] == 1
    assert product_gap["source_ref_expected_keys"] == 0
    assert product_gap["source_ref_destination_keys"] == 1
    assert product_gap["source_ref_set_match"] is False
    assert product_gap["blocker"] is True
    assert "bitrix:deal-product-row:30:61" not in report_output


@pytest.mark.asyncio
async def test_product_reconcile_blocks_equal_counts_with_different_source_keys(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    source_row = {
        "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
        "PRODUCT_ID": "501", "QUANTITY": "2.25",
    }
    _write_bitrix_product_sources(cache, [source_row])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    _write_bitrix_product_sources(cache, [{**source_row, "ID": "62"}])
    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    product_gap = next(row for row in report["gaps"] if row["area"] == "bitrix_products")
    assert product_gap["source_ref_expected_keys"] == 1
    assert product_gap["source_ref_destination_keys"] == 1
    assert product_gap["source_ref_set_match"] is False
    assert product_gap["source_ref_semantic_match"] is False
    assert product_gap["status"] == "source_ref_mismatch"
    assert product_gap["blocker"] is True
    assert "bitrix:deal-product-row:30:61" not in output
    assert "bitrix:deal-product-row:30:62" not in output


@pytest.mark.parametrize("drift", ["qty", "sku_id", "deal_id", "unit_price"])
@pytest.mark.asyncio
async def test_product_reconcile_blocks_semantic_drift_with_same_source_keys(
    monkeypatch, tmp_path, capsys, drift
):
    from decimal import Decimal

    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    source_deal = _load_source_deal(cache)
    _write_jsonl(cache, "bx_deals", [
        source_deal,
        {**source_deal, "ID": "31", "TITLE": "Synthetic second deal", "STAGE_ID": "NEW"},
    ])
    source_row = {
        "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
        "PRODUCT_ID": "501", "QUANTITY": "2.25",
    }
    _write_bitrix_product_sources(cache, [source_row])
    _write_jsonl(cache, "bx_product_rows", [
        {"deal_id": "30", "rows": [source_row]},
        {"deal_id": "31", "rows": []},
    ])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from core.domain.models import Sku
    from modules.sales.models import Deal, DealItem

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        item = (await session.execute(select(DealItem))).scalar_one()
        if drift == "qty":
            item.qty = Decimal("3.25")
        elif drift == "sku_id":
            drift_sku = Sku(code="SKU-DRIFT", title="Synthetic drift SKU")
            session.add(drift_sku)
            await session.flush()
            item.sku_id = drift_sku.id
        elif drift == "deal_id":
            second_deal = (await session.execute(
                select(Deal).where(Deal.number == "BX-31")
            )).scalar_one()
            item.deal_id = second_deal.id
        else:
            item.unit_price = Decimal("1.00")
        await session.commit()
        assert (await session.execute(select(func.count()).select_from(DealItem))).scalar_one() == 1
        assert (await session.execute(select(DealItem.source_ref))).scalar_one() == (
            "bitrix:deal-product-row:30:61"
        )
    await db.disconnect()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    product_gap = next(row for row in report["gaps"] if row["area"] == "bitrix_products")
    assert product_gap["source_ref_expected_keys"] == 1
    assert product_gap["source_ref_destination_keys"] == 1
    assert product_gap["source_ref_set_match"] is True
    assert product_gap["source_ref_semantic_match"] is False
    assert product_gap["source_ref_semantic_mismatches"] == 1
    assert product_gap["status"] == "source_semantic_mismatch"
    assert product_gap["blocker"] is True
    assert "bitrix:deal-product-row:30:61" not in output


@pytest.mark.parametrize(
    "issue", ["owner_id", "missing_xml_id", "invalid_quantity", "product_and_sku_invalid"]
)
@pytest.mark.asyncio
async def test_invalid_product_source_is_a_reported_blocker_after_successful_load(
    monkeypatch, tmp_path, capsys, issue
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    source_row = {
        "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
        "PRODUCT_ID": "501", "QUANTITY": "2.25",
    }
    _write_bitrix_product_sources(cache, [source_row])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    if issue in {"owner_id", "product_and_sku_invalid"}:
        changed_row = {**source_row, "OWNER_ID": "31"}
        _write_bitrix_product_sources(cache, [changed_row])
    elif issue == "invalid_quantity":
        changed_row = {**source_row, "QUANTITY": "not-a-quantity"}
        _write_bitrix_product_sources(cache, [changed_row])
    else:
        _write_bitrix_product_sources(cache, [source_row])
        product = _load_jsonl_for_test(cache, "bx_products")[0]
        product.pop("XML_ID")
        _write_jsonl(cache, "bx_products", [product])

    if issue == "product_and_sku_invalid":
        _write_jsonl(cache, "onec_sku", [
            {"Ref_Key": "private-ref-a", "Code": "PRIVATE-DUPLICATE-CODE"},
            {"Ref_Key": "private-ref-b", "Code": "PRIVATE-DUPLICATE-CODE"},
        ])

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    product_gap = next(row for row in report["gaps"] if row["area"] == "bitrix_products")
    sku_gap = next(row for row in report["gaps"] if row["area"] == "onec_sku_identity")
    assert product_gap["status"] == "invalid_source"
    assert product_gap["blocker"] is True
    assert product_gap["source_ref_expected_keys"] is None
    assert sku_gap["blocker"] is (issue == "product_and_sku_invalid")
    assert "PRIVATE-DUPLICATE-CODE" not in output
    assert "private-ref-a" not in output
    assert "BITRIX_PRODUCT_ROWS_INVALID" not in output


def test_unrelated_duplicate_1c_code_blocks_catalog_before_product_mapping():
    module = _module()
    with pytest.raises(ValueError, match="BITRIX_PRODUCT_ROWS_INVALID"):
        module._prepare_bitrix_deal_items(
            [{"ID": "30", "CATEGORY_ID": "0"}],
            [{"deal_id": "30", "rows": [{
                "ID": "61", "PRODUCT_ID": "501", "QUANTITY": "1",
            }]}],
            [{"ID": "501", "XML_ID": "sku-1", "CODE": "B-1", "NAME": "Product"}],
            [
                {"Ref_Key": "sku-1", "Code": "SKU-1"},
                {"Ref_Key": "sku-2", "Code": "DUPLICATE"},
                {"Ref_Key": "sku-3", "Code": "DUPLICATE"},
            ],
        )


@pytest.mark.parametrize("change", ["quantity", "removed"])
@pytest.mark.asyncio
async def test_changed_or_removed_bitrix_product_source_fails_and_rolls_back(
    monkeypatch, tmp_path, capsys, change
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    original_row = {
        "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
        "PRODUCT_ID": "501", "QUANTITY": "2.25",
    }
    _write_bitrix_product_sources(cache, [original_row])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    _write_jsonl(cache, "bx_leads", [
        *_load_jsonl_for_test(cache, "bx_leads"),
        {"ID": "41", "TITLE": "New synthetic lead", "STATUS_ID": "NEW",
         "SOURCE_ID": "WEB", "ASSIGNED_BY_ID": "1", "DATE_CREATE": "2024-11-03T10:00:00"},
    ])
    if change == "quantity":
        changed_rows = [{**original_row, "QUANTITY": "3.25"}]
    else:
        changed_rows = []
    _write_bitrix_product_sources(cache, changed_rows)

    from sqlalchemy import func, select

    from modules.leads.models import Lead
    from modules.sales.models import DealItem

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        before = (
            (await session.execute(select(func.count()).select_from(Lead))).scalar_one(),
            (await session.execute(select(func.count()).select_from(DealItem))).scalar_one(),
            (await session.execute(select(DealItem.qty))).scalar_one(),
        )
    await db.disconnect()

    with pytest.raises(ValueError, match="BITRIX_PRODUCT_ROWS_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        after = (
            (await session.execute(select(func.count()).select_from(Lead))).scalar_one(),
            (await session.execute(select(func.count()).select_from(DealItem))).scalar_one(),
            (await session.execute(select(DealItem.qty))).scalar_one(),
        )
        assert await session.scalar(
            select(func.count()).select_from(Lead).where(
                Lead.message == module.LEAD_IMPORT_MARKER + "41"
            )
        ) == 0
    await db.disconnect()
    assert after == before


def _load_jsonl_for_test(cache: Path, name: str) -> list[dict]:
    path = cache / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@pytest.mark.asyncio
async def test_manual_line_conflict_rolls_back_other_imported_rows(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_product_sources(cache, [])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    from decimal import Decimal

    from sqlalchemy import func, select

    from core.domain.models import Sku
    from modules.leads.models import Lead
    from modules.sales.models import Deal, DealItem

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        sku = (await session.execute(select(Sku).where(Sku.code == "SKU-1"))).scalar_one()
        manual_item = DealItem(
            deal_id=deal.id, sku_id=sku.id, qty=Decimal("4.00"), source_ref=None,
        )
        session.add(manual_item)
        await session.commit()
        manual_id = manual_item.id
        before = (
            (await session.execute(select(func.count()).select_from(Lead))).scalar_one(),
            (await session.execute(select(func.count()).select_from(DealItem))).scalar_one(),
        )
    await db.disconnect()

    _write_jsonl(cache, "bx_leads", [
        *_load_jsonl_for_test(cache, "bx_leads"),
        {"ID": "41", "TITLE": "New synthetic lead", "STATUS_ID": "NEW",
         "SOURCE_ID": "WEB", "ASSIGNED_BY_ID": "1", "DATE_CREATE": "2024-11-03T10:00:00"},
    ])
    _write_bitrix_product_sources(cache, [{
        "ID": "61", "OWNER_ID": "30", "OWNER_TYPE": "D",
        "PRODUCT_ID": "501", "QUANTITY": "2.25",
    }])
    with pytest.raises(ValueError, match="BITRIX_PRODUCT_ROWS_INVALID"):
        await module.load()
    assert capsys.readouterr().out == ""

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        after = (
            (await session.execute(select(func.count()).select_from(Lead))).scalar_one(),
            (await session.execute(select(func.count()).select_from(DealItem))).scalar_one(),
        )
        manual = (await session.execute(select(DealItem))).scalar_one()
        assert manual.id == manual_id
        assert (manual.source_ref, manual.qty, manual.unit_price) == (None, Decimal("4.00"), None)
        assert await session.scalar(
            select(func.count()).select_from(Lead).where(
                Lead.message == module.LEAD_IMPORT_MARKER + "41"
            )
        ) == 0
    await db.disconnect()
    assert after == before


def test_import_module_does_not_load_connector_config(monkeypatch):
    sys.modules.pop("connectors.config", None)
    module = _module()
    assert "connectors.config" not in sys.modules
    assert callable(module._connector_config)


def test_extract_requests_only_minimal_company_identity(tmp_path, monkeypatch, capsys):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    monkeypatch.setattr(module, "OUT_DIR", module.OUT_DIR)
    monkeypatch.setattr(module, "_resolve_cache_dir", lambda: cache)
    calls = []

    def fake_bx_list(method, params):
        calls.append((method, params))
        if method == "crm.deal.list":
            return [{"ID": "30", "COMPANY_ID": "10", "CONTACT_ID": "20"}]
        if method == "crm.contact.list":
            return [{"ID": "20", "NAME": "Synthetic Contact", "COMPANY_ID": "10"}]
        if method == "crm.requisite.list":
            return [{"ENTITY_ID": "10", "RQ_INN": "100000002"}]
        if method == "crm.company.list":
            return [{"ID": "10", "TITLE": "Synthetic Company Name"}]
        return []

    monkeypatch.setattr(module, "bx_list", fake_bx_list)
    monkeypatch.setattr(module, "bx", lambda method, params=None: {"result": []})
    monkeypatch.setattr(module, "extract_onec", lambda: None)

    module.extract()
    output = capsys.readouterr().out

    company_calls = [params for method, params in calls if method == "crm.company.list"]
    assert company_calls == [{"filter": {"@ID": ["10"]}, "select": ["ID", "TITLE"]}]
    assert any(method == "crm.requisite.list" for method, _ in calls)
    assert json.loads((cache / "bx_companies.jsonl").read_text(encoding="utf-8")) == {
        "ID": "10", "TITLE": "Synthetic Company Name"
    }
    assert "Synthetic Contact" not in output
    assert "Synthetic Company Name" not in output


def test_company_name_evidence_requires_one_normalized_1c_reference():
    module = _module()
    unique, statuses = module._company_1c_evidence(
        [{"ID": "10", "TITLE": "  Example   COMPANY "}],
        [],
        [{"Ref_Key": "ref-a", "Description": "Example Company", "ИНН": "100000002"}],
        referenced_company_ids=["10"],
    )
    assert unique["10"] == {
        "unp": "100000002",
        "ref": "ref-a",
        "name": "Example Company",
        "match_method": "name",
    }
    assert statuses["10"] == "matched"

    ambiguous, ambiguous_statuses = module._company_1c_evidence(
        [{"ID": "10", "TITLE": "Example Company"}],
        [],
        [
            {"Ref_Key": "ref-a", "Description": "Example Company"},
            {"Ref_Key": "ref-b", "Description": " example  company "},
        ],
        referenced_company_ids=["10"],
    )
    assert ambiguous == {}
    assert ambiguous_statuses["10"] == "ambiguous_1c_name_match"

    invalid_unp_fallback, invalid_unp_statuses = module._company_1c_evidence(
        [{"ID": "10", "TITLE": "Example Company"}],
        [{"ENTITY_ID": "10", "RQ_INN": "invalid"}],
        [{"Ref_Key": "ref-a", "Description": "Example Company", "ИНН": "100000002"}],
        referenced_company_ids=["10"],
    )
    assert invalid_unp_fallback == {}
    assert invalid_unp_statuses["10"] == "invalid_company_unp"

    unmatched_unp_fallback, unmatched_unp_statuses = module._company_1c_evidence(
        [{"ID": "10", "TITLE": "Example Company"}],
        [{"ENTITY_ID": "10", "RQ_INN": "100000003"}],
        [{"Ref_Key": "ref-a", "Description": "Example Company", "ИНН": "100000002"}],
        referenced_company_ids=["10"],
    )
    assert unmatched_unp_fallback == {}
    assert unmatched_unp_statuses["10"] == "no_1c_unp_match"

    absent, absent_statuses = module._company_1c_evidence(
        [{"ID": "10", "TITLE": "  "}],
        [],
        [{"Ref_Key": "ref-a", "Description": "Example Company"}],
        referenced_company_ids=["10"],
    )
    assert absent == {}
    assert absent_statuses["10"] == "missing_company_name"

    active, active_statuses = module._company_1c_evidence(
        [{"ID": "10", "TITLE": "Example Company"}],
        [],
        [
            {"Ref_Key": "deleted-ref", "Description": "Example Company",
             "DeletionMark": True},
            {"Ref_Key": "active-ref", "Description": "Example Company",
             "DeletionMark": False},
        ],
        referenced_company_ids=["10"],
    )
    assert active["10"]["ref"] == "active-ref"
    assert active_statuses["10"] == "matched"

    deleted_only, deleted_statuses = module._company_1c_evidence(
        [{"ID": "10", "TITLE": "Example Company"}],
        [],
        [{"Ref_Key": "deleted-ref", "Description": "Example Company",
          "DeletionMark": "true"}],
        referenced_company_ids=["10"],
    )
    assert deleted_only == {}
    assert deleted_statuses["10"] == "no_1c_name_match"


def test_private_source_cache_refuses_partial_or_changed_inputs(tmp_path):
    module = _module()
    cache = tmp_path.resolve() / "cache"
    cache.mkdir()
    (cache / "PRIVATE_CACHE_INCOMPLETE").touch()
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_INCOMPLETE"):
        module._verify_private_cache(cache)
    (cache / "PRIVATE_CACHE_INCOMPLETE").unlink()

    names = {"bx_deals", "bx_contacts", "bx_leads", "bx_calls", "bx_users",
             "bx_companies", "bx_requisites", "onec_counterparties", "onec_sku",
             "bx_product_rows", "bx_products", "bx_stage_history", "bx_timeline_comments"}
    entries = {}
    for name in names:
        data = b'{"ID":"1"}\n'
        (cache / f"{name}.jsonl").write_bytes(data)
        entries[name] = {"records": 1, "bytes": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()}
    manifest = {"format": "CRM-LIVE-001-private-cache-v1", "cache": entries,
                "ready_for_load": False, "blocked_source_groups": {"deal_product_rows": 1}}
    def write_manifest():
        body = json.dumps(manifest).encode("utf-8")
        (cache / "private-source-manifest.json").write_bytes(body)
        (cache / "PRIVATE_CACHE_FORMAT").write_text(
            "CRM-LIVE-001-private-cache-v1:" + hashlib.sha256(body).hexdigest() + "\n",
            encoding="ascii")
    write_manifest()
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_NOT_LOADABLE"):
        module._verify_private_cache(cache)

    manifest["ready_for_load"] = True
    manifest["blocked_source_groups"] = {}
    write_manifest()
    module._verify_private_cache(cache)
    (cache / "private-source-manifest.json").write_text(
        json.dumps({**manifest, "ready_for_load": False}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        module._verify_private_cache(cache)
    write_manifest()
    (cache / "bx_deals.jsonl").write_bytes(b'{"ID":"2"}\n')
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        module._verify_private_cache(cache)
    (cache / "private-source-manifest.json").unlink()
    with pytest.raises(RuntimeError, match="PRIVATE_CACHE_CHANGED"):
        module._verify_private_cache(cache)


def test_duplicate_source_deal_filter_skips_identical_and_conflicting_ids():
    module = _module()
    unique, identical_duplicates, conflicting_ids, missing_ids = module._deduplicate_source_deals(
        [
            {"ID": "10", "TITLE": "Synthetic stable"},
            {"ID": "10", "TITLE": "Synthetic stable"},
            {"ID": "20", "TITLE": "Synthetic first copy"},
            {"ID": "20", "TITLE": "Synthetic conflicting copy"},
            {"TITLE": "Synthetic missing ID"},
        ]
    )
    assert unique == [{"ID": "10", "TITLE": "Synthetic stable"}]
    assert identical_duplicates == 1
    assert conflicting_ids == 1
    assert missing_ids == 1


@pytest.mark.asyncio
async def test_unique_company_name_link_is_stable_across_repeated_loads(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "bx_companies", [{"ID": "10", "TITLE": " test 1C company "}])
    _write_jsonl(cache, "bx_requisites", [])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()
    client_ids, contact_id, _deal_id = await _seed_existing_deal_directory(module)
    await module.load()
    capsys.readouterr()
    await module.reconcile()
    first = json.loads(capsys.readouterr().out)
    await module.load()
    capsys.readouterr()
    await module.reconcile()
    second = json.loads(capsys.readouterr().out)

    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyAlias
    from modules.sales.models import Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        master = (await session.execute(select(Counterparty))).scalar_one()
        alias = (
            await session.execute(
                select(CounterpartyAlias).where(
                    CounterpartyAlias.source == "bitrix",
                    CounterpartyAlias.external_ref == "company:10",
                )
            )
        ).scalar_one()
        assert master.name == "Test 1C Company"
        assert deal.crm_client_id == client_ids[0]
        assert deal.crm_contact_id == contact_id
        assert alias.counterparty_id == master.id
    await db.disconnect()

    assert first["source"]["company_1c_mapping"]["matched_by_unique_name"] == 1
    assert first["destination"]["crm_directory_links"] == second["destination"][
        "crm_directory_links"
    ]
    assert first["destination"]["crm_directory_links"]["client_links_verified"] == 1
    assert first["destination"]["crm_directory_links"]["contact_links_verified"] == 1


@pytest.mark.asyncio
async def test_unique_name_fallback_links_duplicate_unp_ref_without_claiming_unp(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    rows = [
        {"Ref_Key": "ref-a", "Description": "Alpha", "ИНН": "111111111"},
        {"Ref_Key": "ref-z", "Description": "Zeta", "ИНН": "111111111"},
    ]
    _make_counterparty_cache(
        cache,
        [{"ID": "bx-z", "TITLE": "Zeta"}],
        [],
        rows,
    )
    _write_jsonl(
        cache,
        "bx_deals",
        [{"ID": "deal-z", "TITLE": "Synthetic deal", "STAGE_ID": "NEW",
          "CATEGORY_ID": "0", "COMPANY_ID": "bx-z", "OPPORTUNITY": "1"}],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyAlias

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        aliases = (await session.execute(select(CounterpartyAlias))).scalars().all()
        masters = (await session.execute(select(Counterparty))).scalars().all()
        refs = {
            row.external_ref: row.counterparty_id
            for row in aliases if row.source == "1c"
        }
        bitrix_alias = next(
            row for row in aliases
            if row.source == "bitrix" and row.external_ref == "company:bx-z"
        )
        assert bitrix_alias.counterparty_id == refs["ref-z"]
        assert refs["ref-a"] != refs["ref-z"]
        assert {row.id: (row.name, row.unp) for row in masters} == {
            refs["ref-a"]: ("Alpha", "111111111"),
            refs["ref-z"]: ("Zeta", None),
        }
    await db.disconnect()

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    assert report["source"]["company_1c_mapping"]["matched_by_unique_name"] == 1
    assert report["destination"]["alias_audit"]["unp_conflict_refs"] == 0
    assert report["destination"]["alias_audit"]["allowed_unp_omission_refs"] == 1
    fidelity = report["destination"]["fidelity"]["bitrix_companies"]
    assert fidelity["classification"]["status"] == "requires_review"
    assert fidelity["classification"]["requires_review"]["fields"] == {
        "changed_unp": 1
    }

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        master = await session.get(Counterparty, refs["ref-z"])
        master.unp = "222222222"
        await session.commit()
    await db.disconnect()

    await module.reconcile()
    drift_report = json.loads(capsys.readouterr().out)
    assert drift_report["destination"]["alias_audit"]["unp_conflict_refs"] == 1
    assert drift_report["destination"]["alias_audit"]["allowed_unp_omission_refs"] == 0
    assert drift_report["destination"]["crm_directory_links"]["client_outcomes"] == {
        "counterparty_conflicting_1c_master": 1
    }


def test_load_path_does_not_construct_settings_or_connectors(tmp_path):
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    probe = """
import asyncio
import importlib
import dotenv
import requests
from config.settings import Settings

def forbidden(*args, **kwargs):
    raise AssertionError("forbidden load-only side effect")

Settings.__init__ = forbidden
dotenv.load_dotenv = forbidden
requests.sessions.Session.request = forbidden
module = importlib.import_module("scripts.import_month")
asyncio.run(module.load())
"""
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "AIOS_ENVIRONMENT": "dev",
            "AIOS_DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}",
            "IMPORT_CACHE_DIR": str(cache),
            "IMPORT_FROM": "2024-11-01T00:00:00",
            "IMPORT_TO": "2024-12-01T00:00:00",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Test Company" not in result.stdout


def test_all_preflights_load_guard_before_extraction(tmp_path):
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    probe = """
import requests
import runpy
import sys

def forbidden(*args, **kwargs):
    raise AssertionError("network extraction started before load preflight")

requests.sessions.Session.request = forbidden
sys.argv = ["scripts/import_month.py", "all"]
runpy.run_path("scripts/import_month.py", run_name="__main__")
"""
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "AIOS_ENVIRONMENT": "dev",
            "AIOS_DATABASE_URL": "",
            "IMPORT_CACHE_DIR": str(cache),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "AIOS_DATABASE_URL" in result.stderr
    assert "network extraction started" not in result.stderr


def test_load_guard_requires_explicit_isolated_inputs(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(tmp_path.resolve()))
    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    monkeypatch.delenv("AIOS_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="AIOS_DATABASE_URL"):
        module._require_isolated_load()

    monkeypatch.setenv("AIOS_DATABASE_URL", "postgresql+psycopg://example")
    with pytest.raises(RuntimeError, match="sqlite"):
        module._require_isolated_load()

    monkeypatch.setenv("AIOS_DATABASE_URL", "sqlite+aiosqlite:///relative.db")
    with pytest.raises(RuntimeError, match="абсолютный"):
        module._require_isolated_load()


@pytest.mark.asyncio
async def test_cached_load_twice_is_idempotent_and_reconciles_without_network(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(cache.resolve()))
    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: pytest.fail("network"))
    monkeypatch.setattr(module._onec, "get", lambda *args, **kwargs: pytest.fail("network"))

    await module.load()
    capsys.readouterr()
    await module.reconcile()
    first = json.loads(capsys.readouterr().out)

    await module.load()
    capsys.readouterr()
    await module.reconcile()
    second_text = capsys.readouterr().out
    second = json.loads(second_text)

    assert first == second
    assert first["destination"]["fidelity"]["bitrix_deals"]["match"] is True
    assert first["destination"]["load_counts"]["bitrix_deals"] == {
        "source_supported_rows": 1,
        "destination_rows": 1,
    }
    assert first["destination"]["load_counts"]["bitrix_contacts"] == {
        "source_rows": 1,
        "expected_import_rows": 1,
        "destination_rows": 1,
        "deduplicated_source_rows": 0,
    }
    assert first["source"]["products"]["onec_item_refs_missing_sku"] == 0
    assert first["source"]["financial"]["import_contract"] == (
        "pending_receivable_requires_reconciliation"
    )
    assert first["destination"]["financial"]["pending_receivable_rows"] == 1
    assert first["destination"]["financial"]["paid_rows"] == 0
    assert first["destination"]["counts"]["stage_events"] == 0
    assert "Test Company" not in second_text

    from decimal import Decimal

    from sqlalchemy import select

    from modules.sales.models import Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        original_amount = deal.amount
        original_counterparty = deal.counterparty
        deal.amount = Decimal("999.00")
        await session.commit()
    await db.disconnect()
    await module.reconcile()
    amount_mutation = json.loads(capsys.readouterr().out)
    assert amount_mutation["destination"]["semantic"]["bitrix_deals"]["digest"] != first[
        "destination"
    ]["semantic"]["bitrix_deals"]["digest"]
    assert amount_mutation["destination"]["fidelity"]["bitrix_deals"]["match"] is False

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        deal.amount = original_amount
        await session.commit()
    await db.disconnect()
    await module.reconcile()
    restored = json.loads(capsys.readouterr().out)
    assert restored["destination"]["semantic"]["bitrix_deals"] == first["destination"]["semantic"]["bitrix_deals"]

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        deal.counterparty = "Synthetic broken link"
        await session.commit()
    await db.disconnect()
    await module.reconcile()
    link_mutation = json.loads(capsys.readouterr().out)
    assert link_mutation["destination"]["semantic"]["bitrix_deals"]["digest"] != first[
        "destination"
    ]["semantic"]["bitrix_deals"]["digest"]
    assert link_mutation["destination"]["fidelity"]["bitrix_deals"]["match"] is False
    assert original_counterparty == "Test 1C Company"


@pytest.mark.asyncio
async def test_identical_duplicate_deals_are_skipped_and_reported_idempotently(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    deal_rows = [
        json.loads(line)
        for line in (cache / "bx_deals.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    _write_jsonl(cache, "bx_deals", deal_rows + [dict(deal_rows[0])])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    first_load_output = capsys.readouterr().out
    await module.load()
    second_load_output = capsys.readouterr().out
    await module.reconcile()
    report = json.loads(capsys.readouterr().out)

    from sqlalchemy import func, select

    from modules.sales.models import Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(Deal))).scalar_one() == 1
    await db.disconnect()

    assert "duplicate_source_deals: 1" in first_load_output
    assert "duplicate_source_deals: 1" in second_load_output
    assert report["source"]["deduplication"]["bitrix_deals"][
        "identical_duplicate_rows"
    ] == 1
    assert report["destination"]["fidelity"]["bitrix_deals"]["classification"][
        "status"
    ] == "requires_review"


def test_cli_failure_diagnostic_never_exposes_sql_parameters(monkeypatch, capsys):
    module = _module()
    from sqlalchemy.exc import IntegrityError

    unsafe_value = "Synthetic private deal title"
    failure = IntegrityError(
        "INSERT INTO sales.deal (title) VALUES (?)",
        {"title": unsafe_value},
        RuntimeError(unsafe_value),
    )

    async def fail_load():
        raise failure

    monkeypatch.setattr(module, "sys", sys)
    monkeypatch.setattr(sys, "argv", ["import_month.py", "load"])
    monkeypatch.setattr(module.os, "chdir", lambda _path: None)
    monkeypatch.setattr(module, "_require_isolated_load", lambda: None)
    monkeypatch.setattr(module, "load", fail_load)

    with pytest.raises(SystemExit) as exit_info:
        module._run_cli()

    assert exit_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "import: failed; code=DB_INTEGRITY\n"
    assert unsafe_value not in output.err


@pytest.mark.asyncio
async def test_deal_company_resolves_from_1c_without_bitrix_company_cards(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "bx_companies", [])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()
    await module.reconcile()
    report = json.loads(capsys.readouterr().out)

    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyAlias
    from modules.sales.models import Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        master = (await session.execute(select(Counterparty))).scalar_one()
        alias = (
            await session.execute(
                select(CounterpartyAlias).where(
                    CounterpartyAlias.source == "bitrix",
                    CounterpartyAlias.external_ref == "company:10",
                )
            )
        ).scalar_one()
        assert deal.counterparty == "Test 1C Company"
        assert master.name == "Test 1C Company"
        assert alias.counterparty_id == master.id
    await db.disconnect()

    assert report["source"]["company_1c_mapping"]["company_references"] == 1
    assert report["source"]["company_1c_mapping"]["matched_by_unique_unp"] == 1
    assert report["source"]["links"]["deals_to_companies"]["distinct_missing"] == 0
    assert report["destination"]["fidelity"]["bitrix_companies"]["match"] is True
    assert report["destination"]["load_counts"]["bitrix_companies"] == {
        "source_rows": 0,
        "referenced_company_ids": 1,
        "destination_alias_rows": 1,
    }


@pytest.mark.asyncio
async def test_existing_bitrix_deal_gets_verified_directory_links_without_overwrite(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    # First pass creates the pilot BX deal and the canonical 1C counterparty.
    await module.load()
    capsys.readouterr()
    client_ids, contact_id, deal_id = await _seed_existing_deal_directory(module)

    # Subsequent passes only enrich the missing stable directory references.
    await module.load()
    capsys.readouterr()
    await module.reconcile()
    first_report = json.loads(capsys.readouterr().out)
    summary = first_report["destination"]["crm_directory_links"]
    assert summary["client_links_verified"] == 1
    assert summary["contact_links_verified"] == 1

    await module.load()
    capsys.readouterr()
    await module.reconcile()
    second_report = json.loads(capsys.readouterr().out)
    assert second_report["destination"]["crm_directory_links"] == summary

    from decimal import Decimal

    from sqlalchemy import func, select

    from core.domain.models import Counterparty, CounterpartyAlias
    from core.services.crm_access import CrmAccess
    from modules.sales.crm_client_lookup import SalesCrmClientLookup
    from modules.sales.models import CrmClient, CrmClientContact, Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()
        assert deal.crm_client_id == client_ids[0]
        assert deal.crm_contact_id == contact_id
        assert deal.title == "Manually maintained title"
        assert deal.counterparty == "Manually maintained display name"
        assert deal.amount == Decimal("77.50")
        assert deal.stage == "negotiation"
        assert deal.next_step == "Keep this manual next step"
        resolved = await SalesCrmClientLookup().resolve_link(
            session,
            actor=CrmAccess("own", 901),
            client_id=deal.crm_client_id,
            contact_id=deal.crm_contact_id,
            expected_owner_id=deal.owner_id,
        )
        assert resolved.contact_id == contact_id
        assert (await session.execute(select(func.count()).select_from(Deal))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(CrmClient))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(CrmClientContact))).scalar_one() == 1
        master = (await session.execute(select(Counterparty))).scalar_one()
        assert master.name == "Test 1C Company"
        assert master.name != "Test Company"
        alias = (
            await session.execute(
                select(CounterpartyAlias).where(
                    CounterpartyAlias.source == "bitrix",
                    CounterpartyAlias.external_ref == "company:10",
                )
            )
        ).scalar_one()
        assert alias.counterparty_id == master.id
    await db.disconnect()


@pytest.mark.asyncio
async def test_ambiguous_crm_client_match_stays_unlinked_and_is_reconciled(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()
    await _seed_existing_deal_directory(module, duplicate_clients=True)
    await module.load()
    capsys.readouterr()
    await module.reconcile()
    report = json.loads(capsys.readouterr().out)

    from sqlalchemy import select

    from modules.sales.models import Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.number == "BX-30"))).scalar_one()
        assert deal.crm_client_id is None
        assert deal.crm_contact_id is None
    await db.disconnect()
    outcomes = report["destination"]["crm_directory_links"]["client_outcomes"]
    assert outcomes["client_ambiguous"] == 1
    assert report["destination"]["crm_directory_links"]["client_links_verified"] == 0


@pytest.mark.asyncio
async def test_existing_conflicting_crm_link_is_preserved_and_reconciled(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()
    client_ids, _contact_id, deal_id = await _seed_existing_deal_directory(
        module, preexisting_conflicting_link=True
    )
    await module.load()
    capsys.readouterr()
    await module.reconcile()
    report = json.loads(capsys.readouterr().out)

    from sqlalchemy import select

    from modules.sales.models import Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()
        assert deal.crm_client_id == client_ids[1]
        assert deal.crm_contact_id is None
    await db.disconnect()
    summary = report["destination"]["crm_directory_links"]
    assert summary["existing_client_link_conflicts"] == 1
    assert summary["contact_links_verified"] == 0


@pytest.mark.asyncio
async def test_existing_foreign_contact_without_client_is_held_and_reported(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()
    _expected_client_ids, _contact_id, deal_id = await _seed_existing_deal_directory(module)

    from sqlalchemy import select

    from modules.sales.models import CrmClient, CrmClientContact, Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        foreign_client = CrmClient(
            name="Synthetic foreign client",
            name_key="synthetic foreign client",
            unp=None,
            owner_id=901,
            counterparty_id=None,
            request_key="synthetic-foreign-client",
            request_hash="c" * 64,
            created_by="synthetic test",
        )
        session.add(foreign_client)
        await session.flush()
        foreign_contact = CrmClientContact(
            crm_client_id=foreign_client.id,
            full_name="Synthetic foreign contact",
            phone="+375291111111",
            email="foreign@example.invalid",
            contact_key="synthetic-foreign-contact",
            request_key="synthetic-foreign-contact-request",
            request_hash="d" * 64,
        )
        session.add(foreign_contact)
        deal = (await session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()
        deal.crm_client_id = None
        deal.crm_contact_id = foreign_contact.id
        await session.commit()
        foreign_contact_id = foreign_contact.id
    await db.disconnect()

    await module.load()
    capsys.readouterr()
    await module.reconcile()
    report = json.loads(capsys.readouterr().out)

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()
        assert deal.crm_client_id is None
        assert deal.crm_contact_id == foreign_contact_id
    await db.disconnect()

    summary = report["destination"]["crm_directory_links"]
    assert summary["existing_contact_pair_conflicts"] == 1
    assert summary["existing_contact_pair_outcomes"] == {
        "existing_contact_client_mismatch": 1
    }
    assert summary["client_links_verified"] == 0


@pytest.mark.asyncio
async def test_semantic_value_and_link_mutations_require_review(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = tmp_path / "cache"
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(cache.resolve()))
    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from core.domain.models import Contact, Counterparty, CounterpartyAlias
    from modules.sales.models import CallLog, Deal

    async def mutate_and_check(model, where, field, value, entity):
        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            row = (await session.execute(select(model).where(where))).scalar_one()
            original = getattr(row, field)
            setattr(row, field, value)
            await session.commit()
        await db.disconnect()

        await module.reconcile()
        report = json.loads(capsys.readouterr().out)
        fidelity = report["destination"]["fidelity"][entity]
        assert fidelity["match"] is False
        assert fidelity["classification"]["status"] == "requires_review"
        assert fidelity["classification"]["allowed_changes"]["rows"] == 0
        assert fidelity["classification"]["requires_review"]["rows"] > 0
        assert fidelity["classification"]["conflicts"]["rows"] > 0

        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            row = (await session.execute(select(model).where(where))).scalar_one()
            setattr(row, field, original)
            await session.commit()
        await db.disconnect()
        await module.reconcile()
        capsys.readouterr()

    await mutate_and_check(
        Counterparty,
        Counterparty.id == (
            select(CounterpartyAlias.counterparty_id)
            .where(
                CounterpartyAlias.source == "bitrix",
                CounterpartyAlias.external_ref == "company:10",
            )
            .scalar_subquery()
        ),
        "name",
        "Wrong company name",
        "bitrix_companies",
    )
    await mutate_and_check(
        Counterparty,
        Counterparty.id == (
            select(CounterpartyAlias.counterparty_id)
            .where(
                CounterpartyAlias.source == "bitrix",
                CounterpartyAlias.external_ref == "company:10",
            )
            .scalar_subquery()
        ),
        "unp",
        "999999999",
        "bitrix_companies",
    )
    await mutate_and_check(
        Contact,
        Contact.full_name == "Test Contact",
        "counterparty_id",
        None,
        "bitrix_contacts",
    )
    await mutate_and_check(
        Deal,
        Deal.number == "BX-30",
        "counterparty",
        "Wrong deal link",
        "bitrix_deals",
    )
    await mutate_and_check(
        CallLog,
        CallLog.call_id == "50",
        "contact_id",
        None,
        "bitrix_calls",
    )


def _set_call_primary_deal(cache: Path, deal_id: str = "30") -> None:
    calls = [json.loads(line) for line in (cache / "bx_calls.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    calls[0] = {
        **calls[0],
        "CRM_ENTITY_TYPE": "DEAL",
        "CRM_ENTITY_ID": deal_id,
    }
    _write_jsonl(cache, "bx_calls", calls)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("CALL_RECORD_URL", "https://example.invalid/synthetic.wav"),
        ("RECORD_FILE_ID", "51"),
    ],
)
@pytest.mark.asyncio
async def test_resealed_call_recording_fails_before_database_writes(
    monkeypatch, tmp_path, field, value
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _set_call_primary_deal(cache)
    calls = [json.loads(line) for line in (cache / "bx_calls.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    calls[0][field] = value
    _write_jsonl(cache, "bx_calls", calls)
    _seal_private_cache_for_test(cache, ready=True)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    with pytest.raises(ValueError, match="BITRIX_CALL_RECORDINGS_UNSUPPORTED"):
        await module.load()
    assert not db_path.exists()
    assert module._source_reconciliation()["call_deal_links"]["invalid_source"] is True


@pytest.mark.parametrize(
    "identity_changes",
    [
        [{"CALL_ID": "x" * 65}],
        [{"CALL_ID": "x" * 64 + "a"}, {"ID": "51", "CALL_ID": "x" * 64 + "b"}],
        [{"CALL_ID": "same"}, {"ID": "51", "CALL_ID": "same"}],
        [{"CALL_ID": ""}, {"ID": "51", "CALL_ID": "50"}],
        [{"CALL_ID": ["synthetic"]}],
        [{"CALL_ID": True}],
        [{"CALL_ID": "  "}],
        [{"CALL_ID": " padded "}],
        [{"ID": "", "CALL_ID": ""}],
        [{"ID": None, "CALL_ID": None}],
        [{"ID": "050", "CALL_ID": ""}],
    ],
    ids=[
        "overlong-single", "overlong-alias", "duplicate-explicit",
        "fallback-collision", "list", "bool", "whitespace", "padded",
        "empty-both", "missing-both", "noncanonical-fallback",
    ],
)
@pytest.mark.asyncio
async def test_invalid_bitrix_call_identity_fails_before_database_writes(
    monkeypatch, tmp_path, identity_changes
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    calls = [json.loads(line) for line in (cache / "bx_calls.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    calls[0] = {**calls[0], **identity_changes[0]}
    if len(identity_changes) > 1:
        calls.append({**calls[0], **identity_changes[1]})
    _write_jsonl(cache, "bx_calls", calls)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    with pytest.raises(ValueError, match="BITRIX_CALL_ID_INVALID"):
        await module.load()
    assert not db_path.exists()
    source = module._source_reconciliation()
    assert source["call_deal_links"]["invalid_source"] is True


@pytest.mark.asyncio
async def test_bitrix_deal_call_import_is_idempotent_and_reconciled(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _set_call_primary_deal(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: pytest.fail("network"))

    await module.load()
    capsys.readouterr()
    await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from modules.sales.models import CallLog, Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        call = (await session.execute(
            select(CallLog).where(CallLog.call_id == "50")
        )).scalar_one()
        deal = (await session.execute(
            select(Deal).where(Deal.number == "BX-30")
        )).scalar_one()
        assert call.deal_id == deal.id
        assert await session.scalar(select(func.count()).select_from(CallLog)) == 1
        assert await session.scalar(select(func.count()).select_from(Deal)) == 1
    await db.disconnect()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    call_link_gap = next(
        gap for gap in report["gaps"] if gap["area"] == "bitrix_call_deal_links"
    )
    assert call_link_gap["blocker"] is False
    assert call_link_gap["status"] == "source_available"
    assert call_link_gap["source_ref_semantic_match"] is True
    assert report["destination"]["fidelity"]["bitrix_calls"]["match"] is True
    assert "BX-30" not in output


@pytest.mark.parametrize(
    ("call_deal_id", "deal_category"),
    [("0", "0"), ("999", "0"), ("30", "5")],
)
@pytest.mark.asyncio
async def test_invalid_bitrix_call_deal_target_fails_before_database_writes(
    monkeypatch, tmp_path, call_deal_id, deal_category
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _set_call_primary_deal(cache, call_deal_id)
    deals = [json.loads(line) for line in (cache / "bx_deals.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    deals[0] = {**deals[0], "CATEGORY_ID": deal_category}
    _write_jsonl(cache, "bx_deals", deals)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    with pytest.raises(ValueError, match="BITRIX_CALL_DEAL_INVALID"):
        await module.load()
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_existing_bitrix_call_semantic_change_blocks_replay_without_mutation(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _set_call_primary_deal(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    calls = [json.loads(line) for line in (cache / "bx_calls.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    calls[0] = {**calls[0], "PHONE_NUMBER": "+375291234567"}
    _write_jsonl(cache, "bx_calls", calls)
    with pytest.raises(ValueError, match="BITRIX_CALL_CONFLICT"):
        await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from modules.sales.models import CallLog, Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        call = (await session.execute(
            select(CallLog).where(CallLog.call_id == "50")
        )).scalar_one()
        deal = (await session.execute(
            select(Deal).where(Deal.number == "BX-30")
        )).scalar_one()
        assert call.phone_e164 is None
        assert call.deal_id == deal.id
        assert await session.scalar(select(func.count()).select_from(CallLog)) == 1
        assert await session.scalar(select(func.count()).select_from(Deal)) == 1
    await db.disconnect()


@pytest.mark.asyncio
async def test_bitrix_call_deal_destination_drift_is_reconcile_blocker(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _set_call_primary_deal(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from modules.sales.models import CallLog

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        call = (await session.execute(
            select(CallLog).where(CallLog.call_id == "50")
        )).scalar_one()
        call.deal_id = None
        await session.commit()
    await db.disconnect()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    call_link_gap = next(
        gap for gap in report["gaps"] if gap["area"] == "bitrix_call_deal_links"
    )
    assert call_link_gap["blocker"] is True
    assert call_link_gap["status"] == "source_semantic_mismatch"
    assert call_link_gap["source_ref_semantic_match"] is False
    assert report["destination"]["fidelity"]["bitrix_calls"]["match"] is False
    assert "BX-30" not in output


@pytest.mark.parametrize(
    ("source_status", "local_status"),
    [
        (2, "open"),
        (3, "in_progress"),
        (4, "awaiting_control"),
        (5, "done"),
        (6, "postponed"),
        (7, "declined"),
    ],
)
def test_bitrix_task_status_codes_remain_distinct(source_status, local_status):
    module = _module()
    prepared = module._prepare_bitrix_tasks(
        [_bitrix_task_row(status=source_status, ufCrmTask=[])],
        [{"ID": "30", "CATEGORY_ID": "0"}],
    )
    task = prepared["tasks"][0]
    assert task["source_status_code"] == str(source_status)
    assert task["status"] == local_status


@pytest.mark.asyncio
async def test_bitrix_task_import_preserves_source_fields_links_and_replay(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_tasks(cache, [_bitrix_task_row()])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()
    await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from modules.sales.models import Deal, DealTask, DealTaskCrmLink

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        task = (await session.execute(
            select(DealTask).where(DealTask.source_ref == "bitrix:task:101")
        )).scalar_one()
        deal = (await session.execute(
            select(Deal).where(Deal.number == "BX-30")
        )).scalar_one()
        links = (await session.execute(
            select(DealTaskCrmLink)
            .where(DealTaskCrmLink.task_id == task.id)
            .order_by(DealTaskCrmLink.ordinal)
        )).scalars().all()
        assert task.deal_id == deal.id
        assert task.title == "Synthetic task title"
        assert task.description == "Synthetic task description"
        assert task.description_in_bbcode is True
        assert task.source_responsible_id == "7001"
        assert task.assignee_id is None
        assert (task.source_status_code, task.status) == ("6", "postponed")
        assert task.due_at.isoformat() == "2024-11-02T10:00:00"
        assert [(link.ordinal, link.raw_binding, link.entity_type, link.source_id,
                 link.deal_id) for link in links] == [
            (0, "D_30", "D", "30", deal.id),
            (1, "L_80", "L", "80", None),
        ]
        assert await session.scalar(
            select(func.count()).select_from(DealTask)
        ) == 1
        assert await session.scalar(
            select(func.count()).select_from(DealTaskCrmLink)
        ) == 2
    await db.disconnect()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(gap for gap in report["gaps"] if gap["area"] == "bitrix_tasks")
    assert gap["blocker"] is False
    assert gap["status"] == "source_available"
    assert gap["source_ref_expected_keys"] == 1
    assert gap["source_ref_destination_keys"] == 1
    assert gap["source_ref_set_match"] is True
    assert gap["source_ref_semantic_match"] is True
    assert "Synthetic task title" not in output
    assert "7001" not in output


@pytest.mark.asyncio
async def test_bitrix_task_multiple_deal_bindings_and_unbound_task_are_preserved(
    monkeypatch, tmp_path
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    deals = [json.loads(line) for line in (cache / "bx_deals.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    deals.append({
        **deals[0], "ID": "31", "TITLE": "Synthetic second deal",
        "CATEGORY_ID": "7", "STAGE_ID": "C7:NEW",
    })
    _write_jsonl(cache, "bx_deals", deals)
    _write_bitrix_tasks(cache, [
        _bitrix_task_row(task_id="101", ufCrmTask=["D_30", "X9_8", "D_31"]),
        _bitrix_task_row(task_id="102", ufCrmTask=[]),
    ])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()

    from sqlalchemy import func, select

    from modules.sales.models import Deal, DealTask, DealTaskCrmLink

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal_ids = {
            deal.number: deal.id
            for deal in (await session.execute(
                select(Deal).where(Deal.number.in_(["BX-30", "BX-31"]))
            )).scalars()
        }
        tasks = {
            task.source_ref: task
            for task in (await session.execute(select(DealTask))).scalars()
        }
        assert tasks["bitrix:task:101"].deal_id is None
        assert tasks["bitrix:task:102"].deal_id is None
        links = (await session.execute(
            select(DealTaskCrmLink)
            .where(DealTaskCrmLink.task_id == tasks["bitrix:task:101"].id)
            .order_by(DealTaskCrmLink.ordinal)
        )).scalars().all()
        assert [(link.ordinal, link.raw_binding, link.deal_id) for link in links] == [
            (0, "D_30", deal_ids["BX-30"]),
            (1, "X9_8", None),
            (2, "D_31", deal_ids["BX-31"]),
        ]
        assert await session.scalar(
            select(func.count()).select_from(DealTaskCrmLink)
            .where(DealTaskCrmLink.task_id == tasks["bitrix:task:102"].id)
        ) == 0
    await db.disconnect()


@pytest.mark.parametrize(
    ("task_changes", "deal_category", "second_task"),
    [
        ({"id": None}, "0", None),
        ({"status": "8"}, "0", None),
        ({"title": "x" * 256}, "0", None),
        ({"responsibleId": "1" * 65}, "0", None),
        ({"deadline": "2024-11-02T10:00:00"}, "0", None),
        ({"ufCrmTask": ["D_999"]}, "0", None),
        ({"ufCrmTask": "D_30"}, "0", None),
        ({"ufCrmTask": ["X_" + "1" * 65]}, "0", None),
        ({"ufCrmTask": ["D_30"]}, "5", None),
        ({"ufCrmTask": ["D_030"]}, "0", None),
        ({"ufTaskWebdavFiles": ["FILE-1"]}, "0", None),
        ({"ufMailMessage": "mail-1"}, "0", None),
        ({"ID": "102"}, "0", None),
        ({}, "0", _bitrix_task_row()),
    ],
)
@pytest.mark.asyncio
async def test_invalid_bitrix_task_source_fails_before_database_writes(
    monkeypatch, tmp_path, task_changes, deal_category, second_task
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    task = _bitrix_task_row(**task_changes)
    _write_bitrix_tasks(cache, [task] + ([second_task] if second_task else []))
    if deal_category != "0":
        deals = [json.loads(line) for line in (cache / "bx_deals.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()]
        deals[0] = {**deals[0], "CATEGORY_ID": deal_category}
        _write_jsonl(cache, "bx_deals", deals)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    with pytest.raises(ValueError, match="BITRIX_TASK_INVALID"):
        await module.load()
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_invalid_bitrix_task_source_is_an_aggregate_reconcile_blocker(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_tasks(cache, [_bitrix_task_row(status="99")])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    with pytest.raises(ValueError, match="BITRIX_TASK_INVALID"):
        await module.load()
    assert not db_path.exists()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(gap for gap in report["gaps"] if gap["area"] == "bitrix_tasks")
    assert gap["status"] == "invalid_source"
    assert gap["blocker"] is True
    assert gap["source_ref_expected_keys"] is None
    assert "Synthetic task title" not in output
    assert "101" not in output


@pytest.mark.asyncio
async def test_bitrix_task_source_and_destination_drift_are_blocked_aggregately(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    original_task = _bitrix_task_row()
    _make_cache(cache)
    _write_bitrix_tasks(cache, [original_task])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    _write_bitrix_tasks(cache, [{**original_task, "description": "Changed source"}])
    with pytest.raises(ValueError, match="BITRIX_TASK_CONFLICT"):
        await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from modules.sales.models import DealTask

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        task = (await session.execute(select(DealTask))).scalar_one()
        assert task.description == "Synthetic task description"
        task.status = "done"
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(DealTask)) == 1
    await db.disconnect()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(gap for gap in report["gaps"] if gap["area"] == "bitrix_tasks")
    assert gap["blocker"] is True
    assert gap["status"] == "source_semantic_mismatch"
    assert gap["source_ref_set_match"] is True
    assert gap["source_ref_semantic_match"] is False
    assert "Synthetic task title" not in output
    assert "Changed source" not in output


@pytest.mark.asyncio
async def test_local_assignee_change_blocks_task_replay_and_reconcile(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_tasks(cache, [_bitrix_task_row(ufCrmTask=[])])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from modules.sales.models import DealTask

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        task = (await session.execute(select(DealTask))).scalar_one()
        assert task.deal_id is None
        task.assignee_id = 601
        await session.commit()
    await db.disconnect()

    with pytest.raises(ValueError, match="BITRIX_TASK_CONFLICT"):
        await module.load()

    await module.reconcile()
    output = capsys.readouterr().out
    report = json.loads(output)
    gap = next(gap for gap in report["gaps"] if gap["area"] == "bitrix_tasks")
    assert gap["blocker"] is True
    assert gap["status"] == "source_semantic_mismatch"
    assert gap["source_ref_semantic_match"] is False
    assert "601" not in output


def test_conflicting_task_binding_alias_fails_before_database_use():
    module = _module()
    row = _bitrix_task_row(ufCrmTask=[], UF_CRM_TASK=["D_30", "L_80"])
    with pytest.raises(ValueError, match="BITRIX_TASK_INVALID"):
        module._prepare_bitrix_tasks([row], [{"ID": "30", "CATEGORY_ID": "0"}])


def test_official_task_binding_alias_is_used_when_camel_case_field_is_absent():
    module = _module()
    row = _bitrix_task_row()
    row.pop("ufCrmTask")
    row["UF_CRM_TASK"] = ["D_30", "L_80"]
    prepared = module._prepare_bitrix_tasks(
        [row], [{"ID": "30", "CATEGORY_ID": "0"}],
    )
    assert [link["raw_binding"] for link in prepared["tasks"][0]["links"]] == [
        "D_30", "L_80",
    ]


@pytest.mark.asyncio
async def test_bitrix_task_late_failure_rolls_back_tasks_and_deals(
    monkeypatch, tmp_path
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_bitrix_tasks(cache, [_bitrix_task_row()])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    async def fail_late(*args, **kwargs):
        raise RuntimeError("synthetic late failure")

    monkeypatch.setattr(module, "_load_sales_prices", fail_late)
    with pytest.raises(RuntimeError, match="synthetic late failure"):
        await module.load()

    from sqlalchemy import func, select

    from modules.sales.models import Deal, DealTask, DealTaskCrmLink

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Deal)) == 0
        assert await session.scalar(select(func.count()).select_from(DealTask)) == 0
        assert await session.scalar(select(func.count()).select_from(DealTaskCrmLink)) == 0
    await db.disconnect()


@pytest.mark.asyncio
async def test_sealed_nonempty_task_cache_loads_after_semantic_preflight(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "bx_product_rows", [{"deal_id": "30", "rows": []}])
    _write_jsonl(cache, "bx_products", [])
    _write_bitrix_tasks(cache, [_bitrix_task_row()])
    _seal_private_cache_for_test(cache, include_tasks=True)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    assert db_path.exists()
    assert "Synthetic task title" not in capsys.readouterr().out

    from sqlalchemy import func, select

    from modules.sales.models import DealTask

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(DealTask)) == 1
    await db.disconnect()


@pytest.mark.asyncio
async def test_confirmed_payment_is_preserved_and_legacy_paid_is_reported(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    monkeypatch.setenv("IMPORT_CACHE_DIR", str(cache))
    monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: pytest.fail("network"))

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from modules.finance.models import Payment

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        payment = (
            await session.execute(select(Payment).where(Payment.entity_ref == "1c:sale:sale-1"))
        ).scalar_one()
        assert payment.status == "pending"
        assert payment.paid_at is None
        assert payment.due_date is None
        payment.status = "paid"
        await session.commit()
    await db.disconnect()

    await module.reconcile()
    legacy = json.loads(capsys.readouterr().out)
    assert legacy["destination"]["financial"]["paid_rows"] == 1
    assert legacy["destination"]["financial"]["payments_with_allocations"] == 0
    assert legacy["destination"]["financial"]["legacy_paid_without_allocations"] == 1

    from modules.finance.models import PaymentAllocation

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        payment = (
            await session.execute(select(Payment).where(Payment.entity_ref == "1c:sale:sale-1"))
        ).scalar_one()
        session.add(PaymentAllocation(payment_id=payment.id, amount=payment.amount))
        await session.commit()
    await db.disconnect()

    await module.load()
    capsys.readouterr()
    await module.reconcile()
    confirmed = json.loads(capsys.readouterr().out)
    assert confirmed["destination"]["financial"]["paid_rows"] == 1
    assert confirmed["destination"]["financial"]["payments_with_allocations"] == 1
    assert confirmed["destination"]["financial"]["legacy_paid_without_allocations"] == 0


@pytest.mark.asyncio
async def test_bitrix_company_with_different_unp_does_not_create_master(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_counterparty_cache(
        cache,
        [{"ID": "bx-1", "TITLE": "Untrusted Bitrix Title"}],
        [{"ENTITY_ID": "bx-1", "RQ_INN": "111111111"}],
        [{"Ref_Key": "onec-1", "Description": "Authoritative 1C Name", "ИНН": "222222222"}],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyAlias

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        counterparties = (await session.execute(select(Counterparty))).scalars().all()
        aliases = (await session.execute(select(CounterpartyAlias))).scalars().all()
        assert len(counterparties) == 1
        assert counterparties[0].name == "Authoritative 1C Name"
        assert len(aliases) == 1
        assert aliases[0].source == "1c"
    await db.disconnect()

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    assert report["source"]["company_1c_mapping"]["outcomes"] == {
        "no_1c_unp_match": 1
    }
    assert report["destination"]["counts"]["counterparties"] == 1
    assert report["destination"]["counts"]["counterparty_aliases_bitrix_companies"] == 0
    assert report["destination"]["alias_audit"]["unp_conflict_refs"] == 0
    assert report["destination"]["fidelity"]["bitrix_companies"]["classification"]["status"] == "exact"


@pytest.mark.asyncio
async def test_counterparty_same_unp_different_name_uses_one_master(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_counterparty_cache(
        cache,
        [{"ID": "bx-1", "TITLE": "Bitrix Canonical"}],
        [{"ENTITY_ID": "bx-1", "RQ_INN": "111111111"}],
        [{"Ref_Key": "onec-1", "Description": "OneC Alias", "ИНН": "111111111"}],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from core.domain.models import Counterparty, CounterpartyAlias

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(Counterparty))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(CounterpartyAlias))).scalar_one() == 2
    await db.disconnect()

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    audit = report["destination"]["alias_audit"]
    assert audit["master_rows_with_bitrix_and_onec_aliases"] == 1
    assert audit["by_source"]["1c"]["destination_refs_with_unp"] == 1
    assert report["destination"]["fidelity"]["bitrix_companies"]["match"] is True


@pytest.mark.asyncio
async def test_distinct_1c_refs_with_duplicate_unp_keep_stable_masters(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    rows = [
        {"Ref_Key": "cp-z", "Description": "Canonical Zeta", "ИНН": "111111111"},
        {"Ref_Key": "cp-a", "Description": "Canonical Alpha", "ИНН": "111111111"},
    ]
    _make_counterparty_cache(
        cache,
        [{"ID": "bx-1", "TITLE": "Untrusted Bitrix Company"}],
        [{"ENTITY_ID": "bx-1", "RQ_INN": "111111111"}],
        rows,
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyAlias

    async def refs_and_names():
        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            aliases = (await session.execute(select(CounterpartyAlias))).scalars().all()
            masters = (await session.execute(select(Counterparty))).scalars().all()
            refs = {
                row.external_ref: row.counterparty_id
                for row in aliases
                if row.source == "1c"
            }
            names = {row.id: (row.name, row.unp) for row in masters}
            assert not any(row.source == "bitrix" for row in aliases)
        await db.disconnect()
        return refs, names

    first_refs, first_names = await refs_and_names()
    assert len(set(first_refs.values())) == 2
    assert first_names[first_refs["cp-a"]] == ("Canonical Alpha", "111111111")
    assert first_names[first_refs["cp-z"]] == ("Canonical Zeta", None)

    # Simulate an earlier importer collapsing both refs into one master; the next
    # pass must split the second alias back to its own 1C identity.
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        aliases = (await session.execute(select(CounterpartyAlias))).scalars().all()
        masters = (await session.execute(select(Counterparty))).scalars().all()
        ref_to_master = {
            row.external_ref: row.counterparty_id for row in aliases if row.source == "1c"
        }
        cp_z = next(row for row in aliases if row.source == "1c" and row.external_ref == "cp-z")
        cp_z.counterparty_id = ref_to_master["cp-a"]
        await session.execute(
            Counterparty.__table__.delete().where(Counterparty.id == ref_to_master["cp-z"])
        )
        await session.commit()
    await db.disconnect()

    # Input order changes do not change which Ref_Key retains the unique UNP row.
    _write_jsonl(cache, "onec_counterparties", list(reversed(rows)))
    await module.load()
    load_output = capsys.readouterr().out
    second_refs, second_names = await refs_and_names()
    assert second_refs == first_refs
    assert second_names == first_names
    assert "counterparty_1c_ref_splits: 1" in load_output

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    assert report["source"]["company_1c_mapping"]["outcomes"] == {
        "ambiguous_1c_unp_match": 1
    }


@pytest.mark.asyncio
async def test_incremental_duplicate_unp_keeps_existing_1c_ref_master_id(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_counterparty_cache(
        cache,
        [],
        [],
        [{"Ref_Key": "cp-z", "Description": "Canonical Zeta", "ИНН": "111111111"}],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    async def references_and_masters():
        from sqlalchemy import select

        from core.domain.models import Counterparty, CounterpartyAlias

        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            aliases = (await session.execute(select(CounterpartyAlias))).scalars().all()
            masters = (await session.execute(select(Counterparty))).scalars().all()
            references = {
                row.external_ref: row.counterparty_id
                for row in aliases if row.source == "1c"
            }
            master_data = {
                row.id: (row.name, row.unp) for row in masters
            }
        await db.disconnect()
        return references, master_data

    await module.load()
    first_output = capsys.readouterr()
    first_refs, first_masters = await references_and_masters()
    cp_z_id = first_refs["cp-z"]
    assert first_masters[cp_z_id] == ("Canonical Zeta", "111111111")
    assert "Canonical Zeta" not in first_output.out + first_output.err
    assert "111111111" not in first_output.out + first_output.err

    # A newly arrived, lexically earlier Ref_Key must not take the existing identity,
    # even when the incremental input contains only that new reference.
    rows = [
        {"Ref_Key": "cp-a", "Description": "Canonical Alpha", "ИНН": "111111111"},
        {"Ref_Key": "cp-z", "Description": "Canonical Zeta", "ИНН": "111111111"},
    ]
    _write_jsonl(cache, "onec_counterparties", [rows[0]])
    await module.load()
    load_output = capsys.readouterr()
    second_refs, second_masters = await references_and_masters()
    assert second_refs["cp-z"] == cp_z_id
    assert second_refs["cp-a"] != cp_z_id
    assert second_masters[cp_z_id] == ("Canonical Zeta", "111111111")
    assert second_masters[second_refs["cp-a"]] == ("Canonical Alpha", None)
    assert "Canonical" not in load_output.out + load_output.err
    assert "111111111" not in load_output.out + load_output.err

    _write_jsonl(cache, "onec_counterparties", list(reversed(rows)))
    await module.load()
    capsys.readouterr()
    third_refs, third_masters = await references_and_masters()
    assert third_refs == second_refs
    assert third_masters == second_masters


@pytest.mark.asyncio
async def test_distinct_1c_refs_without_unp_do_not_merge_by_same_name(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    rows = [
        {"Ref_Key": "cp-z", "Description": "Same Legal Name"},
        {"Ref_Key": "cp-a", "Description": "Same Legal Name"},
    ]
    _make_counterparty_cache(cache, [], [], rows)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    load_output = capsys.readouterr()

    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyAlias

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        aliases = (await session.execute(select(CounterpartyAlias))).scalars().all()
        masters = (await session.execute(select(Counterparty))).scalars().all()
        references = {
            row.external_ref: row.counterparty_id
            for row in aliases if row.source == "1c"
        }
        assert len(masters) == 2
        assert references["cp-a"] != references["cp-z"]
        assert all(row.unp is None for row in masters)
        assert all(row.name == "Same Legal Name" for row in masters)
    await db.disconnect()
    assert "Same Legal Name" not in load_output.out + load_output.err


@pytest.mark.asyncio
async def test_duplicate_1c_unp_full_load_is_independent_of_input_order(
    monkeypatch, tmp_path, capsys
):
    rows = [
        {"Ref_Key": "cp-z", "Description": "Canonical Zeta", "ИНН": "111111111"},
        {"Ref_Key": "cp-a", "Description": "Canonical Alpha", "ИНН": "111111111"},
    ]
    results = []
    for index, ordered_rows in enumerate((rows, list(reversed(rows)))):
        module = _module()
        cache = (tmp_path / f"cache-{index}").resolve()
        cache.mkdir()
        _make_counterparty_cache(cache, [], [], ordered_rows)
        db_path = (tmp_path / f"isolated-{index}.sqlite3").resolve()
        _set_load_environment(monkeypatch, cache, db_path)

        await module.load()
        load_output = capsys.readouterr()
        assert "Canonical" not in load_output.out + load_output.err
        assert "111111111" not in load_output.out + load_output.err

        from sqlalchemy import select

        from core.domain.models import Counterparty, CounterpartyAlias

        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            aliases = (await session.execute(select(CounterpartyAlias))).scalars().all()
            masters = (await session.execute(select(Counterparty))).scalars().all()
            master_data = {row.id: (row.name, row.unp) for row in masters}
            results.append({
                row.external_ref: master_data[row.counterparty_id]
                for row in aliases if row.source == "1c"
            })
        await db.disconnect()

    assert results[0] == results[1] == {
        "cp-a": ("Canonical Alpha", "111111111"),
        "cp-z": ("Canonical Zeta", None),
    }


@pytest.mark.asyncio
async def test_counterparty_alias_unp_drift_is_not_retargeted_and_is_reported(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_counterparty_cache(
        cache,
        [{"ID": "bx-1", "TITLE": "Untrusted Bitrix Title"}],
        [{"ENTITY_ID": "bx-1", "RQ_INN": "111111111"}],
        [{"Ref_Key": "onec-1", "Description": "Stable 1C Master", "ИНН": "111111111"}],
    )
    _write_jsonl(
        cache,
        "bx_deals",
        [{"ID": "pilot-1", "TITLE": "Synthetic pilot", "STAGE_ID": "NEW",
          "CATEGORY_ID": "0", "COMPANY_ID": "bx-1", "OPPORTUNITY": "1"}],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await module.load()
    capsys.readouterr()

    # Changed source evidence must not retarget the pre-existing Bitrix alias.
    _make_counterparty_cache(
        cache,
        [{"ID": "bx-1", "TITLE": "Changed Bitrix Title"}],
        [{"ENTITY_ID": "bx-1", "RQ_INN": "222222222"}],
        [
            {"Ref_Key": "onec-1", "Description": "Stable 1C Master", "ИНН": "111111111"},
            {"Ref_Key": "onec-2", "Description": "Other 1C Master", "ИНН": "222222222"},
        ],
    )
    await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from core.domain.models import Counterparty, CounterpartyAlias

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        masters = (await session.execute(select(Counterparty).order_by(Counterparty.unp))).scalars().all()
        aliases = (await session.execute(select(CounterpartyAlias))).scalars().all()
        assert (await session.execute(select(func.count()).select_from(Counterparty))).scalar_one() == 2
        assert (await session.execute(select(func.count()).select_from(CounterpartyAlias))).scalar_one() == 3
        assert [(row.name, row.unp) for row in masters] == [
            ("Stable 1C Master", "111111111"),
            ("Other 1C Master", "222222222"),
        ]
        bitrix_alias = next(row for row in aliases if row.source == "bitrix")
        assert bitrix_alias.counterparty_id == masters[0].id
    await db.disconnect()

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    assert report["destination"]["alias_audit"]["unp_conflict_refs"] == 1
    assert report["destination"]["fidelity"]["bitrix_companies"]["match"] is False
    assert report["destination"]["crm_directory_links"]["client_outcomes"][
        "counterparty_existing_alias_conflict"
    ] == 1


@pytest.mark.asyncio
async def test_preserved_1c_ref_unp_drift_rolls_back_before_bitrix_alias_link(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_counterparty_cache(
        cache,
        [],
        [],
        [
            {"Ref_Key": "ref-a", "Description": "Stable Alpha", "ИНН": "111111111"},
            {"Ref_Key": "ref-z", "Description": "Stable Zeta", "ИНН": "222222222"},
        ],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyAlias

    async def directory_state():
        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            aliases = (await session.execute(select(CounterpartyAlias))).scalars().all()
            masters = (await session.execute(select(Counterparty))).scalars().all()
            refs = {
                row.external_ref: row.counterparty_id
                for row in aliases if row.source == "1c"
            }
            master_data = {row.id: (row.name, row.unp) for row in masters}
            assert not any(row.source == "bitrix" for row in aliases)
        await db.disconnect()
        return refs, master_data

    initial_refs, initial_masters = await directory_state()
    _make_counterparty_cache(
        cache,
        [{"ID": "bx-10", "TITLE": "Bitrix Company"}],
        [{"ENTITY_ID": "bx-10", "RQ_INN": "111111111"}],
        [{"Ref_Key": "ref-z", "Description": "Changed Zeta", "ИНН": "111111111"}],
    )

    with pytest.raises(RuntimeError, match="counterparty alias UNP conflict"):
        await module.load()
    output = capsys.readouterr()
    assert "Changed Zeta" not in output.out + output.err
    assert "111111111" not in output.out + output.err

    final_refs, final_masters = await directory_state()
    assert final_refs == initial_refs
    assert final_masters == initial_masters


@pytest.mark.asyncio
async def test_private_reconcile_details_preserve_aggregate_and_are_repeatable(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from core.domain.models import Contact, Counterparty, CounterpartyAlias

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        counterparty_id = (
            select(CounterpartyAlias.counterparty_id)
            .where(
                CounterpartyAlias.source == "bitrix",
                CounterpartyAlias.external_ref == "company:10",
            )
            .scalar_subquery()
        )
        company = (await session.execute(select(Counterparty).where(
            Counterparty.id == counterparty_id
        ))).scalar_one()
        company.name = "Changed Company"
        contact = (await session.execute(
            select(Contact).where(Contact.full_name == "Test Contact")
        )).scalar_one()
        contact.counterparty_id = None
        await session.commit()
    await db.disconnect()

    await module.reconcile()
    aggregate_stdout = capsys.readouterr().out
    assert "Test Company" not in aggregate_stdout
    assert "Changed Company" not in aggregate_stdout

    detail_path = (tmp_path / "private" / "details.json").resolve()
    monkeypatch.setenv("IMPORT_RECONCILE_DETAIL_REPORT", str(detail_path))
    await module.reconcile()
    detail_stdout = capsys.readouterr().out
    assert detail_stdout == aggregate_stdout
    private_report = json.loads(detail_path.read_text(encoding="utf-8"))
    rows = private_report["rows"]
    assert [row["source_id"] for row in rows] == ["10", "20", "30"]
    assert rows[0]["changed_fields"] == ["name"]
    assert rows[0]["source"]["name"] == "Test 1C Company"
    assert rows[0]["destination"]["name"] == "Changed Company"
    assert rows[1]["changed_fields"] == ["counterparty_link"]
    assert rows[1]["source"]["counterparty_link"] == "company:10"
    assert rows[1]["destination"]["counterparty_link"] is None
    assert rows[2]["kind"] == "crm_directory_link_unresolved"
    assert rows[2]["reason"]["client"] == "owner_unmapped"
    first_bytes = detail_path.read_bytes()

    await module.reconcile()
    assert capsys.readouterr().out == detail_stdout
    assert detail_path.read_bytes() == first_bytes


def test_private_source_details_include_missing_links_without_default_output(
    monkeypatch, tmp_path
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)

    deals = [json.loads(line) for line in (cache / "bx_deals.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    deals[0] = {**deals[0], "ID": "31", "COMPANY_ID": "999"}
    _write_jsonl(cache, "bx_deals", deals)
    calls = [json.loads(line) for line in (cache / "bx_calls.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    calls[0] = {
        **calls[0],
        "ID": "51",
        "CALL_ID": "51",
        "CRM_ENTITY_TYPE": "COMPANY",
        "CRM_ENTITY_ID": "888",
    }
    calls.append({
        **calls[0],
        "ID": "52",
        "CALL_ID": "52",
        "CRM_ENTITY_TYPE": "CONTACT",
        "CRM_ENTITY_ID": "777",
    })
    _write_jsonl(cache, "bx_calls", calls)
    sales = [json.loads(line) for line in (cache / "onec_sales.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    sales[0] = {
        **sales[0],
        "Контрагент_Key": "cp-missing",
        "Товары": [{"Номенклатура_Key": "sku-missing", "Цена": "10"}],
    }
    sales.append({**sales[0], "Ref_Key": "second-shared-missing-sale"})
    _write_jsonl(cache, "onec_sales", sales)

    monkeypatch.setattr(module, "OUT_DIR", cache)
    detail_rows = []
    report = module._source_reconciliation(detail_rows=detail_rows)
    relations = {row["relation"] for row in detail_rows}
    assert relations == {
        "deals_to_companies",
        "calls_to_companies",
        "calls_to_contacts",
        "onec_sales_to_sku",
        "onec_sales_to_counterparty",
    }
    assert {
        row["source_id"]
        for row in detail_rows
        if row["dataset"].startswith("bitrix_")
    } == {"31", "51", "52"}
    onec_details = [row for row in detail_rows if row["dataset"] == "onec_sales"]
    assert {(row["relation"], row["source_reference_id"]) for row in onec_details} == {
        ("onec_sales_to_sku", "sku-missing"),
        ("onec_sales_to_counterparty", "cp-missing"),
    }
    assert report["links"]["deals_to_companies"]["rows_missing"] == 1
    assert report["links"]["calls_to_companies"]["rows_missing"] == 1
    assert report["links"]["calls_to_contacts"]["rows_missing"] == 1
    assert len(onec_details) == 4
    assert {row["source_id"] for row in onec_details} == {
        str(sales[0]["Ref_Key"]), "second-shared-missing-sale",
    }
    assert report["products"]["onec_item_refs_missing_sku"] == 1
    assert report["products"]["onec_counterparty_refs_missing"] == 1


@pytest.mark.asyncio
async def test_private_detail_path_is_validated_before_any_write(
    monkeypatch, tmp_path
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    aggregate_path = (tmp_path / "aggregate.json").resolve()
    monkeypatch.setenv("IMPORT_RECONCILE_REPORT", str(aggregate_path))
    monkeypatch.setenv("IMPORT_RECONCILE_DETAIL_REPORT", "relative-details.json")
    monkeypatch.setattr(
        module,
        "_isolated_database",
        lambda: pytest.fail("path validation must precede database access"),
    )

    with pytest.raises(RuntimeError, match="IMPORT_RECONCILE_DETAIL_REPORT"):
        await module.reconcile()
    assert not aggregate_path.exists()
    assert not (Path("relative-details.json")).exists()


@pytest.mark.asyncio
async def test_private_report_collision_guard_preserves_inputs_and_skips_db(
    monkeypatch, tmp_path
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    cache_file = cache / "bx_companies.jsonl"
    cache_bytes = cache_file.read_bytes()
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    db_path.write_bytes(b"sqlite-input")
    db_bytes = db_path.read_bytes()
    _set_load_environment(monkeypatch, cache, db_path)
    monkeypatch.setattr(
        module,
        "_isolated_database",
        lambda: pytest.fail("collision validation must precede database access"),
    )

    detail_targets = [cache_file, db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]
    hardlink = tmp_path / "cache-hardlink.jsonl"
    try:
        os.link(cache_file, hardlink)
    except OSError:
        pass
    else:
        detail_targets.append(hardlink)

    for index, detail_target in enumerate(detail_targets):
        aggregate_path = (tmp_path / f"aggregate-{index}.json").resolve()
        monkeypatch.setenv("IMPORT_RECONCILE_REPORT", str(aggregate_path))
        monkeypatch.setenv("IMPORT_RECONCILE_DETAIL_REPORT", str(detail_target))
        with pytest.raises(RuntimeError, match="IMPORT_RECONCILE_DETAIL_REPORT"):
            await module.reconcile()
        assert cache_file.read_bytes() == cache_bytes
        assert db_path.read_bytes() == db_bytes
        assert not aggregate_path.exists()

    same_path = (tmp_path / "same.json").resolve()
    monkeypatch.setenv("IMPORT_RECONCILE_REPORT", str(same_path))
    monkeypatch.setenv("IMPORT_RECONCILE_DETAIL_REPORT", str(same_path))
    with pytest.raises(RuntimeError, match="IMPORT_RECONCILE_REPORT"):
        await module.reconcile()
    assert not same_path.exists()


async def _seed_bitrix_owner_account(
    module,
    *,
    username: str = "bitrix:1",
    employee_id: int | None = 901,
    status: str = "active",
    department: str = "Продажи",
    role: str = "sales",
):
    from core.domain.models import User

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        session.add(User(
            username=username,
            full_name="Test User",
            employee_id=employee_id,
            department=department,
            role=role,
            status=status,
        ))
        await session.commit()
    await db.disconnect()


@pytest.mark.asyncio
async def test_new_deal_links_to_confirmed_owner_master_and_contact_on_repeated_load(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await _seed_bitrix_owner_account(module)

    await module.load()
    first_output = capsys.readouterr()
    assert "Test Contact" not in first_output.out + first_output.err
    assert "+375291234567" not in first_output.out + first_output.err
    assert "test@example.invalid" not in first_output.out + first_output.err

    from sqlalchemy import func, select

    from core.domain.models import CounterpartyAlias
    from modules.sales.models import CrmClient, CrmClientContact, Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(
            select(Deal).where(Deal.number == "BX-30")
        )).scalar_one()
        alias = (await session.execute(
            select(CounterpartyAlias).where(
                CounterpartyAlias.source == "1c",
                CounterpartyAlias.external_ref == "cp-1",
            )
        )).scalar_one()
        client = (await session.execute(
            select(CrmClient).where(CrmClient.id == deal.crm_client_id)
        )).scalar_one()
        contact = (await session.execute(
            select(CrmClientContact).where(CrmClientContact.id == deal.crm_contact_id)
        )).scalar_one()
        assert deal.owner_id == 901
        assert client.owner_id == 901
        assert client.counterparty_id == alias.counterparty_id
        assert client.name == "Test 1C Company"
        assert contact.crm_client_id == client.id
        assert (contact.full_name, contact.phone, contact.email) == (
            "Test Contact", "+375291234567", "test@example.invalid"
        )
        ids = (deal.id, client.id, contact.id)
        assert (await session.execute(select(func.count()).select_from(CrmClient))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(CrmClientContact))).scalar_one() == 1
    await db.disconnect()

    await module.load()
    second_output = capsys.readouterr()
    assert "crm_clients_created: 0" in second_output.out
    assert "crm_client_contacts_created: 0" in second_output.out
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(
            select(Deal).where(Deal.number == "BX-30")
        )).scalar_one()
        counts = (
            (await session.execute(select(func.count()).select_from(CrmClient))).scalar_one(),
            (await session.execute(select(func.count()).select_from(CrmClientContact))).scalar_one(),
        )
        assert (deal.id, deal.crm_client_id, deal.crm_contact_id) == ids
        assert counts == (1, 1)
    await db.disconnect()

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    summary = report["destination"]["crm_directory_links"]
    assert summary["owner_outcomes"] == {"matched": 1}
    assert summary["client_links_verified"] == 1
    assert summary["contact_links_verified"] == 1


@pytest.mark.parametrize(
    ("username", "employee_id", "status", "department", "role"),
    [
        ("local:901", 901, "active", "Продажи", "sales"),
        ("bitrix:1", None, "active", "Продажи", "sales"),
        ("bitrix:1", 901, "inactive", "Продажи", "sales"),
        ("bitrix:1", 901, "active", "Маркетинг", "sales"),
        ("bitrix:1", 901, "active", "Продажи", "accountant"),
    ],
)
@pytest.mark.asyncio
async def test_new_deal_requires_exact_bitrix_owner_crosswalk_and_eligible_employee(
    monkeypatch, tmp_path, capsys, username, employee_id, status, department, role
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await _seed_bitrix_owner_account(
        module,
        username=username,
        employee_id=employee_id,
        status=status,
        department=department,
        role=role,
    )

    await module.load()
    load_output = capsys.readouterr()
    assert "Test Contact" not in load_output.out + load_output.err
    assert "test@example.invalid" not in load_output.out + load_output.err

    from sqlalchemy import func, select

    from modules.sales.models import CrmClient, CrmClientContact, Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(
            select(Deal).where(Deal.number == "BX-30")
        )).scalar_one()
        assert (deal.owner_id, deal.crm_client_id, deal.crm_contact_id) == (None, None, None)
        assert (await session.execute(select(func.count()).select_from(CrmClient))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(CrmClientContact))).scalar_one() == 0
    await db.disconnect()

    detail_path = (tmp_path / "private-details.json").resolve()
    monkeypatch.setenv("IMPORT_RECONCILE_DETAIL_REPORT", str(detail_path))
    await module.reconcile()
    report_output = capsys.readouterr().out
    report = json.loads(report_output)
    summary = report["destination"]["crm_directory_links"]
    assert summary["owner_outcomes"] == {"owner_unmapped": 1}
    private_report = json.loads(detail_path.read_text(encoding="utf-8"))
    detail = next(
        row for row in private_report["rows"]
        if row["kind"] == "crm_directory_link_unresolved"
    )
    assert detail["reason"]["owner"] == "owner_unmapped"
    assert detail["reason"]["client"] == "owner_unmapped"
    assert "Test Contact" not in report_output
    assert "test@example.invalid" not in report_output


@pytest.mark.asyncio
async def test_reimport_preserves_manual_deal_owner_client_and_contact(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await _seed_bitrix_owner_account(module)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from modules.sales.models import CrmClient, CrmClientContact, Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        manual_client = CrmClient(
            name="Manual CRM client",
            name_key="manual crm client",
            unp=None,
            owner_id=902,
            counterparty_id=None,
            request_key="manual-client-request",
            request_hash="f" * 64,
            created_by="manual synthetic test",
        )
        session.add(manual_client)
        await session.flush()
        manual_contact = CrmClientContact(
            crm_client_id=manual_client.id,
            full_name="Manual contact",
            phone=None,
            email="manual@example.invalid",
            contact_key="manual-contact-key",
            request_key="manual-contact-request",
            request_hash="e" * 64,
        )
        session.add(manual_contact)
        deal = (await session.execute(
            select(Deal).where(Deal.number == "BX-30")
        )).scalar_one()
        deal.owner_id = 902
        deal.crm_client_id = manual_client.id
        deal.crm_contact_id = manual_contact.id
        deal.title = "Manual title preserved"
        await session.commit()
        expected = (deal.owner_id, deal.crm_client_id, deal.crm_contact_id, deal.title)
    await db.disconnect()

    await module.load()
    output = capsys.readouterr().out
    assert "crm_clients_created: 0" in output
    assert "crm_client_contacts_created: 0" in output
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(
            select(Deal).where(Deal.number == "BX-30")
        )).scalar_one()
        assert (deal.owner_id, deal.crm_client_id, deal.crm_contact_id, deal.title) == expected
        assert (await session.execute(select(func.count()).select_from(CrmClient))).scalar_one() == 2
        assert (await session.execute(select(func.count()).select_from(CrmClientContact))).scalar_one() == 2
    await db.disconnect()


@pytest.mark.asyncio
async def test_client_name_conflict_leaves_new_deal_directory_ids_unresolved(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "bx_deals", [])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await _seed_bitrix_owner_account(module)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from modules.sales.models import CrmClient, CrmClientContact, Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        session.add(CrmClient(
            name="Test 1C Company",
            name_key="test 1c company",
            unp="100000003",
            owner_id=901,
            counterparty_id=None,
            request_key="preexisting-conflicting-client",
            request_hash="d" * 64,
            created_by="manual synthetic test",
        ))
        await session.commit()
    await db.disconnect()

    _write_jsonl(
        cache,
        "bx_deals",
        [{
            "ID": "30", "TITLE": "Test Deal", "STAGE_ID": "WON",
            "CATEGORY_ID": "0", "OPPORTUNITY": "10", "CURRENCY_ID": "BYN",
            "COMPANY_ID": "10", "CONTACT_ID": "20", "ASSIGNED_BY_ID": "1",
            "DATE_CREATE": "2024-11-02T10:00:00",
        }],
    )

    await module.load()
    load_output = capsys.readouterr().out
    assert "Test 1C Company" not in load_output
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(
            select(Deal).where(Deal.number == "BX-30")
        )).scalar_one()
        assert deal.owner_id == 901
        assert deal.crm_client_id is None
        assert deal.crm_contact_id is None
        assert (await session.execute(select(func.count()).select_from(CrmClient))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(CrmClientContact))).scalar_one() == 0
    await db.disconnect()

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    assert report["destination"]["crm_directory_links"]["client_outcomes"] == {
        "client_identity_conflict": 1
    }


@pytest.mark.asyncio
async def test_contact_channel_conflict_does_not_create_or_link_a_new_crm_contact(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "bx_deals", [])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await _seed_bitrix_owner_account(module)

    await module.load()
    capsys.readouterr()

    from sqlalchemy import select

    from core.domain.models import CounterpartyAlias
    from modules.sales.models import CrmClient, CrmClientContact, Deal

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        alias = (await session.execute(
            select(CounterpartyAlias).where(
                CounterpartyAlias.source == "1c",
                CounterpartyAlias.external_ref == "cp-1",
            )
        )).scalar_one()
        client = CrmClient(
            name="Test 1C Company",
            name_key="test 1c company",
            unp="100000002",
            owner_id=901,
            counterparty_id=alias.counterparty_id,
            request_key="preexisting-owner-client",
            request_hash="c" * 64,
            created_by="manual synthetic test",
        )
        session.add(client)
        await session.flush()
        session.add(CrmClientContact(
            crm_client_id=client.id,
            full_name="Test Contact",
            phone="+375291234567",
            email="different@example.invalid",
            contact_key="conflicting-contact-key",
            request_key="conflicting-contact-request",
            request_hash="b" * 64,
        ))
        await session.commit()
    await db.disconnect()

    _write_jsonl(
        cache,
        "bx_deals",
        [{
            "ID": "30", "TITLE": "Test Deal", "STAGE_ID": "WON",
            "CATEGORY_ID": "0", "OPPORTUNITY": "10", "CURRENCY_ID": "BYN",
            "COMPANY_ID": "10", "CONTACT_ID": "20", "ASSIGNED_BY_ID": "1",
            "DATE_CREATE": "2024-11-02T10:00:00",
        }],
    )

    await module.load()
    output = capsys.readouterr().out
    assert "Test Contact" not in output
    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        deal = (await session.execute(
            select(Deal).where(Deal.number == "BX-30")
        )).scalar_one()
        contacts = (await session.execute(select(CrmClientContact))).scalars().all()
        clients = (await session.execute(select(CrmClient))).scalars().all()
        assert deal.owner_id == 901
        assert deal.crm_client_id == clients[0].id
        assert deal.crm_contact_id is None
        assert len(clients) == 1
        assert len(contacts) == 1
    await db.disconnect()

    await module.reconcile()
    report = json.loads(capsys.readouterr().out)
    assert report["destination"]["crm_directory_links"]["contact_outcomes"] == {
        "contact_identity_conflict": 1
    }


@pytest.mark.asyncio
async def test_late_load_failure_rolls_back_client_contact_and_deal_in_sqlite(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "bx_deals", [])
    _write_jsonl(cache, "bx_calls", [])
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await _seed_bitrix_owner_account(module)

    # Establish the authoritative company and global contact before the import
    # whose first new write will be a CRM SAVEPOINT.
    await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select

    from core.domain.models import Contact, Counterparty, CounterpartyAlias
    from modules.sales.models import CallLog, CrmClient, CrmClientContact, Deal

    async def database_counts():
        db = module._isolated_database()
        await db.connect()
        async with db.session_factory() as session:
            counts = []
            for model in (
                Counterparty, CounterpartyAlias, Contact, CrmClient,
                CrmClientContact, Deal, CallLog,
            ):
                counts.append(
                    (await session.execute(select(func.count()).select_from(model))).scalar_one()
                )
        await db.disconnect()
        return tuple(counts)

    before = await database_counts()
    assert before[3:] == (0, 0, 0, 0)

    _write_jsonl(
        cache,
        "bx_deals",
        [{
            "ID": "30", "TITLE": "Synthetic deal", "STAGE_ID": "NEW",
            "CATEGORY_ID": "0", "OPPORTUNITY": "10", "CURRENCY_ID": "BYN",
            "COMPANY_ID": "10", "CONTACT_ID": "20", "ASSIGNED_BY_ID": "1",
            "DATE_CREATE": "2024-11-02T10:00:00",
        }],
    )
    _write_jsonl(
        cache,
        "bx_calls",
        [{
            "ID": "50", "CALL_ID": "synthetic-late-failure",
            "CALL_START_DATE": "2024-11-02T10:00:00",
            "CALL_DURATION": "SyntheticInvalid", "CALL_FAILED_CODE": "200",
            "CALL_TYPE": "2", "CRM_ENTITY_TYPE": "DEAL", "CRM_ENTITY_ID": "30",
            "PORTAL_USER_ID": "1",
        }],
    )

    with pytest.raises(ValueError, match="SyntheticInvalid"):
        await module.load()
    capsys.readouterr()

    after = await database_counts()
    assert after == before


@pytest.mark.asyncio
async def test_stale_api_client_check_cannot_duplicate_imported_counterparty_client(
    monkeypatch, tmp_path, capsys
):
    module = _module()
    cache = (tmp_path / "cache").resolve()
    cache.mkdir()
    _make_cache(cache)
    _write_jsonl(cache, "bx_deals", [])
    _write_jsonl(cache, "bx_calls", [])
    _write_jsonl(cache, "bx_companies", [{"ID": "10", "TITLE": "Synthetic  Master"}])
    _write_jsonl(cache, "bx_requisites", [])
    _write_jsonl(
        cache,
        "onec_counterparties",
        [{"Ref_Key": "cp-1", "Description": "Synthetic  Master"}],
    )
    db_path = (tmp_path / "isolated.sqlite3").resolve()
    _set_load_environment(monkeypatch, cache, db_path)
    await _seed_bitrix_owner_account(module)

    # Materialize the 1C master and company alias, but no deal or CRM client.
    await module.load()
    capsys.readouterr()

    from sqlalchemy import func, select
    from sqlalchemy.exc import IntegrityError

    from core.domain.models import CounterpartyAlias
    from modules.sales.models import CrmClient, Deal

    api_db = module._isolated_database()
    await api_db.connect()
    async with api_db.session_factory() as api_session:
        alias = (await api_session.execute(
            select(CounterpartyAlias).where(
                CounterpartyAlias.source == "1c",
                CounterpartyAlias.external_ref == "cp-1",
            )
        )).scalar_one()
        master_id = alias.counterparty_id
        api_seen = await api_session.scalar(
            select(CrmClient).where(
                CrmClient.owner_id == 901,
                CrmClient.counterparty_id == master_id,
            )
        )
        assert api_seen is None

        _write_jsonl(
            cache,
            "bx_deals",
            [{
                "ID": "30", "TITLE": "Synthetic deal", "STAGE_ID": "NEW",
                "CATEGORY_ID": "0", "OPPORTUNITY": "10", "CURRENCY_ID": "BYN",
                "COMPANY_ID": "10", "CONTACT_ID": "20", "ASSIGNED_BY_ID": "1",
                "DATE_CREATE": "2024-11-02T10:00:00",
            }],
        )
        await module.load()
        capsys.readouterr()

        # Match the API's persisted form for a client made from a Counterparty:
        # preserve its internal whitespace in name_key. This insert represents
        # an API request that checked before the import's client became visible.
        api_client = CrmClient(
            name="Synthetic  Master",
            name_key="synthetic  master",
            unp=None,
            owner_id=901,
            counterparty_id=master_id,
            request_key="api-stale-check-request",
            request_hash="a" * 64,
            created_by="synthetic API",
        )
        with pytest.raises(IntegrityError):
            async with api_session.begin_nested():
                api_session.add(api_client)
                await api_session.flush()
        await api_session.rollback()
    await api_db.disconnect()

    db = module._isolated_database()
    await db.connect()
    async with db.session_factory() as session:
        assert (await session.execute(
            select(func.count()).select_from(CrmClient).where(
                CrmClient.owner_id == 901,
                CrmClient.counterparty_id == master_id,
            )
        )).scalar_one() == 1
        deal = (await session.execute(
            select(Deal).where(Deal.number == "BX-30")
        )).scalar_one()
        assert deal.crm_client_id is not None
    await db.disconnect()
