from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import update

from modules.accounting import service


def _production_ownership(book_id: int):
    from modules.production.accounting_ownership import ProductionOrderOwnership, order_snapshot
    from modules.production.models import ProductionOrder

    order = ProductionOrder(
        id=17, number="ПР-17", product="Насос", qty=3, stage="queue",
        created_at=datetime(2026, 9, 1, 10, 0, 0),
    )
    snapshot, digest = order_snapshot(order)
    return ProductionOrderOwnership(
        order_id=17, organization_id=book_id, snapshot=snapshot, digest=digest,
        evidence="Synthetic production ownership", actor="tester",
    )


async def test_manual_order_reference_requires_exact_production_ownership(book, posting):
    from modules.accounting import manual_documents, order_snapshot
    from modules.accounting.schemas import PostingInput

    ownership = _production_ownership(book[0])
    dimensions = order_snapshot.dimensions_from_ownership(ownership)

    class Session:
        def __init__(self, row):
            self.row = row
            self.calls = 0

        async def scalar(self, _statement):
            self.calls += 1
            return self.row

    session = Session(ownership)

    def reviewed(reference):
        payload = posting("MANUAL-PRODUCTION-ORDER").model_dump(mode="json")
        payload["lines"][0]["dimensions"] = reference
        return PostingInput.model_validate(payload)

    await manual_documents.verify_analytic_references(session, book[0], reviewed(dimensions))
    assert session.calls == 1
    for invalid in (
        {"order": "free text"},
        {key: value for key, value in dimensions.items() if key != "order_quantity"},
        {**dimensions, "order_product": "Forged product"},
        {**dimensions, "order_digest": "b" * 64},
        {**dimensions, "order_extra": "unrecognized"},
    ):
        with pytest.raises(service.AccountingError):
            await manual_documents.verify_analytic_references(session, book[0], reviewed(invalid))

    session.calls = 0
    with pytest.raises(service.AccountingError):
        await order_snapshot.verify_reference(session, book[0], {**dimensions, "order_id": "2147483648"})
    assert session.calls == 0
    session.row = _production_ownership(book[0] + 1)
    with pytest.raises(service.AccountingError):
        await order_snapshot.verify_reference(session, book[0], dimensions)

    session.row = ownership
    payload = reviewed(dimensions).model_dump(mode="json")
    forged = {**dimensions, "order_zz": dimensions["order_stage_at_ownership"]}
    del forged["order_stage_at_ownership"]
    payload["lines"][1]["dimensions"] = forged
    with pytest.raises(service.AccountingError):
        await manual_documents.verify_analytic_references(
            session, book[0], PostingInput.model_validate(payload),
        )


async def test_manual_order_options_are_organization_scoped_and_no_store(client, book, monkeypatch):
    from modules.accounting import routes

    async def options(_session, organization_id, term):
        assert organization_id == book[0]
        assert term == "ПР-17"
        return [{"order_source": "production", "order_id": "17"}]

    monkeypatch.setattr(routes.order_snapshot, "options", options)
    response = await client.get(
        f"/accounting/organizations/{book[0]}/manual-orders?q=%D0%9F%D0%A0-17",
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "organization_id": book[0], "items": [{"order_source": "production", "order_id": "17"}],
    }


async def _registered_manual_asset(db, book, posting):
    from datetime import date
    from decimal import Decimal
    from uuid import uuid4

    from sqlalchemy import select

    from modules.accounting import models

    db.add_all([
        models.Account(organization_id=book[0], code="01.1", title="ОС оборудования",
                       category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
                       currency_tracking=False, quantity_tracking=False, cash=False,
                       normative_ref="Synthetic fixed-asset fixture"),
        models.Account(organization_id=book[0], code="02.1", title="Амортизация ОС",
                       category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
                       currency_tracking=False, quantity_tracking=False, cash=False,
                       normative_ref="Synthetic fixed-asset fixture"),
        models.Account(organization_id=book[0], code="26", title="Расходы ОС",
                       category="expense", valid_from=date(2026, 1, 1), required_dimensions=[],
                       currency_tracking=False, quantity_tracking=False, cash=False,
                       normative_ref="Synthetic fixed-asset fixture"),
    ])
    await db.commit()
    source = await service.post(
        db, book[0], posting("MANUAL-ASSET-SOURCE", "01.1", "60", "1200.00"), "tester")
    source_line = await db.scalar(select(models.Line).where(
        models.Line.entry_id == source.id, models.Line.account_code == "01.1",
        models.Line.side == "debit",
    ))
    row = models.FixedAssetRegisterEntry(
        organization_id=book[0], request_key=str(uuid4()), asset_key="asset:equipment:001",
        source_entry_id=source.id, source_line_id=source_line.id, source_digest=source.digest,
        name="Станок", inventory_number="ОС-001", acquisition_date=date(2026, 9, 1),
        commissioning_date=date(2026, 9, 1), depreciation_start=date(2026, 9, 1),
        cost=Decimal("1200.00"), residual_value=Decimal("0.00"), useful_life_months=12,
        depreciation_method="straight_line", asset_account="01.1", accumulated_account="02.1",
        expense_account="26", dimensions={}, evidence="Synthetic registered asset fixture",
        command={}, digest="a" * 64, actor="tester",
    )
    db.add(row)
    await db.commit()
    return row, source, source_line


