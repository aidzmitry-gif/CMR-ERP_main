from uuid import uuid4

from sqlalchemy import func, select, update

from modules.accounting.models import AccessGrant, Entry, ShipmentPreparationDraft, SourceControl


def payload():
    return {"act_digest": "a" * 64, "posting_date": "2026-09-01", "policy_id": None,
            "form": {"explanation": "Unfinished"}, "allocations": [], "terms": []}


async def pending(db, book):
    key = str(uuid4())
    db.add(SourceControl(organization_id=book[0], source=f"wms:physical-shipment:{book[0]}:{key}",
                         version=1, month="2026-09"))
    await db.commit()
    return f"/accounting/organizations/{book[0]}/shipments/{key}/draft"


async def test_draft_versions_replay_and_conflict_do_not_post(client, db, book):
    url = await pending(db, book)
    assert (await client.get(url)).json() == {"revision": 0, "draft": None}
    body = {"request_key": str(uuid4()), "expected_revision": 0, "payload": payload()}
    first = await client.post(url, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 1
    assert (await client.post(url, json=body)).json() == first.json()
    assert (await client.post(url, json={**body, "request_key": str(uuid4())})).status_code == 409
    changed = {**body, "payload": {**payload(), "form": {"explanation": "Changed"}}}
    assert (await client.post(url, json=changed)).status_code == 409
    second = await client.post(url, json={**changed, "request_key": str(uuid4()), "expected_revision": 1})
    assert second.status_code == 200 and second.json()["revision"] == 2
    latest = await client.get(url)
    assert latest.json() == second.json()
    assert latest.headers["cache-control"] == "private, no-store"
    assert await db.scalar(select(func.count()).select_from(Entry)) == 0
    assert await db.scalar(select(func.count()).select_from(ShipmentPreparationDraft)) == 2
    assert await db.scalar(select(SourceControl.entry_id)) is None


async def test_reader_can_read_but_not_save_and_foreign_book_is_denied(client, db, book):
    url = await pending(db, book)
    body = {"request_key": str(uuid4()), "expected_revision": 0, "payload": payload()}
    assert (await client.post(url, json=body)).status_code == 200
    await db.execute(update(AccessGrant).where(AccessGrant.organization_id == book[0]).values(role="reader"))
    await db.commit()
    assert (await client.get(url)).status_code == 200
    assert (await client.post(url, json=body)).status_code == 403
    assert (await client.get(url.replace(f"/organizations/{book[0]}/", "/organizations/999/"))).status_code == 403


async def test_missing_source_and_noninput_payload_rejected(client, db, book):
    body = {"request_key": str(uuid4()), "expected_revision": 0, "payload": payload()}
    url = f"/accounting/organizations/{book[0]}/shipments/{uuid4()}/draft"
    assert (await client.post(url, json=body)).status_code == 409
    url = await pending(db, book)
    assert (await client.post(url, json={**body, "payload": {**payload(), "postings": []}})).status_code == 422
