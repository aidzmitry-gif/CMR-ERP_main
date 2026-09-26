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