async def test_manual_document_save_history_close_guard_and_post(client, db, book, posting):
    prefix = f"/accounting/organizations/{book[0]}"
    path = prefix + "/manual-documents"
    first = posting("MANUAL-1")
    create = {"key": str(uuid4()), "posting": first.model_dump(mode="json")}
    saved = await client.post(path, json=create)
    assert saved.status_code == 201, saved.text
    document_id = saved.json()["id"]
    assert saved.json()["number"] == f"БС-{document_id}"
    assert saved.json()["status"] == "draft"
    assert saved.json()["version"] == 1
    assert saved.json()["revisions"][0]["actor"] == "tester"
    assert saved.json()["revisions"][0]["created_at"]
    assert (await client.post(path, json=create)).json()["id"] == document_id
    changed_key = {**create, "posting": posting("MANUAL-1", amount="120.00").model_dump(mode="json")}
    assert (await client.post(path, json=changed_key)).status_code == 409
    assert (await client.get(path)).json()["items"][0]["id"] == document_id
    assert (await client.get(f"{path}/{document_id}")).json()["organization_id"] == book[0]
    assert (await client.get(f"/accounting/organizations/{book[0] + 999}/manual-documents/{document_id}")).status_code == 403
    preliminary = await client.get(prefix + "/reports?start=2026-09-01&end=2026-09-30")
    assert preliminary.status_code == 200, preliminary.text
    assert preliminary.json()["pending_documents"] >= 1

    second = posting("MANUAL-1", amount="120.00", explanation="Corrected supplier source amount")
    edit = {"key": str(uuid4()), "expected_version": 1,
            "posting": second.model_dump(mode="json")}
    revised = await client.put(f"{path}/{document_id}", json=edit)
    assert revised.status_code == 200, revised.text
    assert revised.json()["version"] == 2
    assert [row["version"] for row in revised.json()["revisions"]] == [1, 2]
    assert revised.json()["revisions"][0]["posting"]["lines"][0]["amount"] == "100.00"
    assert revised.json()["revisions"][1]["posting"]["lines"][0]["amount"] == "120.00"
    assert (await client.put(f"{path}/{document_id}", json=edit)).json()["version"] == 2
    assert (await client.put(f"{path}/{document_id}", json={**edit, "key": str(uuid4())})).status_code == 409
    replayed_create = await client.post(path, json=create)
    assert replayed_create.status_code == 201, replayed_create.text
    assert replayed_create.json()["id"] == document_id
    assert replayed_create.json()["version"] == 2
    assert len(replayed_create.json()["revisions"]) == 2

    controls = await client.get(prefix + "/periods/2026-09/closing-controls")
    assert controls.status_code == 200, controls.text
    assert {item["code"] for item in controls.json()["blockers"]} >= {"unposted_manual_documents"}
    assert controls.json()["documents"]["pending_manual_documents"] == 1
    period = await service.period_for(db, book[0], "2026-09")
    close = {"expected_generation": period.generation,
             "evidence": {step: "checked" for step in service.CLOSE_STEPS}}
    blocked = await client.post(prefix + "/periods/2026-09/close", json=close)
    assert blocked.status_code == 422, blocked.text
    assert "Unposted manual accounting documents" in blocked.text

    command = {"key": str(uuid4()), "expected_version": 2, "digest": service.digest(second)}
    confirmed = await client.post(f"{path}/{document_id}/post", json=command)
    assert confirmed.status_code == 200, confirmed.text
    entry_id = confirmed.json()["entry_id"]
    assert confirmed.json()["document_version"] == 2
    assert confirmed.json()["digest"] == command["digest"]
    assert (await client.post(f"{path}/{document_id}/post", json=command)).json()["entry_id"] == entry_id
    assert (await client.post(f"{path}/{document_id}/post", json={**command, "key": str(uuid4())})).status_code == 409
    replayed_create = await client.post(path, json=create)
    assert replayed_create.status_code == 201, replayed_create.text
    assert replayed_create.json()["status"] == "posted"
    assert replayed_create.json()["version"] == 2
    assert replayed_create.json()["entry_id"] == entry_id
    assert (await client.put(f"{path}/{document_id}", json={**edit, "expected_version": 2,
                                                         "key": str(uuid4())})).status_code == 409
    final = (await client.get(f"{path}/{document_id}")).json()
    assert final["status"] == "posted" and final["entry_id"] == entry_id
    assert (await client.get(prefix + "/periods/2026-09/closing-controls")).json()["documents"]["pending_manual_documents"] == 0
    after_post = await client.get(prefix + "/reports?start=2026-09-01&end=2026-09-30")
    assert after_post.status_code == 200 and after_post.json()["pending_documents"] == 0
    entry = (await client.get(f"{prefix}/entries/{entry_id}")).json()
    assert entry["source"] == "MANUAL-1"
    assert entry["lines"][0]["amount"] == "120.00"


async def test_posted_manual_document_is_corrected_by_a_new_linked_document(client, book, posting):
    prefix = f"/accounting/organizations/{book[0]}"
    path = prefix + "/manual-documents"
    original = posting("MANUAL-CORRECTION")
    saved = await client.post(path, json={
        "key": str(uuid4()), "posting": original.model_dump(mode="json"),
    })
    assert saved.status_code == 201, saved.text
    document_id = saved.json()["id"]
    posted = await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 1, "digest": service.digest(original),
    })
    assert posted.status_code == 200, posted.text
    original_entry_id = posted.json()["entry_id"]

    correction = posting(
        "MANUAL-CORRECTION", source_version=2, correction_of=original_entry_id,
        amount="20.00", explanation="Additive correction from the linked manual document",
    )
    corrected_document = await client.post(path, json={
        "key": str(uuid4()), "posting": correction.model_dump(mode="json"),
    })
    assert corrected_document.status_code == 201, corrected_document.text
    assert corrected_document.json()["id"] != document_id
    assert corrected_document.json()["revisions"][0]["posting"]["correction_of"] == original_entry_id
    corrected_id = corrected_document.json()["id"]
    corrected_post = await client.post(f"{path}/{corrected_id}/post", json={
        "key": str(uuid4()), "expected_version": 1, "digest": service.digest(correction),
    })
    assert corrected_post.status_code == 200, corrected_post.text
    corrected_entry_id = corrected_post.json()["entry_id"]

    unchanged_original = (await client.get(f"{path}/{document_id}")).json()
    assert unchanged_original["status"] == "posted"
    assert unchanged_original["entry_id"] == original_entry_id
    assert unchanged_original["revisions"][0]["posting"]["lines"][0]["amount"] == "100.00"
    corrected_entry = (await client.get(f"{prefix}/entries/{corrected_entry_id}")).json()
    assert corrected_entry["correction_of"] == original_entry_id
    assert corrected_entry["changes"]["after_lines"][0]["amount"] == "20.00"
    original_entry = (await client.get(f"{prefix}/entries/{original_entry_id}")).json()
    assert [item["id"] for item in original_entry["corrections"]] == [corrected_entry_id]
    report = (await client.get(f"{prefix}/reports?start=2026-09-01&end=2026-09-30")).json()
    balances = {row["account"]: row for row in report["trial_balance"]}
    assert balances["41"]["closing"] == "120.00"
    assert balances["60"]["closing"] == "-120.00"


