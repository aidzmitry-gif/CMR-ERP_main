from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from modules.accounting import bank_account_mapping, bank_import
from modules.accounting.models import (
    Account,
    BankAccountMapping,
    BankImportReceipt,
    Entry,
    Line,
    Organization,
    SourceBinding,
)
from modules.accounting.schemas import BankAccountMappingCloseInput, BankAccountMappingInput
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


async def map_source(db, org_id, source, *, dimensions=None):
    account = await db.scalar(select(Account).where(
        Account.organization_id == org_id, Account.code == "51",
    ))
    mapping = BankAccountMapping(
        organization_id=org_id, provider=source.source_provider, external_account=source.account_code,
        currency=source.currency, valid_from=date(2026, 1, 1), valid_to=None, version=1,
        ledger_account_id=account.id, dimensions=dimensions or {},
        evidence="Synthetic bank mapping evidence", actor="tester",
    )
    db.add(mapping)
    await db.commit()
    return mapping


@pytest.mark.asyncio
async def test_imported_bank_transaction_posts_once_and_keeps_source_snapshot(client, db, book):
    source = BankTransaction(
        ext_id="BANK-EXT-1", occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN",
        payer_unp="191234567", payer_name="Buyer", purpose="Advance", account_code="main",
        source_provider="synthetic-bank",
    )
    db.add(source)
    await db.commit()
    db.add(SourceBinding(
        organization_id=book[0], source_type="finance_bank_transaction", source_id=source.id,
        ownership="own", evidence="Chief mapped the bank source to the pilot company",
        actor="tester",
    ))
    await db.commit()
    await map_source(db, book[0], source)
    snapshot = bank_import.source_snapshot(source)
    body = command(book, bank_import._digest(snapshot), source_transaction_id=source.id, bank_dimensions={})

    preview = await client.post(f"/accounting/organizations/{book[0]}/bank-import/preview", json=body)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["source_snapshot"]["ext_id"] == "BANK-EXT-1"
    assert plan["mapping"]["bank_account"] == "51"
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
    settlement_line = await db.scalar(select(Line).where(Line.entry_id == entry_id, Line.account_code == "62"))
    assert settlement_line.dimensions["counterparty"] == "buyer"
    assert settlement_line.dimensions["contract"] == "contract"
    from modules.accounting.closing_controls import snapshot as closing_snapshot

    controls = await closing_snapshot(db, book[0], "2026-09")
    assert not any(item["code"] == "unposted_bank_imports" for item in controls["blockers"])
    assert receipt.source_ext_id == "BANK-EXT-1"
    assert receipt.snapshot["source_digest"] == bank_import._digest(snapshot)
    assert receipt.snapshot["mapping"] == plan["mapping"]

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


async def test_bank_import_requires_own_binding_and_exact_registry_values(client, db, book):
    source = BankTransaction(
        ext_id="BANK-MAP-UNBOUND", occurred_on=date(2026, 9, 3), amount="80.00", currency="BYN",
        account_code="mapping-account", source_provider="synthetic-bank",
    )
    db.add(source)
    await db.commit()
    source_id = source.id
    body = command(book, bank_import._digest(bank_import.source_snapshot(source)), source_transaction_id=source_id,
                   bank_dimensions={})
    unbound = await client.post(f"/accounting/organizations/{book[0]}/bank-import/preview", json=body)
    assert unbound.status_code == 422
    assert "binding" in unbound.json()["detail"]

    other = Organization(name="Synthetic foreign bank owner", unp="888888888")
    db.add(other)
    await db.flush()
    db.add(SourceBinding(organization_id=other.id, source_type="finance_bank_transaction", source_id=source_id,
                         ownership="own", evidence="Synthetic foreign owner evidence", actor="tester"))
    await db.commit()
    foreign = await client.post(f"/accounting/organizations/{book[0]}/bank-import/preview", json=body)
    assert foreign.status_code == 422
    assert "binding" in foreign.json()["detail"]


