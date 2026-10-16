from sqlalchemy import func, select, text, update

from modules.accounting import models, service, shipment_commands, shipment_preview
from modules.accounting.schemas import PostingInput
from tests.accounting.test_shipment_commands import prepared


async def recorded(db, book, posting):
    receipt, data, plan = await prepared(db, book, posting)
    saved = await shipment_commands.confirm(
        db, book[0], receipt, data, plan["basis_digest"], "tester"
    )
    await db.commit()
    return saved


async def test_reader_can_inspect_saved_package_without_new_entries(db, book, posting, client):
    saved = await recorded(db, book, posting)
    await db.execute(
        update(models.AccessGrant)
        .where(models.AccessGrant.organization_id == book[0])
        .values(role="reader")
    )
    await db.commit()
    count = await db.scalar(select(func.count()).select_from(models.Entry))
    result = await client.get(
        f"/accounting/organizations/{book[0]}/entries/{saved.anchor_entry_id}/shipment-package"
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["id"] == saved.id and body["status"] == "recorded"
    assert body["snapshot"]["mapping"][0]["cost_byn"] == "3.33"
    assert body["snapshot"]["pages"][0]["entry_id"] == saved.anchor_entry_id
    assert body["confirmation_available"] is False and body["statutory_certified"] is False
    assert result.headers["cache-control"] == "private, no-store"
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == count


async def test_unknown_or_foreign_book_cannot_reveal_package(db, book, posting, client):
    saved = await recorded(db, book, posting)
    entry_id = saved.anchor_entry_id
    assert (
        await client.get(f"/accounting/organizations/{book[0]}/entries/999999/shipment-package")
    ).status_code == 404
    assert (
        await client.get(
            f"/accounting/organizations/{book[0] + 1}/entries/{entry_id}/shipment-package"
        )
    ).status_code == 403
    assert (
        await client.get(f"/accounting/organizations/{book[0]}/entries/1/shipment-package")
    ).status_code == 404


async def test_corrupt_package_is_not_presented_as_verified(db, book, posting, client):
    saved = await recorded(db, book, posting)
    # SQLite corruption simulation; real PostgreSQL immutable guards stay untouched.
    await db.execute(
        text("UPDATE line SET amount=amount+0.01 WHERE entry_id=:entry"),
        {"entry": saved.anchor_entry_id},
    )
    await db.commit()
    result = await client.get(
        f"/accounting/organizations/{book[0]}/entries/{saved.anchor_entry_id}/shipment-package"
    )
    assert result.status_code == 409


async def test_second_entry_resolves_the_whole_package(db, book, posting, client, monkeypatch):
    receipt, data, plan = await prepared(db, book, posting)
    first = plan["postings"][0]["posting"]
    # The first four lines are the two balanced inventory cost blocks.
    plan["postings"] = []
    for index, lines in enumerate([first["lines"][:4], first["lines"][4:]]):
        body = PostingInput(
            **{**first, "source": first["source"] + (":part:2" if index else ""), "lines": lines}
        )
        plan["postings"].append(
            {"posting": body.model_dump(mode="json"), "digest": service.digest(body)}
        )

    async def paginated_plan(*args, **kwargs):
        return plan

    monkeypatch.setattr(shipment_preview, "prepare", paginated_plan)
    saved = await shipment_commands.confirm(
        db, book[0], receipt, data, plan["basis_digest"], "tester"
    )
    await db.commit()
    child = saved.snapshot["pages"][1]["entry_id"]
    response = await client.get(
        f"/accounting/organizations/{book[0]}/entries/{child}/shipment-package"
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == saved.id
    assert len(response.json()["snapshot"]["pages"]) == 2
