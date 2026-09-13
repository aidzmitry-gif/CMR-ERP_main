from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from modules.accounting import bank_import
from modules.accounting.models import BankImportReceipt, Entry, SourceBinding
from modules.finance.models import BankTransaction


def command(book, source_digest, **changes):
    data = {
        "request_key": str(uuid4()),
        "source_transaction_id": 1,
        "source_digest": source_digest,
        "policy_id": book[1],
        "bank_account": "51",
        "settlement_account": "62",
        "bank_dimensions": {"bank_statement": "ignored-by-source"},
        "settlement_dimensions": {"counterparty": "buyer", "contract": "contract"},
        "posting_date": "2026-09-04",
        "cash_activity": "operating",
        "explanation": "Review imported bank receipt before posting",
    }
    data.update(changes)
    return data


@pytest.mark.asyncio
async def test_imported_bank_transaction_posts_once_and_keeps_source_snapshot(client, db, book):
    source = BankTransaction(
        ext_id="BANK-EXT-1", occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN",
        payer_unp="191234567", payer_name="Buyer", purpose="Advance", account_code="main",
    )
    db.add(source)
    await db.commit()
    db.add(SourceBinding(
        organization_id=book[0], source_type="finance_bank_transaction", source_id=source.id,
        ownership="own", evidence="Chief mapped the bank source to the pilot company",
        actor="tester",
    ))
    await db.commit()
    snapshot = bank_import.source_snapshot(source)
    body = command(book, bank_import._digest(snapshot), source_transaction_id=source.id)

    preview = await client.post(f"/accounting/organizations/{book[0]}/bank-import/preview", json=body)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["source_snapshot"]["ext_id"] == "BANK-EXT-1"
    assert plan["posting"]["lines"][0]["dimensions"]["bank_statement"] == "BANK-EXT-1"
    assert plan["posted"] is False

    confirmed = await client.post(
        f"/accounting/organizations/{book[0]}/bank-import/confirm",
        json={**body, "basis_digest": plan["basis_digest"], "digest": plan["digest"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    entry_id = confirmed.json()["entry_id"]
    assert (await db.scalar(select(Entry).where(Entry.id == entry_id))).operation == "bank_settlement"
    receipt = await db.scalar(select(BankImportReceipt).where(BankImportReceipt.entry_id == entry_id))
    assert receipt.source_ext_id == "BANK-EXT-1"
    assert receipt.snapshot["source_digest"] == bank_import._digest(snapshot)

    replay = await client.post(
        f"/accounting/organizations/{book[0]}/bank-import/confirm",
        json={**body, "basis_digest": plan["basis_digest"], "digest": plan["digest"]},
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["entry_id"] == entry_id
    assert await db.scalar(select(BankImportReceipt.entry_id)) == entry_id

    # Finance may update queue metadata after the ledger write.  A lost
    # response retry still returns the immutable accounting receipt.
    source.match_status = "matched"
    await db.commit()
    replay_after_match = await client.post(
        f"/accounting/organizations/{book[0]}/bank-import/confirm",
        json={**body, "basis_digest": plan["basis_digest"], "digest": plan["digest"]},
    )
    assert replay_after_match.status_code == 201, replay_after_match.text
    assert replay_after_match.json()["entry_id"] == entry_id


@pytest.mark.asyncio
async def test_imported_bank_transaction_requires_exact_current_source(client, db, book):
    source = BankTransaction(
        ext_id="BANK-EXT-2", occurred_on=date(2026, 9, 3), amount="50.00", currency="USD",
    )
    db.add(source)
    await db.commit()
    db.add(SourceBinding(
        organization_id=book[0], source_type="finance_bank_transaction", source_id=source.id,
        ownership="own", evidence="Chief mapped the bank source to the pilot company",
        actor="tester",
    ))
    await db.commit()
    body = command(book, "a" * 64, source_transaction_id=source.id)
    response = await client.post(f"/accounting/organizations/{book[0]}/bank-import/preview", json=body)
    assert response.status_code == 422
    assert "BYN" in response.text

    source.currency = "BYN"
    await db.commit()
    stale = await client.post(f"/accounting/organizations/{book[0]}/bank-import/preview", json=body)
    assert stale.status_code == 422
    assert "source snapshot" in stale.text


@pytest.mark.asyncio
async def test_bank_import_candidates_expose_digest_and_explicit_binding_state(client, db, book):
    source = BankTransaction(
        ext_id="BANK-EXT-CANDIDATE", occurred_on=date(2026, 9, 5), amount="75.00", currency="BYN",
        payer_name="Candidate buyer", purpose="Invoice advance",
    )
    db.add(source)
    await db.commit()

    response = await client.get(f"/accounting/organizations/{book[0]}/bank-import/candidates")
    assert response.status_code == 200, response.text
    candidate = next(row for row in response.json() if row["source_snapshot"]["ext_id"] == "BANK-EXT-CANDIDATE")
    assert candidate["binding_status"] == "unbound"
    assert candidate["imported"] is False
    assert candidate["source_digest"] == bank_import._digest(bank_import.source_snapshot(source))

    db.add(SourceBinding(
        organization_id=book[0], source_type="finance_bank_transaction", source_id=source.id,
        ownership="own", evidence="Chief mapped the bank source to the pilot company", actor="tester",
    ))
    await db.commit()
    response = await client.get(f"/accounting/organizations/{book[0]}/bank-import/candidates")
    candidate = next(row for row in response.json() if row["source_snapshot"]["ext_id"] == "BANK-EXT-CANDIDATE")
    assert candidate["binding_status"] == "own"