async def test_manual_document_rejects_foreign_operation_and_changed_digest(client, book, posting):
    path = f"/accounting/organizations/{book[0]}/manual-documents"
    source = posting("MANUAL-2")
    wrong = source.model_dump(mode="json")
    wrong["operation"] = "inventory_purchase"
    assert (await client.post(path, json={"key": str(uuid4()), "posting": wrong})).status_code == 422
    created = await client.post(path, json={"key": str(uuid4()), "posting": source.model_dump(mode="json")})
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    assert (await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 1, "digest": "0" * 64,
    })).status_code == 409
    assert (await client.get(f"{path}/{document_id}")).json()["status"] == "draft"


async def test_manual_document_cannot_bind_another_documents_posting(client, book, posting):
    path = f"/accounting/organizations/{book[0]}/manual-documents"
    first_posting = posting("MANUAL-UNIQUE")
    first = await client.post(path, json={"key": str(uuid4()),
                                          "posting": first_posting.model_dump(mode="json")})
    second = await client.post(path, json={"key": str(uuid4()),
                                           "posting": first_posting.model_dump(mode="json")})
    assert first.status_code == 201 and second.status_code == 201
    posted = await client.post(f"{path}/{first.json()['id']}/post", json={
        "key": str(uuid4()), "expected_version": 1, "digest": service.digest(first_posting),
    })
    assert posted.status_code == 200, posted.text
    duplicate = await client.post(f"{path}/{second.json()['id']}/post", json={
        "key": str(uuid4()), "expected_version": 1, "digest": service.digest(first_posting),
    })
    assert duplicate.status_code == 409
    assert (await client.get(f"{path}/{second.json()['id']}")).json()["status"] == "draft"
    other = await client.post(path, json={"key": str(uuid4()),
                                          "posting": posting("MANUAL-OTHER").model_dump(mode="json")})
    assert other.status_code == 201
    edit = await client.put(f"{path}/{other.json()['id']}", json={
        "key": str(uuid4()), "expected_version": 1,
        "posting": first_posting.model_dump(mode="json"),
    })
    assert edit.status_code == 409


async def test_unposted_manual_document_can_be_voided_without_erasing_history(client, book, posting):
    prefix = f"/accounting/organizations/{book[0]}"
    path = prefix + "/manual-documents"
    draft = await client.post(path, json={"key": str(uuid4()),
                                          "posting": posting("MANUAL-VOID").model_dump(mode="json")})
    assert draft.status_code == 201, draft.text
    document_id = draft.json()["id"]
    command = {"key": str(uuid4()), "expected_version": 1, "reason": " Duplicate draft "}
    voided = await client.post(f"{path}/{document_id}/void", json=command)
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "voided"
    assert voided.json()["void"]["reason"] == "Duplicate draft"
    assert voided.json()["void"]["actor"] == "tester"
    assert voided.json()["revisions"][0]["posting"]["source"] == "MANUAL-VOID"
    assert (await client.post(f"{path}/{document_id}/void", json=command)).json()["status"] == "voided"
    assert (await client.post(f"{path}/{document_id}/void", json={**command, "key": str(uuid4())})).status_code == 409
    assert (await client.put(f"{path}/{document_id}", json={
        "key": str(uuid4()), "expected_version": 1,
        "posting": posting("MANUAL-VOID").model_dump(mode="json"),
    })).status_code == 409
    assert (await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 1,
        "digest": service.digest(posting("MANUAL-VOID")),
    })).status_code == 409
    assert (await client.get(path)).json()["items"][0]["status"] == "voided"
    controls = await client.get(prefix + "/periods/2026-09/closing-controls")
    assert controls.status_code == 200
    assert controls.json()["documents"]["pending_manual_documents"] == 0
    report = await client.get(prefix + "/reports?start=2026-09-01&end=2026-09-30")
    assert report.status_code == 200 and report.json()["pending_documents"] == 0


async def test_manual_counterparty_snapshot_requires_directory_id_and_stays_historical(client, db, book, posting):
    from core.domain.models import Counterparty
    from modules.accounting.schemas import PostingInput

    path = f"/accounting/organizations/{book[0]}/manual-documents"
    payload = posting("MANUAL-MDM").model_dump(mode="json")
    payload["lines"][1]["dimensions"] = {"counterparty": "supplier1"}
    free_text = await client.post(path, json={"key": str(uuid4()), "posting": payload})
    assert free_text.status_code == 422 and "counterparty directory" in free_text.text
    assert (await client.post(f"/accounting/organizations/{book[0]}/preview", json=payload)).status_code == 422
    assert (await client.post(f"/accounting/organizations/{book[0]}/entries", json=payload)).status_code == 422

    payload["lines"][1]["dimensions"] = {
        "counterparty_id": "1", "counterparty": "supplier1",
        "counterparty_unp": "190000001", "counterparty_revision": "1",
    }
    saved = await client.post(path, json={"key": str(uuid4()), "posting": payload})
    assert saved.status_code == 201, saved.text
    document_id = saved.json()["id"]
    counterparty = await db.get(Counterparty, 1)
    counterparty.name = "Supplier renamed"
    await db.commit()
    stale = await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 1,
        "digest": service.digest(PostingInput.model_validate(payload)),
    })
    assert stale.status_code == 422 and "select it again" in stale.text
    await db.refresh(counterparty)
    payload["lines"][1]["dimensions"]["counterparty"] = counterparty.name
    payload["lines"][1]["dimensions"]["counterparty_revision"] = str(counterparty.revision)
    edited = await client.put(f"{path}/{document_id}", json={
        "key": str(uuid4()), "expected_version": 1, "posting": payload,
    })
    assert edited.status_code == 200 and edited.json()["version"] == 2
    confirmed = await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 2,
        "digest": service.digest(PostingInput.model_validate(payload)),
    })
    assert confirmed.status_code == 200, confirmed.text
    counterparty.name = "Supplier renamed again"
    await db.commit()
    entry = (await client.get(f"/accounting/organizations/{book[0]}/entries/{confirmed.json()['entry_id']}")).json()
    assert entry["lines"][1]["dimensions"]["counterparty"] == "Supplier renamed"
    replay = await client.post(f"/accounting/organizations/{book[0]}/entries", json=payload)
    assert replay.status_code == 201 and replay.json()["id"] == confirmed.json()["entry_id"]
    saved_history = (await client.get(f"{path}/{document_id}")).json()["revisions"]
    assert saved_history[0]["posting"]["lines"][1]["dimensions"]["counterparty"] == "supplier1"


