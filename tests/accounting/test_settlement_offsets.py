from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from modules.accounting import reports, service
from modules.accounting.models import SettlementOffsetReceipt
from tests.accounting.test_bank_documents import document as bank_document


def offset(bank_entry_id, policy_id, **changes):
    data = {
        "request_key": str(uuid4()),
        "bank_entry_id": bank_entry_id,
        "kind": "customer_advance",
        "target_document": "sales:document:customer-42",
        "target_account": "62",
        "target_dimensions": {
            "counterparty": "buyer-1",
            "contract": "contract-1",
            "settlement_document": "sales:document:customer-42",
        },
        "amount": "60.00",
        "document_date": "2026-09-03",
        "operation_date": "2026-09-03",
        "posting_date": "2026-09-03",
        "policy_id": policy_id,
        "evidence": "Signed advance allocation and target document evidence",
        "explanation": "Apply customer advance to the issued document",
    }
    data.update(changes)
    return data


async def make_advance_bank(client, book, amount="100.00"):
    response = await client.post(
        f"/accounting/organizations/{book[0]}/bank/confirm",
        json=bank_document(
            source="bank-customer-advance",
            statement_reference="statement-customer-advance",
            policy_id=book[1],
            settlement_account="60",
            amount=amount,
            settlement_dimensions={
                "counterparty": "buyer-1",
                "contract": "contract-1",
                "settlement_document": "customer-advance:buyer-1",
            },
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_supplier_advance_offset_uses_the_opposite_explicit_roles(client, book):
    bank = await client.post(
        f"/accounting/organizations/{book[0]}/bank/confirm",
        json=bank_document(
            direction="payment",
            source="bank-supplier-advance",
            statement_reference="statement-supplier-advance",
            policy_id=book[1],
            settlement_account="62",
            settlement_dimensions={
                "counterparty": "supplier-1",
                "contract": "contract-s",
                "settlement_document": "supplier-advance:supplier-1",
            },
        ),
    )
    assert bank.status_code == 201, bank.text
    command = offset(
        bank.json()["id"], book[1], kind="supplier_advance",
        target_document="purchase:document:supplier-42", target_account="60",
        target_dimensions={
            "counterparty": "supplier-1", "contract": "contract-s",
            "settlement_document": "purchase:document:supplier-42",
        },
    )
    preview = await client.post(
        f"/accounting/organizations/{book[0]}/settlement-offsets/preview", json=command,
    )
    assert preview.status_code == 200, preview.text
    assert [(line["account"], line["side"]) for line in preview.json()["posting"]["lines"]] == [
        ("62", "credit"), ("60", "debit"),
    ]
    confirmed = await client.post(
        f"/accounting/organizations/{book[0]}/settlement-offsets/confirm",
        json={**command, "basis_digest": preview.json()["basis_digest"], "digest": preview.json()["digest"]},
    )
    assert confirmed.status_code == 201, confirmed.text


async def test_customer_advance_offset_preview_confirm_replay_and_register(client, db, book):
    bank_entry_id = await make_advance_bank(client, book)
    command = offset(bank_entry_id, book[1])
    preview = await client.post(
        f"/accounting/organizations/{book[0]}/settlement-offsets/preview", json=command,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["basis"]["available_byn"] == "100.00"
    assert [(line["account"], line["side"], line["amount"]) for line in body["posting"]["lines"]] == [
        ("60", "debit", "60.00"), ("62", "credit", "60.00"),
    ]
    confirmation = {**command, "basis_digest": body["basis_digest"], "digest": body["digest"]}
    first = await client.post(
        f"/accounting/organizations/{book[0]}/settlement-offsets/confirm", json=confirmation,
    )
    second = await client.post(
        f"/accounting/organizations/{book[0]}/settlement-offsets/confirm", json=confirmation,
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["entry_id"] == second.json()["entry_id"]
    rows = (await db.scalars(select(SettlementOffsetReceipt))).all()
    assert len(rows) == 1
    assert rows[0].target_document == command["target_document"]
    assert rows[0].source_snapshot["settlement_account"] == "60"
    listed = await client.get(f"/accounting/organizations/{book[0]}/settlement-offsets")
    assert listed.status_code == 200 and len(listed.json()) == 1
    result = await reports.report(db, book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert result["balance"]["difference"] == "0.00"


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": "101.00"},
        {"target_dimensions": {"settlement_document": "other"}},
        {"target_dimensions": {"counterparty": "other", "settlement_document": "sales:document:customer-42"}},
        {"kind": "supplier_advance"},
    ],
)
async def test_advance_offset_fails_closed(client, book, changes):
    bank_entry_id = await make_advance_bank(client, book)
    response = await client.post(
        f"/accounting/organizations/{book[0]}/settlement-offsets/preview",
        json=offset(bank_entry_id, book[1], **changes),
    )
    assert response.status_code == 422


async def test_settlement_offset_is_not_a_generic_manual_operation(db, book, posting):
    data = posting(source="manual-offset", debit="60", credit="62", operation="settlement_offset")
    with pytest.raises(service.AccountingError, match="dedicated reviewed confirmation"):
        await service.post(db, book[0], data, "tester")
