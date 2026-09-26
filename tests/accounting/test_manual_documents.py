from uuid import uuid4

from modules.accounting import service


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