async def test_bank_import_rejects_manual_mismatch_and_stale_mapping_confirm(client, db, book):
    source = BankTransaction(
        ext_id="BANK-MAP-STALE", occurred_on=date(2026, 9, 3), amount="90.00", currency="BYN",
        account_code="stale-account", source_provider="synthetic-bank",
    )
    db.add(source)
    await db.flush()
    db.add(SourceBinding(organization_id=book[0], source_type="finance_bank_transaction", source_id=source.id,
                         ownership="own", evidence="Synthetic own binding evidence", actor="tester"))
    await db.commit()
    mapping = await map_source(db, book[0], source)
    body = command(book, bank_import._digest(bank_import.source_snapshot(source)), source_transaction_id=source.id,
                   bank_dimensions={})
    mismatch = await client.post(f"/accounting/organizations/{book[0]}/bank-import/preview",
                                 json={**body, "bank_account": "41"})
    assert mismatch.status_code == 422
    assert "exactly match" in mismatch.json()["detail"]
    preview = await client.post(f"/accounting/organizations/{book[0]}/bank-import/preview", json=body)
    assert preview.status_code == 200, preview.text
    await bank_account_mapping.close(
        db, book[0], mapping.id,
        BankAccountMappingCloseInput(valid_to=date(2026, 9, 3), evidence="Synthetic stale mapping close evidence"),
    )
    await db.commit()
    stale = await client.post(f"/accounting/organizations/{book[0]}/bank-import/confirm",
                              json={**body, "basis_digest": preview.json()["basis_digest"],
                                    "digest": preview.json()["digest"]})
    assert stale.status_code == 409
    assert "mapping" in stale.json()["detail"]
    assert await db.scalar(select(BankImportReceipt.entry_id)) is None