async def test_manual_sku_snapshot_requires_directory_id_and_stays_historical(client, db, book, posting):
    from core.domain.models import Sku
    from modules.accounting.schemas import PostingInput

    db.add(Sku(id=71, code="ITEM-71", title="Motor", unit="шт", is_active=True))
    await db.commit()
    path = f"/accounting/organizations/{book[0]}/manual-documents"
    payload = posting("MANUAL-SKU").model_dump(mode="json")
    payload["lines"][0]["dimensions"] = {"sku": "ITEM-71"}
    assert (await client.post(path, json={"key": str(uuid4()), "posting": payload})).status_code == 422
    assert (await client.post(f"/accounting/organizations/{book[0]}/preview", json=payload)).status_code == 422
    assert (await client.post(f"/accounting/organizations/{book[0]}/entries", json=payload)).status_code == 422

    payload["lines"][0]["dimensions"] = {
        "sku_id": "71", "sku": "ITEM-71", "sku_title": "Motor", "sku_unit": "шт",
    }
    saved = await client.post(path, json={"key": str(uuid4()), "posting": payload})
    assert saved.status_code == 201, saved.text
    document_id = saved.json()["id"]
    sku = await db.get(Sku, 71)
    sku.title = "Motor updated"
    await db.commit()
    stale = await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 1,
        "digest": service.digest(PostingInput.model_validate(payload)),
    })
    assert stale.status_code == 422 and "select it again" in stale.text
    await db.refresh(sku)
    payload["lines"][0]["dimensions"]["sku_title"] = sku.title
    edited = await client.put(f"{path}/{document_id}", json={
        "key": str(uuid4()), "expected_version": 1, "posting": payload,
    })
    assert edited.status_code == 200 and edited.json()["version"] == 2
    confirmed = await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 2,
        "digest": service.digest(PostingInput.model_validate(payload)),
    })
    assert confirmed.status_code == 200, confirmed.text
    sku.title = "Motor renamed again"
    await db.commit()
    entry = (await client.get(f"/accounting/organizations/{book[0]}/entries/{confirmed.json()['entry_id']}")).json()
    assert entry["lines"][0]["dimensions"]["sku_title"] == "Motor updated"
    replay = await client.post(f"/accounting/organizations/{book[0]}/entries", json=payload)
    assert replay.status_code == 201 and replay.json()["id"] == confirmed.json()["entry_id"]


async def test_manual_warehouse_snapshot_is_company_scoped_and_historical(client, db, book, posting):
    from modules.accounting.models import Organization
    from modules.accounting.schemas import PostingInput
    from modules.wms.models import WarehouseDirectory

    other = Organization(name="Other warehouse owner", unp="888888888")
    db.add(other)
    await db.flush()
    own = WarehouseDirectory(organization_id=book[0], name="MAIN", title="Main store",
                             is_active=True, created_by="tester")
    foreign = WarehouseDirectory(organization_id=other.id, name="OTHER", title="Other store",
                                 is_active=True, created_by="tester")
    inactive = WarehouseDirectory(organization_id=book[0], name="OLD", title="Old store",
                                  is_active=False, created_by="tester")
    db.add_all([own, foreign, inactive])
    await db.commit()
    own_id, foreign_id, other_id = own.id, foreign.id, other.id
    options = await client.get(f"/accounting/organizations/{book[0]}/inventory/warehouses?q=store")
    assert options.status_code == 200
    assert options.json()["items"] == [{"id": own_id, "name": "MAIN", "title": "Main store"}]
    assert options.headers["cache-control"] == "private, no-store"
    assert (await client.get(f"/accounting/organizations/{other_id}/inventory/warehouses?q=store")).status_code == 403

    path = f"/accounting/organizations/{book[0]}/manual-documents"
    payload = posting("MANUAL-WAREHOUSE").model_dump(mode="json")
    payload["lines"][0]["dimensions"] = {"warehouse": "MAIN"}
    assert (await client.post(path, json={"key": str(uuid4()), "posting": payload})).status_code == 422
    assert (await client.post(f"/accounting/organizations/{book[0]}/preview", json=payload)).status_code == 422
    assert (await client.post(f"/accounting/organizations/{book[0]}/entries", json=payload)).status_code == 422
    payload["lines"][0]["dimensions"] = {
        "warehouse_id": str(foreign_id), "warehouse": "OTHER", "warehouse_title": "Other store",
    }
    assert (await client.post(path, json={"key": str(uuid4()), "posting": payload})).status_code == 422
    payload["lines"][0]["dimensions"] = {
        "warehouse_id": str(own_id), "warehouse": "MAIN", "warehouse_title": "Main store",
    }
    saved = await client.post(path, json={"key": str(uuid4()), "posting": payload})
    assert saved.status_code == 201, saved.text
    document_id = saved.json()["id"]
    await db.refresh(own)
    own.title = "Main store updated"
    await db.commit()
    stale = await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 1,
        "digest": service.digest(PostingInput.model_validate(payload)),
    })
    assert stale.status_code == 422 and "select it again" in stale.text
    await db.refresh(own)
    payload["lines"][0]["dimensions"]["warehouse_title"] = own.title
    edited = await client.put(f"{path}/{document_id}", json={
        "key": str(uuid4()), "expected_version": 1, "posting": payload,
    })
    assert edited.status_code == 200 and edited.json()["version"] == 2
    confirmed = await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 2,
        "digest": service.digest(PostingInput.model_validate(payload)),
    })
    assert confirmed.status_code == 200, confirmed.text
    own.title = "Main store renamed again"
    await db.commit()
    entry = (await client.get(f"/accounting/organizations/{book[0]}/entries/{confirmed.json()['entry_id']}")).json()
    assert entry["lines"][0]["dimensions"]["warehouse_title"] == "Main store updated"
    replay = await client.post(f"/accounting/organizations/{book[0]}/entries", json=payload)
    assert replay.status_code == 201 and replay.json()["id"] == confirmed.json()["entry_id"]


