from datetime import date

from modules.accounting.models import Entry, Organization
from modules.procurement.receipt_documents import ReceiptDocument, ReceiptPosting


async def test_unlinked_purchase_register_is_scoped_and_cursor_paged(client, db, book):
    def purchase(source: str) -> Entry:
        return Entry(
            organization_id=book[0], source=source, source_version=1,
            operation="inventory_purchase", document_date=date(2026, 8, 1),
            operation_date=date(2026, 8, 2), posting_date=date(2026, 8, 3),
            policy_id=book[1], rule_version="synthetic", explanation="Test purchase",
            opening=False, correction_of=None, digest="a" * 64, actor="tester",
        )

    entries = [purchase(f"old-{i}") for i in range(4)]
    db.add_all(entries)
    other = Organization(name="Other test company", unp="888888888")
    db.add(other)
    await db.flush()

    own_document = ReceiptDocument(organization_id=book[0], source_key="own-linked",
                                   current_version=1, status="posted", created_by="tester")
    other_document = ReceiptDocument(organization_id=other.id, source_key="cross-book",
                                     current_version=1, status="posted", created_by="tester")
    db.add_all([own_document, other_document])
    await db.flush()
    db.add_all([
        ReceiptPosting(receipt_id=own_document.id, version=1, entry_id=entries[0].id,
                       options={}, digest="b" * 64, actor="tester"),
        ReceiptPosting(receipt_id=other_document.id, version=1, entry_id=entries[1].id,
                       options={}, digest="c" * 64, actor="tester"),
    ])
    await db.commit()

    url = f"/accounting/organizations/{book[0]}/purchases/unlinked-primary"
    first = await client.get(f"{url}?limit=2")
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "private, no-store"
    assert first.json()["organization_id"] == book[0]
    assert [row["entry_id"] for row in first.json()["rows"]] == [entries[3].id, entries[2].id]
    assert all(row["reason"] == "procurement_primary_not_linked" for row in first.json()["rows"])
    assert first.json()["next_after_id"] == entries[2].id

    second = await client.get(f"{url}?limit=2&after_id={first.json()['next_after_id']}")
    assert second.status_code == 200, second.text
    assert [row["entry_id"] for row in second.json()["rows"]] == [entries[1].id]
    assert second.json()["next_after_id"] is None
    assert entries[0].id not in [row["entry_id"] for row in first.json()["rows"] + second.json()["rows"]]
    assert (await client.get(f"/accounting/organizations/{other.id}/purchases/unlinked-primary")).status_code == 403
    assert (await client.get(f"{url}?limit=201")).status_code == 422
