import pytest
from sqlalchemy import func, select

from modules.accounting.bank_statement_csv import COLUMNS, CsvInput, preview
from modules.finance.models import BankTransaction

HEADER = ",".join(COLUMNS) + "\n"


def payload(rows):
    return dict(provider="synthetic-bank", account_code="BY-TEST", evidence="Synthetic account ownership",
                content=HEADER + rows)


def test_csv_errors_are_explicit_and_block_whole_package():
    data = CsvInput(**payload("one,receipt,2026-09-01,12.30,BYN,,,Sale\n"
                             "two,payment,2026-09-01,4.20,USD,,,Import\n"
                             "one,receipt,2026-09-01,12.30,BYN,,,Sale\n"))
    result = preview(1, data)
    assert not result["valid"]
    assert [e["record"] for e in result["errors"]] == [2, 3]
    assert result["totals"] == {"receipt": "12.30", "payment": "0.00"}


async def test_csv_atomic_import_and_replay(client, db, book):
    prefix = f"/accounting/organizations/{book[0]}/bank-statement/csv"
    data = payload("one,receipt,2026-09-01,12.30,BYN,,,Sale\n"
                   "two,payment,2026-09-01,4.20,BYN,,,Purchase\n")
    checked = await client.post(prefix + "/preview", json=data)
    assert checked.status_code == 200, checked.text
    assert checked.json()["totals"] == {"receipt": "12.30", "payment": "4.20"}
    assert await db.scalar(select(func.count()).select_from(BankTransaction)) == 0
    command = {**data, "preview_digest": checked.json()["preview_digest"]}
    first = await client.post(prefix + "/confirm", json=command)
    assert first.status_code == 200, first.text
    second = await client.post(prefix + "/confirm", json=command)
    assert second.json() == first.json()
    assert await db.scalar(select(func.count()).select_from(BankTransaction)) == 2


async def test_csv_conflict_rolls_back_preceding_new_rows(client, db, book):
    prefix = f"/accounting/organizations/{book[0]}/bank-statement/csv"

    async def send(data):
        checked = await client.post(prefix + "/preview", json=data)
        assert checked.status_code == 200, checked.text
        return await client.post(prefix + "/confirm", json={**data, "preview_digest": checked.json()["preview_digest"]})

    assert (await send(payload("old,receipt,2026-09-01,12.30,BYN,,,Sale\n"))).status_code == 200
    response = await send(payload("new,payment,2026-09-01,4.20,BYN,,,Purchase\n"
                                  "old,receipt,2026-09-01,99.00,BYN,,,Changed\n"))
    assert response.status_code == 422
    assert (await db.scalars(select(BankTransaction.source_external_id))).all() == ["old"]


@pytest.mark.parametrize("changed", ["content", "evidence", "account_code"])
async def test_csv_changed_basis_requires_new_preview(client, book, changed):
    prefix = f"/accounting/organizations/{book[0]}/bank-statement/csv"
    data = payload("one,receipt,2026-09-01,12.30,BYN,,,Sale\n")
    checked = (await client.post(prefix + "/preview", json=data)).json()
    command = {**data, "preview_digest": checked["preview_digest"]}
    command[changed] += "changed" if changed != "content" else "two,payment,2026-09-01,1.00,BYN,,,Fee\n"
    response = await client.post(prefix + "/confirm", json=command)
    assert response.status_code == 422