async def test_manual_contract_uses_counterparty_scoped_directory_and_keeps_replay(client, db, book, posting):
    from datetime import date, datetime

    from modules.accounting.schemas import PostingInput
    from modules.procurement.supplier_contracts import SupplierContract
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.client_document_register import DealClientBinding
    from modules.sales.models import Deal, DealDocument

    supplier_contract = SupplierContract(
        organization_id=book[0], supplier_id=1, number="SUP-17", title="Поставка",
        signed_on=date(2026, 1, 1), evidence="Synthetic registered supplier contract",
        is_active=True, created_by="tester",
    )
    deal = Deal(number="DEAL-CONTRACT-17", title="Synthetic sale", counterparty="supplier1",
                counterparty_id=1)
    db.add_all([supplier_contract, deal])
    await db.flush()
    db.add_all([
        DealOwnership(deal_id=deal.id, organization_id=book[0], snapshot={"test": True},
                      evidence="Synthetic ownership", actor="tester"),
        DealClientBinding(deal_id=deal.id, organization_id=book[0], counterparty_id=1,
                          snapshot={"client": {"id": 1}}, evidence="Synthetic binding", actor="tester"),
    ])
    sales_contract = DealDocument(
        deal_id=deal.id, kind="contract", number="SALE-19", status="posted", version=2,
        issued_at=datetime(2026, 1, 2), content_sha256="b" * 64,
        original_html="<p>contract</p>", snapshot_json={"organization_id": book[0]},
    )
    db.add(sales_contract)
    await db.commit()
    supplier_contract_id = supplier_contract.id
    sales_contract_id = sales_contract.id

    options = await client.get(
        f"/accounting/organizations/{book[0]}/contracts?counterparty_id=1&q=1")
    assert options.status_code == 200, options.text
    assert options.headers["cache-control"] == "private, no-store"
    assert {(item["source"], item["number"], item["version"]) for item in options.json()["items"]} == {
        ("procurement", "SUP-17", 1), ("sales", "SALE-19", 2),
    }

    path = f"/accounting/organizations/{book[0]}/manual-documents"
    payload = posting("MANUAL-CONTRACT").model_dump(mode="json")
    payload["lines"][1]["dimensions"] = {
        "counterparty_id": "1", "counterparty": "supplier1",
        "counterparty_unp": "190000001", "counterparty_revision": "1",
        "contract": "SUP-17",
    }
    assert (await client.post(path, json={"key": str(uuid4()), "posting": payload})).status_code == 422
    assert (await client.post(
        f"/accounting/organizations/{book[0]}/preview", json=payload)).status_code == 422
    assert (await client.post(
        f"/accounting/organizations/{book[0]}/entries", json=payload)).status_code == 422
    payload["lines"][1]["dimensions"].update({
        "contract_source": "procurement", "contract_id": str(supplier_contract_id),
        "contract_title": "Поставка", "contract_version": "1",
    })
    saved = await client.post(path, json={"key": str(uuid4()), "posting": payload})
    assert saved.status_code == 201, saved.text
    confirmed = await client.post(f"{path}/{saved.json()['id']}/post", json={
        "key": str(uuid4()), "expected_version": 1,
        "digest": service.digest(PostingInput.model_validate(payload)),
    })
    assert confirmed.status_code == 200, confirmed.text
    await db.execute(update(SupplierContract).where(SupplierContract.id == supplier_contract_id)
                     .values(is_active=False))
    await db.commit()
    replay = await client.post(f"/accounting/organizations/{book[0]}/entries", json=payload)
    assert replay.status_code == 201 and replay.json()["id"] == confirmed.json()["entry_id"]

    stale_payload = posting("MANUAL-CONTRACT-STALE").model_dump(mode="json")
    stale_payload["lines"][1]["dimensions"] = payload["lines"][1]["dimensions"]
    stale = await client.post(path, json={"key": str(uuid4()), "posting": stale_payload})
    assert stale.status_code == 422 and "select it again" in stale.text

    sales_payload = posting("MANUAL-SALES-CONTRACT").model_dump(mode="json")
    sales_payload["lines"][1]["dimensions"] = {
        "counterparty_id": "1", "counterparty": "supplier1",
        "counterparty_unp": "190000001", "counterparty_revision": "1",
        "contract": "SALE-19", "contract_source": "sales",
        "contract_id": str(sales_contract_id), "contract_title": "Договор продажи",
        "contract_version": "2",
    }
    sales_saved = await client.post(
        path, json={"key": str(uuid4()), "posting": sales_payload})
    assert sales_saved.status_code == 201, sales_saved.text


