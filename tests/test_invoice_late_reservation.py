import asyncio
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from core.services.auth import CurrentUser
from modules.sales.access import DealAccess
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt, InvoiceLateReservationReceipt
from modules.sales.invoice_late_reservation import LateReservationInput, reserve_later
from modules.sales.models import DealDocument, DealItem
from modules.sales.reservation_source import SalesReservationSource
from modules.wms.models import ReservationVersion, StockMovement
from tests.test_invoice_issuance import create, seed


async def late_reservation_flow(api, session, *, concurrent=False):
    ids, base = await seed(api, session, physical="0")
    # An empty warehouse is not a synthetic zero-quantity movement.
    await session.execute(delete(StockMovement).where(StockMovement.organization_id == ids["org"]))
    await session.commit()
    base["reserve_mode"] = "on_order"
    base["valid_until"] = (date.today() + timedelta(days=5)).isoformat()
    p = (await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)).json()
    issued = await create(api, ids, {**base, "request_key": "initial-on-order", "expected_document_version": p["document_version"],
        "expected_basis_digest": p["basis_digest"], "allocations": [], "unreserved_confirmed": True})
    assert issued.status_code == 201, issued.text
    result = issued.json()
    doc_id = result["document"]["id"]
    doc = await session.get(DealDocument, doc_id)
    original = (doc.original_html, deepcopy(doc.snapshot_json), doc.content_sha256)
    receipt = await session.get(InvoiceIssuanceReceipt, doc_id)
    original_response = deepcopy(receipt.response)
    data = LateReservationInput(organization_id=ids["org"], request_key="later-reserve-original",
        expected_document_version=1, expected_content_sha256=result["content_sha256"],
        allocations=[{"line_no": 1, "warehouse": "W", "qty": "2.00"}], evidence="Confirmed arrival and complete journal", journal_complete=True)
    core = api._transport.app.state.core
    user, access = CurrentUser("issuer", ["director"]), DealAccess("all")
    with pytest.raises(HTTPException, match="Ожидаемый остаток неизвестен"):
        await reserve_later(session, core, user, access, ids["deal"], doc_id, data)
    await session.rollback()
    assert await session.scalar(select(func.count()).select_from(InvoiceLateReservationReceipt)) == 0
    session.add(StockMovement(organization_id=ids["org"], sku_code=ids["code"], warehouse="W", kind="in", qty=Decimal("2"), reason="receipt"))
    await session.commit()
    for changes, status in (({"expected_document_version": 2}, 409), ({"journal_complete": False}, 422)):
        with pytest.raises(HTTPException) as rejected:
            await reserve_later(session, core, user, access, ids["deal"], doc_id,
                                data.model_copy(update=changes))
        assert rejected.value.status_code == status
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(InvoiceLateReservationReceipt)) == 0
        assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 0
        assert (await session.get(DealDocument, doc_id)).reserve_status == "unreserved"
        await session.commit()
    endpoint = f"/sales/deals/{ids['deal']}/documents/{doc_id}/reservation"
    item = await session.scalar(select(DealItem).where(DealItem.deal_id == ids["deal"]))
    item.qty = Decimal("99")
    await session.commit()
    preview_body = {k: data.model_dump(mode="json")[k] for k in (
        "organization_id", "expected_document_version", "expected_content_sha256")}
    available = await api.post(endpoint + "-preview", json=preview_body)
    assert available.status_code == 200, available.text
    assert available.headers["cache-control"] == "private, no-store"
    assert available.json()["lines"] == original[1]["items"]
    assert available.json()["lines"][0]["qty"] == "2.00"
    assert available.json()["availability"]["organization_id"] == ids["org"]
    wrong_preview = await api.post(endpoint + "-preview", json={**preview_body, "expected_document_version": 9})
    assert wrong_preview.status_code == 409, wrong_preview.text
    denied = await api.post(endpoint, json=data.model_dump(mode="json"),
                            headers={"X-User": "outsider", "X-User-Roles": "viewer"})
    assert denied.status_code == 403, denied.text
    invalid = await api.post(endpoint, json={**data.model_dump(mode="json"), "journal_complete": False})
    assert invalid.status_code == 422, invalid.text
    missing = await api.post(f"/sales/deals/{ids['deal']}/documents/999999/reservation",
                             json=data.model_dump(mode="json"))
    assert missing.status_code == 404, missing.text
    if concurrent:
        responses = await asyncio.gather(*(api.post(endpoint, json=data.model_dump(mode="json")) for _ in range(2)))
        assert sorted(r.status_code for r in responses) == [200, 201], [r.text for r in responses]
        response = next(r for r in responses if r.status_code == 201)
        assert next(r for r in responses if r.status_code == 200).json() == {**response.json(), "replayed": True}
    else:
        response = await api.post(endpoint, json=data.model_dump(mode="json"))
    assert response.status_code == 201, response.text
    reserved = response.json()
    assert reserved["document"]["reserve_status"] == "reserved"
    assert reserved["document"]["reserve_mode"] == "on_order"
    repeated = await api.post(endpoint, json=data.model_dump(mode="json"))
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == {**reserved, "replayed": True}
    session.expire_all()
    await session.commit()
    assert await session.scalar(select(func.count()).select_from(ReservationVersion)) == 1
    assert await session.scalar(select(func.count()).select_from(StockMovement).where(
        StockMovement.organization_id == ids["org"])) == 1
    receipt = await session.get(InvoiceIssuanceReceipt, doc_id)
    assert receipt.reservation_digest is None and receipt.response == original_response
    doc = await session.get(DealDocument, doc_id)
    assert (doc.original_html, doc.snapshot_json, doc.content_sha256) == original
    source = await SalesReservationSource().invoice_shipping_source(session, doc_id, organization_id=ids["org"],
        expected_version=1, expected_content_sha256=result["content_sha256"])
    assert source["fulfillment_allowed"] and source["reservation_digest"] == reserved["reservation_digest"]
    await session.commit()
    with pytest.raises(HTTPException, match="another command"):
        await reserve_later(session, core, user, access, ids["deal"], doc_id,
                            data.model_copy(update={"evidence": "Different evidence"}))
    await session.rollback()
    return ids, doc_id, result["content_sha256"]


async def test_later_reservation_preserves_original_and_replays(api, session):
    await late_reservation_flow(api, session)
