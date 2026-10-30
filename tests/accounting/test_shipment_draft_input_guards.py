"""TN/TTN drafts keep exact source lines and reviewed directory identities."""
from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from core.domain.models import Counterparty
from modules.accounting import shipment_document_drafts as drafts
from modules.accounting.models import ShipmentPreparationDraft
from tests.accounting.test_shipment_document_drafts import body


@pytest.mark.parametrize("fields, message", [
    ({"sender_name": "Unreviewed free text"}, "unsupported TN/TTN fields"),
    ({"items": None}, "Invalid shipment item draft"),
    ({"items": [{}] * 10001}, "Invalid shipment item draft"),
    ({"items": [7]}, "Invalid shipment item draft"),
    ({"items": [{"line_no": 1, "sku": "unverified"}]}, "Invalid shipment item draft"),
    ({"items": [{"line_no": True}]}, "unique positive integers"),
    ({"items": [{"line_no": "1"}]}, "unique positive integers"),
    ({"items": [{"line_no": 0}]}, "unique positive integers"),
    ({"items": [{"line_no": 1}, {"line_no": 1}]}, "unique positive integers"),
    ({"items": [{"line_no": 1, "unit": 5}]}, "unit must be plain text"),
    ({"items": [{"line_no": 1, "unit": "x" * 501}]}, "unit must be plain text"),
    ({"document_number": None}, "document_number must be plain text"),
    ({"document_number": "synthetic\x00number"}, "document_number must be plain text"),
    ({"document_number": "\ud800"}, "Draft fields must contain plain text only"),
    ({"recipient_counterparty_id": True}, "must be a positive integer"),
    ({"contract_version": 0}, "must be a positive integer"),
    ({"contract_source": "procurement"}, "issued sales contracts"),
])
def test_draft_schema_refuses_untrusted_fields_without_coercion(fields, message):
    with pytest.raises(ValidationError) as error:
        drafts.ShipmentDocumentDraftInput.model_validate(body(**fields))
    assert message in str(error.value)


def test_draft_payload_limit_is_measured_in_encoded_bytes():
    fields = body()["fields"]
    fields["items"] = [{"line_no": n, "unit": "я" * 500, "unit_price": "x" * 500,
                        "vat_basis": "x" * 500} for n in range(1, 1301)]
    with pytest.raises(ValidationError) as error:
        drafts.ShipmentDocumentDraftInput.model_validate(body(**fields))
    assert "Draft exceeds 2 MB" in str(error.value)


@pytest.mark.parametrize("field, value, status, message", [
    ("recipient_counterparty_id", None, 409, "active counterparty directory"),
    ("recipient_counterparty_revision", False, 409, "active counterparty directory"),
    ("contract_source", "procurement", 409, "issued sales contract"),
    ("contract_id", None, 409, "current sales contract"),
    ("contract_version", 0, 409, "current sales contract"),
    ("contract_number", "", 409, "current sales contract"),
    ("contract_title", "   ", 409, "current sales contract"),
    ("contract_title", 7, 422, "plain text"),
    ("document_number", 7, 422, "plain text"),
    ("items", None, 422, "Invalid shipment item draft"),
    ("items", [7], 422, "Invalid shipment item draft"),
    ("items", [{"line_no": 1, "sku": "unverified"}], 422, "Invalid shipment item draft"),
    ("items", [{"line_no": True}], 422, "unique integers"),
    ("items", [{"line_no": 1}, {"line_no": 1}], 422, "unique integers"),
    ("items", [{"line_no": 2}], 409, "not in the verified shipment"),
    ("items", [{"line_no": 1, "unit_price": 7}], 422, "plain text"),
])
def test_normalization_never_guesses_recipient_contract_or_source_line(field, value, status, message):
    raw = body()["fields"]
    raw[field] = value
    package = {"prefilled": {"items": [{"line_no": 1}]}}
    original = deepcopy(raw), deepcopy(package)
    with pytest.raises(HTTPException) as error:
        drafts._normalize_request_fields(raw, "ttn", package)
    assert error.value.status_code == status and message in error.value.detail
    assert (raw, package) == original


@pytest.mark.parametrize("source_lines", [None, [], "unverified", [{"line_no": True}],
                                           [{"line_no": 0}], [{"line_no": "1"}],
                                           [{"line_no": 1}, {"line_no": 1}]])
def test_saved_draft_requires_positive_unique_verified_source_lines(source_lines):
    with pytest.raises(HTTPException) as error:
        drafts._normalize_request_fields(body()["fields"], "ttn", {"prefilled": {"items": source_lines}})
    assert error.value.status_code == 409 and "Verified shipment" in error.value.detail


def test_normalization_trims_only_user_text_and_keeps_verified_line_order():
    raw = body(document_number="  SYNTHETIC-17  ", items=[
        {"line_no": 2, "unit": " pack ", "unit_price": " 12.00 ", "vat_basis": " reviewed "},
        {"line_no": 1, "unit": " item ", "unit_price": " 1.00 ", "vat_basis": " reviewed "},
    ])["fields"]
    package = {"prefilled": {"items": [{"line_no": 1}, {"line_no": 2}]}}
    result = drafts._normalize_request_fields(raw, "ttn", package)
    assert result["document_number"] == "SYNTHETIC-17"
    assert [item["line_no"] for item in result["items"]] == [1, 2]
    assert result["items"][1] == {"line_no": 2, "unit": "pack", "unit_price": "12.00", "vat_basis": "reviewed"}
    assert result["recipient_counterparty_id"] == raw["recipient_counterparty_id"]
    assert result["contract_id"] == raw["contract_id"]


@pytest.mark.parametrize("problem, expected", [
    ("ok", 200), ("missing_book", 404), ("missing_recipient", 409),
    ("inactive", 409), ("merged", 409), ("revision_changed", 409),
])
async def test_party_snapshots_require_live_current_directory_records(db, book, problem, expected):
    recipient = Counterparty(
        name="Synthetic display name", legal_name="Synthetic legal name", unp="999999997",
        is_active=problem != "inactive", merged_into_id=1 if problem == "merged" else None,
    )
    db.add(recipient)
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(ShipmentPreparationDraft))
    arguments = (
        db, 999999 if problem == "missing_book" else book[0],
        999999 if problem == "missing_recipient" else recipient.id,
        recipient.revision + 1 if problem == "revision_changed" else recipient.revision,
    )
    if expected == 200:
        sender, buyer = await drafts._directory_snapshots(*arguments)
        assert sender["id"] == book[0] and buyer["id"] == recipient.id
        assert buyer["name"] == "Synthetic legal name" and buyer["revision"] == recipient.revision
    else:
        with pytest.raises(HTTPException) as error:
            await drafts._directory_snapshots(*arguments)
        assert error.value.status_code == expected
    assert await db.scalar(select(func.count()).select_from(ShipmentPreparationDraft)) == before