async def test_manual_settlement_document_uses_exact_register_revision_and_keeps_replay(
        client, db, book, posting):
    from datetime import date, datetime

    from modules.accounting.schemas import PostingInput
    from modules.procurement.receipt_documents import ReceiptDocument, ReceiptRevision
    from modules.procurement.supplier_contracts import SupplierContract
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.client_document_register import DealClientBinding
    from modules.sales.models import Deal, DealDocument, DocumentPackage

    supplier_contract = SupplierContract(
        organization_id=book[0], supplier_id=1, number="SUP-51", title="Поставка оборудования",
        signed_on=date(2026, 1, 1), evidence="Synthetic registered supplier contract",
        is_active=True, created_by="tester",
    )
    receipt = ReceiptDocument(
        organization_id=book[0], source_key="settlement-receipt-61", current_version=1,
        status="draft", created_by="tester",
    )
    deal = Deal(number="DEAL-SETTLEMENT-71", title="Synthetic sale", counterparty="supplier1",
                counterparty_id=1)
    db.add_all([supplier_contract, receipt, deal])
    await db.flush()
    receipt_facts = {
        "currency": "BYN", "invoice_reference": "ТН-61", "document_date": "2026-09-01",
        "operation_date": "2026-09-02", "supplier": "supplier1", "supplier_id": 1,
        "supplier_unp": "190000001", "contract": "SUP-51",
        "contract_id": supplier_contract.id, "warehouse": "warehouse1", "warehouse_id": 1,
        "warehouse_title": "Synthetic warehouse",
        "explanation": "Synthetic primary invoice", "items": [],
    }
    db.add_all([
        ReceiptRevision(receipt_id=receipt.id, version=1, document=receipt_facts, actor="tester"),
        DealOwnership(deal_id=deal.id, organization_id=book[0], snapshot={"test": True},
                      evidence="Synthetic ownership", actor="tester"),
        DealClientBinding(deal_id=deal.id, organization_id=book[0], counterparty_id=1,
                          snapshot={"client": {"id": 1}}, evidence="Synthetic binding", actor="tester"),
    ])
    sales_contract = DealDocument(
        deal_id=deal.id, kind="contract", number="SALE-C-71", status="posted", version=1,
        issued_at=datetime(2026, 1, 2), content_sha256="b" * 64,
        original_html="<p>contract</p>", snapshot_json={"organization_id": book[0]},
    )
    sales_invoice = DealDocument(
        deal_id=deal.id, kind="invoice", number="СФ-71", status="issued", version=3,
        issued_at=datetime(2026, 9, 2), content_sha256="c" * 64,
        original_html="<p>invoice</p>", snapshot_json={"organization_id": book[0]},
    )
    db.add_all([sales_contract, sales_invoice])
    await db.flush()
    db.add(DocumentPackage(
        deal_id=deal.id, invoice_id=sales_invoice.id, contract_id=sales_contract.id,
        original_html="<p>package</p>", content_sha256="d" * 64, created_by="tester",
    ))
    await db.commit()
    receipt_id = receipt.id
    supplier_contract_id = supplier_contract.id
    sales_contract_id = sales_contract.id
    sales_invoice_id = sales_invoice.id

    options = await client.get(
        f"/accounting/organizations/{book[0]}/settlement-documents?counterparty_id=1&q=1")
    assert options.status_code == 200, options.text
    assert options.headers["cache-control"] == "private, no-store"
    assert {(item["source"], item["number"], item["version"]) for item in options.json()["items"]} == {
        ("procurement", "ТН-61", 1), ("sales", "СФ-71", 3),
    }

    path = f"/accounting/organizations/{book[0]}/manual-documents"
    payload = posting("MANUAL-SETTLEMENT").model_dump(mode="json")
    payload["lines"][1]["dimensions"] = {
        "counterparty_id": "1", "counterparty": "supplier1",
        "counterparty_unp": "190000001", "counterparty_revision": "1",
        "contract": "SUP-51", "contract_source": "procurement",
        "contract_id": str(supplier_contract_id), "contract_title": "Поставка оборудования",
        "contract_version": "1", "settlement_document": "ТН-61",
    }
    assert (await client.post(path, json={"key": str(uuid4()), "posting": payload})).status_code == 422
    assert (await client.post(
        f"/accounting/organizations/{book[0]}/preview", json=payload)).status_code == 422
    assert (await client.post(
        f"/accounting/organizations/{book[0]}/entries", json=payload)).status_code == 422
    payload["lines"][1]["dimensions"].update({
        "settlement_document": f"procurement:receipt:{receipt_id}:1",
        "settlement_document_source": "procurement", "settlement_document_id": str(receipt_id),
        "settlement_document_number": "ТН-61", "settlement_document_version": "1",
    })
    saved = await client.post(path, json={"key": str(uuid4()), "posting": payload})
    assert saved.status_code == 201, saved.text
    document_id = saved.json()["id"]

    current_receipt = await db.get(ReceiptDocument, receipt_id)
    current_receipt.current_version = 2
    db.add(ReceiptRevision(receipt_id=receipt_id, version=2, document={**receipt_facts,
                                                                      "explanation": "Corrected"},
                           actor="tester"))
    await db.commit()
    stale = await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 1,
        "digest": service.digest(PostingInput.model_validate(payload)),
    })
    assert stale.status_code == 422 and "select it again" in stale.text
    payload["lines"][1]["dimensions"].update({
        "settlement_document": f"procurement:receipt:{receipt_id}:2",
        "settlement_document_version": "2",
    })
    edited = await client.put(f"{path}/{document_id}", json={
        "key": str(uuid4()), "expected_version": 1, "posting": payload,
    })
    assert edited.status_code == 200 and edited.json()["version"] == 2
    confirmed = await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 2,
        "digest": service.digest(PostingInput.model_validate(payload)),
    })
    assert confirmed.status_code == 200, confirmed.text

    current_receipt = await db.get(ReceiptDocument, receipt_id)
    current_receipt.current_version = 3
    db.add(ReceiptRevision(receipt_id=receipt_id, version=3, document={**receipt_facts,
                                                                      "explanation": "Later"},
                           actor="tester"))
    await db.commit()
    replay = await client.post(f"/accounting/organizations/{book[0]}/entries", json=payload)
    assert replay.status_code == 201 and replay.json()["id"] == confirmed.json()["entry_id"]

    sales_payload = posting("MANUAL-SALES-SETTLEMENT").model_dump(mode="json")
    sales_payload["lines"][1]["dimensions"] = {
        "counterparty_id": "1", "counterparty": "supplier1",
        "counterparty_unp": "190000001", "counterparty_revision": "1",
        "contract": "SALE-C-71", "contract_source": "sales",
        "contract_id": str(sales_contract_id), "contract_title": "Договор продажи",
        "contract_version": "1", "settlement_document": f"sales:document:{sales_invoice_id}",
        "settlement_document_source": "sales", "settlement_document_id": str(sales_invoice_id),
        "settlement_document_number": "СФ-71", "settlement_document_version": "3",
    }
    sales_saved = await client.post(
        path, json={"key": str(uuid4()), "posting": sales_payload})
    assert sales_saved.status_code == 201, sales_saved.text