async def test_used_mapping_cannot_close_or_create_successor(client, db, book):
    source = BankTransaction(
        ext_id="BANK-MAP-USED", occurred_on=date(2026, 9, 3), amount="100.00", currency="BYN",
        account_code="used-account", source_provider="synthetic-bank",
    )
    db.add(source)
    await db.flush()
    db.add(SourceBinding(organization_id=book[0], source_type="finance_bank_transaction", source_id=source.id,
                         ownership="own", evidence="Synthetic own binding evidence", actor="tester"))
    await db.commit()
    mapping = await map_source(db, book[0], source)
    body = command(book, bank_import._digest(bank_import.source_snapshot(source)), source_transaction_id=source.id,
                   bank_dimensions={})
    preview = await client.post(f"/accounting/organizations/{book[0]}/bank-import/preview", json=body)
    confirmed = await client.post(
        f"/accounting/organizations/{book[0]}/bank-import/confirm",
        json={**body, "basis_digest": preview.json()["basis_digest"], "digest": preview.json()["digest"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    with pytest.raises(HTTPException, match="already used"):
        await bank_account_mapping.close(
            db, book[0], mapping.id,
            BankAccountMappingCloseInput(valid_to=date(2026, 9, 3), evidence="Synthetic used close evidence"),
        )
    account = await db.get(Account, mapping.ledger_account_id)
    with pytest.raises(HTTPException, match="already used"):
        await bank_account_mapping.create(
            db, book[0], BankAccountMappingInput(
                provider=source.source_provider, external_account=source.account_code, currency="BYN",
                valid_from=date(2026, 9, 3), ledger_account_id=account.id, dimensions={},
                evidence="Synthetic used successor evidence",
            ), "tester",
        )


async def test_legacy_receipt_without_mapping_fingerprint_replays(client, db, book):
    source = BankTransaction(
        ext_id="BANK-MAP-LEGACY", occurred_on=date(2026, 9, 3), amount="100.00", currency="BYN",
        account_code="legacy-account", source_provider="synthetic-bank",
    )
    db.add(source)
    await db.flush()
    source_id = source.id
    db.add(SourceBinding(organization_id=book[0], source_type="finance_bank_transaction", source_id=source_id,
                         ownership="own", evidence="Synthetic own binding evidence", actor="tester"))
    await db.commit()
    await map_source(db, book[0], source)
    body = command(book, bank_import._digest(bank_import.source_snapshot(source)), source_transaction_id=source_id,
                   bank_dimensions={})
    preview = await client.post(f"/accounting/organizations/{book[0]}/bank-import/preview", json=body)
    confirmed = await client.post(
        f"/accounting/organizations/{book[0]}/bank-import/confirm",
        json={**body, "basis_digest": preview.json()["basis_digest"], "digest": preview.json()["digest"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    receipt = await db.scalar(select(BankImportReceipt).where(
        BankImportReceipt.source_transaction_id == source_id,
    ))
    legacy_snapshot = dict(receipt.snapshot)
    legacy_snapshot.pop("mapping")
    await db.execute(update(BankImportReceipt).where(BankImportReceipt.entry_id == receipt.entry_id).values(
        snapshot=legacy_snapshot,
    ))
    await db.commit()
    db.expire_all()
    replay = await client.post(
        f"/accounting/organizations/{book[0]}/bank-import/confirm",
        json={**body, "basis_digest": preview.json()["basis_digest"], "digest": preview.json()["digest"]},
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["entry_id"] == confirmed.json()["entry_id"]


async def test_newer_effective_account_makes_mapping_confirm_stale(client, db, book):
    source = BankTransaction(
        ext_id="BANK-MAP-ACCOUNT-STALE", occurred_on=date(2026, 9, 3), amount="100.00", currency="BYN",
        account_code="account-stale", source_provider="synthetic-bank",
    )
    db.add(source)
    await db.flush()
    source_id = source.id
    db.add(SourceBinding(organization_id=book[0], source_type="finance_bank_transaction", source_id=source_id,
                         ownership="own", evidence="Synthetic own binding evidence", actor="tester"))
    await db.commit()
    mapping = await map_source(db, book[0], source)
    body = command(book, bank_import._digest(bank_import.source_snapshot(source)), source_transaction_id=source_id,
                   bank_dimensions={})
    preview = await client.post(f"/accounting/organizations/{book[0]}/bank-import/preview", json=body)
    assert preview.status_code == 200, preview.text
    original = await db.get(Account, mapping.ledger_account_id)
    db.add(Account(organization_id=book[0], code=original.code, title="Newer bank cash account",
                   category="asset", valid_from=date(2026, 9, 3), required_dimensions=[],
                   currency_tracking=True, quantity_tracking=False, cash=True,
                   normative_ref="Synthetic stale-account successor"))
    await db.commit()
    stale = await client.post(
        f"/accounting/organizations/{book[0]}/bank-import/confirm",
        json={**body, "basis_digest": preview.json()["basis_digest"], "digest": preview.json()["digest"]},
    )
    assert stale.status_code == 409
    assert "mapping" in stale.json()["detail"]
    assert await db.scalar(select(BankImportReceipt.entry_id).where(
        BankImportReceipt.source_transaction_id == source_id,
    )) is None


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


@pytest.mark.parametrize("amount", ["NaN", "sNaN", "Infinity", "-Infinity", None, True, "invalid"])
def test_bank_snapshot_rejects_invalid_money(amount):
    source = BankTransaction(ext_id="INVALID", occurred_on=date(2026, 9, 3), amount=amount, currency="BYN")
    with pytest.raises(bank_import.service.AccountingError, match="invalid monetary amount"):
        bank_import.source_snapshot(source)


async def test_bank_source_refreshes_previously_loaded_amount(db, book):
    source = BankTransaction(ext_id="CHANGED", occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN")
    db.add(source)
    await db.flush()
    db.add(SourceBinding(organization_id=book[0], source_type="finance_bank_transaction",
        source_id=source.id, ownership="own", evidence="Explicit test source", actor="tester"))
    await db.commit()
    await db.execute(update(BankTransaction).where(BankTransaction.id == source.id)
        .values(amount="240.00").execution_options(synchronize_session=False))
    await db.commit()
    assert str(source.amount) == "120.00"
    _, snapshot, _ = await bank_import._source(db, book[0], source.id)
    assert snapshot["amount"] == "240.00"


def test_invalid_bank_snapshot_can_be_displayed_without_a_postable_amount():
    source = BankTransaction(ext_id="INVALID-LIST", occurred_on=date(2026, 9, 3), amount="NaN", currency="BYN")
    assert bank_import.source_snapshot(source, allow_invalid=True)["amount"] is None


async def test_bank_candidates_exclude_rows_bound_to_another_company(db, book):
    from modules.accounting.models import Organization

    other = Organization(name="Other company", unp="999999995")
    db.add(other)
    source = BankTransaction(ext_id="PRIVATE-OTHER", occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN")
    db.add(source)
    await db.flush()
    db.add(SourceBinding(organization_id=other.id, source_type="finance_bank_transaction",
        source_id=source.id, ownership="own", evidence="Other company statement", actor="tester"))
    await db.commit()
    result = await bank_import.list_candidates(db, book[0])
    assert all(x["source_snapshot"]["transaction_id"] != source.id for x in result)


@pytest.mark.parametrize("role", ["reader", "accountant"])
async def test_only_chief_can_view_unassigned_bank_sources(client, db, book, role):
    from modules.accounting.models import AccessGrant

    source = BankTransaction(ext_id="UNASSIGNED", occurred_on=date(2026, 9, 3), amount="80.00", currency="BYN")
    db.add(source)
    await db.execute(update(AccessGrant).where(AccessGrant.organization_id == book[0]).values(role=role))
    await db.commit()
    url = f"/accounting/organizations/{book[0]}/bank-import/candidates"
    response = await client.get(url)
    assert response.status_code == 200 and response.json() == []
    db.add(SourceBinding(organization_id=book[0], source_type="finance_bank_transaction", source_id=source.id,
        ownership="own", evidence="Explicit chief mapping", actor="tester"))
    await db.commit()
    own = await client.get(url)
    assert own.status_code == 200
    assert [x["source_snapshot"]["transaction_id"] for x in own.json()] == [source.id]


@pytest.mark.asyncio
async def test_owned_unposted_bank_source_blocks_month_close(client, db, book):
    from modules.accounting import closing_controls, service
    from modules.accounting.schemas import CloseInput

    source = BankTransaction(ext_id="CLOSE-BANK", occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN")
    db.add(source)
    await db.commit()
    before = await closing_controls.snapshot(db, book[0], "2026-09")
    assert not any(item["code"] == "unposted_bank_imports" for item in before["blockers"])
    db.add(SourceBinding(organization_id=book[0], source_type="finance_bank_transaction", source_id=source.id,
                         ownership="own", evidence="Explicit synthetic ownership", actor="tester"))
    await db.commit()
    controls = await closing_controls.snapshot(db, book[0], "2026-09")
    assert next(item["count"] for item in controls["blockers"] if item["code"] == "unposted_bank_imports") == 1
    with pytest.raises(service.AccountingError, match="Unposted imported bank"):
        await service.validate_close_period(db, book[0], "2026-09", CloseInput(
            expected_generation=controls["period"]["generation"], evidence={key: "Verified fixture" for key in service.CLOSE_STEPS}))
    source.occurred_on = date(2026, 10, 1)
    await db.commit()
    later = await closing_controls.snapshot(db, book[0], "2026-09")
    assert not any(item["code"] == "unposted_bank_imports" for item in later["blockers"])
    source.occurred_on = None
    await db.commit()
    undated = await closing_controls.snapshot(db, book[0], "2026-09")
    assert any(item["code"] == "unposted_bank_imports" for item in undated["blockers"])


@pytest.mark.asyncio
@pytest.mark.parametrize("occurred_on,expected_status", [(date(2026, 9, 3), 409), (date(2026, 8, 31), 409), (None, 409), (date(2026, 10, 1), 201)])
async def test_new_bank_binding_cannot_invalidate_closed_period(client, db, book, occurred_on, expected_status):
    from modules.accounting.models import Period

    db.add(Period(organization_id=book[0], month="2026-09", closed=True, generation=0))
    source = BankTransaction(ext_id="CLOSED-BIND", occurred_on=occurred_on, amount="120.00", currency="BYN")
    db.add(source)
    await db.commit()
    source_id = source.id
    result = await client.post(f"/accounting/organizations/{book[0]}/source-bindings", json={
        "source_type": "finance_bank_transaction", "source_id": source.id, "ownership": "own", "evidence": "Synthetic bank ownership decision",
    })
    assert result.status_code == expected_status, result.text
    saved = await db.scalar(select(SourceBinding.id).where(SourceBinding.source_id == source_id))
    assert (saved is not None) == (expected_status == 201)


@pytest.mark.asyncio
async def test_existing_bank_binding_replays_after_period_closes(client, db, book):
    from modules.accounting.models import Period

    source = BankTransaction(ext_id="REPLAY-BIND", occurred_on=date(2026, 9, 3), amount="120.00", currency="BYN")
    db.add(source)
    await db.commit()
    body = {"source_type": "finance_bank_transaction", "source_id": source.id, "ownership": "own", "evidence": "Synthetic replay decision"}
    url = f"/accounting/organizations/{book[0]}/source-bindings"
    first = await client.post(url, json=body)
    assert first.status_code == 201, first.text
    db.add(Period(organization_id=book[0], month="2026-09", closed=True, generation=0))
    await db.commit()
    replay = await client.post(url, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]


@pytest.mark.asyncio
async def test_report_stays_preliminary_for_owned_unposted_bank_source(db, book):
    from modules.accounting.models import Period
    from modules.accounting.reports import report

    # Legacy state before bank closing guards: closed period with an unposted source.
    db.add(Period(organization_id=book[0], month="2026-09", closed=True, generation=0))
    source = BankTransaction(ext_id="REPORT-BANK", occurred_on=date(2026, 9, 20), amount="120.00", currency="BYN")
    db.add(source)
    await db.flush()
    db.add(SourceBinding(organization_id=book[0], source_type="finance_bank_transaction", source_id=source.id,
                         ownership="own", evidence="Synthetic legacy report source", actor="tester"))
    await db.commit()
    monthly = await report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert monthly["status"] == "preliminary"
    assert monthly["pending_documents"] == 1
    before_source = await report(db, book[0], date(2026, 9, 1), date(2026, 9, 19))
    assert before_source["pending_documents"] == 0
    source.occurred_on = None
    await db.commit()
    undated = await report(db, book[0], date(2026, 9, 1), date(2026, 9, 19))
    assert undated["pending_documents"] == 1
    assert undated["status"] == "preliminary"