async def test_manual_employee_snapshot_uses_current_employment_and_preserves_replay(
        client, db, book, posting):
    from datetime import date

    from modules.accounting.models import Account, Organization
    from modules.accounting.payroll_employment import PayrollEmploymentInput
    from modules.accounting.payroll_employment import create as create_binding
    from modules.accounting.schemas import PostingInput
    from modules.hr.models import Employee

    async def bind(org_id, employee_id, state="active", contract_ref="SYN-EMP-1",
                   effective_from="2026-01-01"):
        return await create_binding(db, org_id, PayrollEmploymentInput.model_validate({
            "request_key": str(uuid4()), "employee_id": employee_id,
            "contract_ref": contract_ref, "effective_from": effective_from,
            "state": state, "source_document": "synthetic-employment-contract",
            "evidence": "Synthetic binding evidence for accounting acceptance",
        }), "tester")

    def dimensions(binding):
        return {
            "employee": binding["employee_name"],
            "employee_id": str(binding["employee_id"]),
            "employment_binding_id": str(binding["binding_id"]),
            "employee_contract_ref": binding["contract_ref"],
            "employee_binding_revision": str(binding["revision"]),
            "employee_binding_digest": binding["digest"],
            "department": binding["department"],
        }

    account = Account(organization_id=book[0], code="42", title="Synthetic employee cost",
                      category="asset", valid_from=date(2026, 1, 1),
                      required_dimensions=["employee", "department"],
                      currency_tracking=True, quantity_tracking=False, cash=False,
                      normative_ref="synthetic")
    db.add(account)
    employee = Employee(full_name="Synthetic employment employee", department="Production")
    other = Organization(name="Synthetic other employer", unp="123456789")
    db.add_all([employee, other])
    await db.flush()
    active = await bind(book[0], employee.id)
    foreign = await bind(other.id, employee.id)
    future = await bind(book[0], employee.id, contract_ref="SYN-EMP-FUTURE",
                        effective_from="2026-10-01")
    employee_id = employee.id
    await db.commit()

    prefix = f"/accounting/organizations/{book[0]}"
    path = prefix + "/manual-documents"
    listed = await client.get(
        f"{prefix}/manual-employees?on=2026-09-01&q=SYNTHETIC EMPLOYMENT")
    assert listed.status_code == 200 and listed.headers["cache-control"] == "private, no-store"
    assert listed.json()["items"] == [{**dimensions(active), "department": "Production"}]
    assert (await client.get(f"{prefix}/manual-employees?on=2026-09-01")).json()["items"] == []

    future_posting = posting("MANUAL-EMP-FUTURE", debit="42").model_dump(mode="json")
    future_posting["lines"][0]["dimensions"] = dimensions(future)
    assert (await client.post(prefix + "/preview", json=future_posting)).status_code == 422

    free_text = posting("MANUAL-EMP-FREE", debit="42").model_dump(mode="json")
    free_text["lines"][0]["dimensions"] = {
        "employee": "Synthetic employment employee", "department": "Production",
    }
    rejected_free_text = await client.post(prefix + "/preview", json=free_text)
    assert rejected_free_text.status_code == 422
    assert "complete current employment snapshot" in rejected_free_text.text
    assert (await client.post(path, json={"key": str(uuid4()), "posting": free_text})).status_code == 422
    assert (await client.post(prefix + "/entries", json=free_text)).status_code == 422

    non_string = posting("MANUAL-EMP-NON-STRING", debit="42").model_dump(mode="json")
    non_string["lines"][0]["dimensions"] = dimensions(active)
    non_string["lines"][0]["dimensions"]["employee_id"] = active["employee_id"]
    assert (await client.post(prefix + "/preview", json=non_string)).status_code == 422

    oversized = posting("MANUAL-EMP-OVERSIZED", debit="42").model_dump(mode="json")
    oversized["lines"][0]["dimensions"] = dimensions(active)
    oversized["lines"][0]["dimensions"]["employment_binding_id"] = "9" * 200
    oversized_result = await client.post(prefix + "/preview", json=oversized)
    assert oversized_result.status_code == 422
    assert "invalid employment snapshot key" in oversized_result.text

    forged = posting("MANUAL-EMP-FORGED", debit="42").model_dump(mode="json")
    forged["lines"][0]["dimensions"] = dimensions(active)
    forged["lines"][0]["dimensions"]["employee_binding_digest"] = "0" * 64
    assert (await client.post(prefix + "/preview", json=forged)).status_code == 422
    wrong_department = posting("MANUAL-EMP-DEPARTMENT", debit="42").model_dump(mode="json")
    wrong_department["lines"][0]["dimensions"] = dimensions(active)
    wrong_department["lines"][0]["dimensions"]["department"] = "Finance"
    assert (await client.post(prefix + "/preview", json=wrong_department)).status_code == 422

    foreign_posting = posting("MANUAL-EMP-FOREIGN", debit="42").model_dump(mode="json")
    foreign_posting["lines"][0]["dimensions"] = dimensions(foreign)
    assert (await client.post(prefix + "/preview", json=foreign_posting)).status_code == 422
    assert (await client.post(path, json={"key": str(uuid4()), "posting": foreign_posting})).status_code == 422
    assert (await client.post(prefix + "/entries", json=foreign_posting)).status_code == 422

    current_posting = posting("MANUAL-EMP-REVISION", debit="42").model_dump(mode="json")
    current_posting["lines"][0]["dimensions"] = dimensions(active)
    saved = await client.post(path, json={"key": str(uuid4()), "posting": current_posting})
    assert saved.status_code == 201, saved.text
    document_id = saved.json()["id"]

    await db.refresh(employee)
    employee.department = "Assembly"
    await db.flush()
    revised_binding = await bind(book[0], employee_id)
    await db.commit()
    stale_post = await client.post(f"{path}/{document_id}/post", json={
        "key": str(uuid4()), "expected_version": 1,
        "digest": service.digest(PostingInput.model_validate(current_posting)),
    })
    assert stale_post.status_code == 422 and "select the current employee again" in stale_post.text
    current_posting["lines"][0]["dimensions"] = dimensions(revised_binding)
    edited = await client.put(f"{path}/{document_id}", json={
        "key": str(uuid4()), "expected_version": 1, "posting": current_posting,
    })
    assert edited.status_code == 200 and edited.json()["version"] == 2
    post_command = {"key": str(uuid4()), "expected_version": 2,
                    "digest": service.digest(PostingInput.model_validate(current_posting))}
    confirmed = await client.post(f"{path}/{document_id}/post", json=post_command)
    assert confirmed.status_code == 200, confirmed.text

    ended = await bind(book[0], employee_id, state="ended")
    await db.commit()
    ended_posting = posting("MANUAL-EMP-ENDED", debit="42").model_dump(mode="json")
    ended_posting["lines"][0]["dimensions"] = dimensions(ended)
    assert (await client.post(prefix + "/preview", json=ended_posting)).status_code == 422
    assert (await client.post(path, json={"key": str(uuid4()), "posting": ended_posting})).status_code == 422
    assert (await client.post(prefix + "/entries", json=ended_posting)).status_code == 422

    replay_preview = await client.post(prefix + "/preview", json=current_posting)
    assert replay_preview.status_code == 200, replay_preview.text
    replay = await client.post(prefix + "/entries", json=current_posting)
    assert replay.status_code == 201 and replay.json()["id"] == confirmed.json()["entry_id"]
    posted_replay = await client.post(f"{path}/{document_id}/post", json=post_command)
    assert posted_replay.status_code == 200 and posted_replay.json()["entry_id"] == confirmed.json()["entry_id"]


async def test_manual_asset_snapshot_requires_exact_company_register_row_and_keeps_replay(
        client, db, book, posting):
    from copy import deepcopy
    from datetime import date
    from decimal import Decimal
    from uuid import uuid4

    from modules.accounting import models
    from modules.accounting.schemas import PostingInput

    asset, source, source_line = await _registered_manual_asset(db, book, posting)
    foreign_org = models.Organization(name="Foreign asset owner", unp="888888888")
    db.add(foreign_org)
    await db.flush()
    foreign_asset = models.FixedAssetRegisterEntry(
        organization_id=foreign_org.id, request_key=str(uuid4()), asset_key="asset:foreign:001",
        source_entry_id=source.id, source_line_id=source_line.id, source_digest=source.digest,
        name="Чужое ОС", inventory_number="ОС-F-001", acquisition_date=date(2026, 9, 1),
        commissioning_date=date(2026, 9, 1), depreciation_start=date(2026, 9, 1),
        cost=Decimal("1200.00"), residual_value=Decimal("0.00"), useful_life_months=12,
        depreciation_method="straight_line", asset_account="01.1", accumulated_account="02.1",
        expense_account="26", dimensions={}, evidence="Synthetic foreign asset fixture",
        command={}, digest="b" * 64, actor="tester",
    )
    db.add(foreign_asset)
    await db.commit()

    def snapshot(row):
        return {
            "asset": row.asset_key, "asset_register_id": str(row.id),
            "asset_digest": row.digest, "asset_name": row.name,
            "asset_inventory_number": row.inventory_number,
        }

    valid = snapshot(asset)
    invalid_snapshots = [{"asset": "unregistered free text"}, snapshot(foreign_asset),
                         {**valid, "asset_register_id": "2147483648"}]
    invalid_snapshots.extend({**valid, key: value + " forged"} for key, value in (
        ("asset", "forge-key"), ("asset_digest", "forge-digest"),
        ("asset_name", "forge-name"), ("asset_inventory_number", "forge-number"),
    ))
    prefix = f"/accounting/organizations/{book[0]}"
    for index, dimensions in enumerate(invalid_snapshots):
        payload = posting(f"MANUAL-ASSET-INVALID-{index}").model_dump(mode="json")
        payload["lines"][0]["dimensions"] = dimensions
        assert (await client.post(f"{prefix}/preview", json=payload)).status_code == 422
        assert (await client.post(f"{prefix}/manual-documents", json={
            "key": str(uuid4()), "posting": payload,
        })).status_code == 422
        assert (await client.post(f"{prefix}/entries", json=payload)).status_code == 422

    payload = posting("MANUAL-ASSET-VALID").model_dump(mode="json")
    payload["lines"][0]["dimensions"] = valid
    saved = await client.post(f"{prefix}/manual-documents", json={
        "key": str(uuid4()), "posting": payload,
    })
    assert saved.status_code == 201, saved.text
    document_id = saved.json()["id"]

    forged_edit = deepcopy(payload)
    forged_edit["lines"][0]["dimensions"]["asset_name"] = "Forged name"
    edit = await client.put(f"{prefix}/manual-documents/{document_id}", json={
        "key": str(uuid4()), "expected_version": 1, "posting": forged_edit,
    })
    assert edit.status_code == 422

    forged_posting = deepcopy(payload)
    forged_posting["source"] = "MANUAL-ASSET-FORGED-POST"
    forged_posting["lines"][0]["dimensions"]["asset_inventory_number"] = "Forged inventory"
    forged_input = PostingInput.model_validate(forged_posting)
    forged_document = models.ManualDocument(
        organization_id=book[0], source=forged_input.source,
        posting_date=forged_input.posting_date, version=1, create_key=str(uuid4()),
    )
    db.add(forged_document)
    await db.flush()
    forged_revision = models.ManualDocumentRevision(
        document_id=forged_document.id, version=1, request_key=str(uuid4()),
        posting=forged_input.model_dump(mode="json"), digest=service.digest(forged_input), actor="tester",
    )
    db.add(forged_revision)
    await db.commit()
    rejected_post = await client.post(f"{prefix}/manual-documents/{forged_document.id}/post", json={
        "key": str(uuid4()), "expected_version": 1, "digest": forged_revision.digest,
    })
    assert rejected_post.status_code == 422

    valid_input = PostingInput.model_validate(payload)
    post_command = {"key": str(uuid4()), "expected_version": 1,
                    "digest": service.digest(valid_input)}
    confirmed = await client.post(f"{prefix}/manual-documents/{document_id}/post", json=post_command)
    assert confirmed.status_code == 200, confirmed.text
    replay = await client.post(f"{prefix}/manual-documents/{document_id}/post", json=post_command)
    assert replay.status_code == 200 and replay.json()["entry_id"] == confirmed.json()["entry_id"]
    direct_replay = await client.post(f"{prefix}/entries", json=payload)
    assert direct_replay.status_code == 201 and direct_replay.json()["id"] == confirmed.json()["entry_id"]
