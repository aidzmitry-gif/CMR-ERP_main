from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from core.services.auth import CurrentUser
from modules.accounting.gateway import AccountingService
from modules.sales.models import DealDocument
from modules.sales.reservation_source import SalesReservationSource
from modules.wms.invoice_remainder import RemainderRelease, RemainderReleaseLine
from modules.wms.invoice_reservations import ReserveInput, invoice_availability, reserve
from modules.wms.invoice_shipments import PhysicalShipmentAct
from modules.wms.models import StockMovement, Task
from modules.wms.reservation_events import apply
from tests.reservation_source import invoice
from tests.test_invoice_physical_shipments import endpoint, request


async def prepared_six(api, session):
    api.headers["X-User"] = "allocator"
    response = await api.post('/accounting/organizations', json={"name": "Remainder test", "unp": "999999978"})
    assert response.status_code == 201, response.text
    org = response.json()['id']
    await invoice(session, 1, [{"sku_code": "A", "qty": "3"}, {"sku_code": "A", "qty": "3"}], org)
    session.add(StockMovement(organization_id=org, sku_code="A", warehouse="W", kind="in", qty=10, reason="receipt"))
    await session.commit()
    actor = await AccountingService().source_member(session, org, CurrentUser("allocator", ["director"]))
    facts = await SalesReservationSource().invoice_reservation(session, 1)
    await reserve(session, org, facts, ReserveInput(allocations=[
        {"line_no": i, "warehouse": "W", "qty": "3"} for i in (1, 2)], journal_complete=True,
        evidence="Synthetic complete journal"), actor)
    await apply(session, 1, [("A", "W", Decimal("3")), ("A", "W", Decimal("3"))], organization_id=org, release=False)
    await session.commit()
    return org, facts


def release_url(org, document=1):
    return f"/wms/organizations/{org}/invoices/{document}/remainder-release"


async def release_request(api, org, facts):
    identity = {"expected_version": facts['version'], "expected_content_sha256": facts['content_sha256']}
    preview = await api.post(release_url(org) + '/preview', json=identity)
    assert preview.status_code == 200, preview.text
    return {**identity, "source_key": str(uuid4()), "expected_basis_digest": preview.json()['basis_digest'],
            "evidence": "Customer declined the unshipped remainder"}


async def partial(api, org, facts, qty="2.00"):
    shipment = await request(api, org, facts, [{"line_no": 1, "warehouse": "W", "qty": qty}])
    response = await api.post(endpoint(org), json=shipment)
    assert response.status_code == 201, response.text
    return shipment, response.json()


async def test_ten_six_two_four_replay_preserves_physical_original_and_acts(api, session):
    org, facts = await prepared_six(api, session)
    doc = await session.get(DealDocument, 1)
    original = (doc.original_html, doc.content_sha256, deepcopy(doc.snapshot_json), doc.status, doc.reserve_status)
    shipment, act = await partial(api, org, facts)
    body = await release_request(api, org, facts)
    first = await api.post(release_url(org), json=body)
    assert first.status_code == 201, first.text
    assert sum(Decimal(r['qty']) for r in first.json()['snapshot']['lines']) == 4
    assert (await api.post(release_url(org), json=body)).json() == first.json()
    assert (await api.post(endpoint(org), json=shipment)).json() == act
    identity = {"expected_version": facts['version'], "expected_content_sha256": facts['content_sha256']}
    preview = await api.post(endpoint(org) + '/preview', json=identity)
    assert preview.status_code == 200, preview.text
    assert {r['blocking_reason'] for r in preview.json()['lines']} == {'remainder_released'}
    assert (await api.post(endpoint(org), json={**shipment, 'source_key': str(uuid4())})).status_code == 409
    await session.refresh(doc)
    assert original == (doc.original_html, doc.content_sha256, doc.snapshot_json, doc.status, doc.reserve_status)
    availability = await invoice_availability(session, org, ['A'])
    row = availability['rows'][0]
    assert (Decimal(row['physical']), Decimal(row['reserved']), Decimal(row['free'])) == (8, 0, 8)
    assert await session.scalar(select(func.count()).select_from(PhysicalShipmentAct)) == 1
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == 2
    assert await session.scalar(select(func.count()).select_from(RemainderRelease)) == 1
    assert await session.scalar(select(func.count()).select_from(RemainderReleaseLine)) == 2
    assert all(t.status == 'canceled' for t in (await session.scalars(select(Task))).all())
    await apply(session, 1, [("A", "W", Decimal("3")), ("A", "W", Decimal("3"))], organization_id=org, release=False)
    assert all(t.status == 'canceled' for t in (await session.scalars(select(Task))).all())
    assert (await api.post(release_url(org), json={**body, 'source_key': str(uuid4())})).status_code == 409


@pytest.mark.parametrize('change', ['key_body', 'version', 'original', 'basis', 'organization', 'document', 'blank'])
async def test_rejection_is_atomic(api, session, change):
    org, facts = await prepared_six(api, session)
    await partial(api, org, facts)
    body = await release_request(api, org, facts)
    url = release_url(org)
    if change == 'key_body':
        assert (await api.post(url, json=body)).status_code == 201
        body['evidence'] = 'Changed body under same key'
    elif change == 'version':
        body['expected_version'] += 1
    elif change == 'original':
        body['expected_content_sha256'] = '0' * 64
    elif change == 'basis':
        body['expected_basis_digest'] = '0' * 64
    elif change == 'organization':
        url = release_url(999)
    elif change == 'document':
        url = release_url(org, 999)
    else:
        body['evidence'] = '  '
    response = await api.post(url, json=body)
    assert response.status_code in {403, 404, 409, 422}, response.text
    assert await session.scalar(select(func.count()).select_from(RemainderRelease)) == (1 if change == 'key_body' else 0)
    assert await session.scalar(select(func.count()).select_from(StockMovement)) == 2


async def test_no_act_and_full_shipment_do_not_release(api, session):
    org, facts = await prepared_six(api, session)
    identity = {"expected_version": facts['version'], "expected_content_sha256": facts['content_sha256']}
    assert (await api.post(release_url(org) + '/preview', json=identity)).status_code == 409
    body = await request(api, org, facts, [{"line_no": i, "warehouse": "W", "qty": "3"} for i in (1, 2)])
    assert (await api.post(endpoint(org), json=body)).status_code == 201
    assert (await api.post(release_url(org) + '/preview', json=identity)).status_code == 409


async def test_stale_preview_after_further_shipment(api, session):
    org, facts = await prepared_six(api, session)
    await partial(api, org, facts, '1')
    stale = await release_request(api, org, facts)
    await partial(api, org, facts, '1')
    assert (await api.post(release_url(org), json=stale)).status_code == 409
    fresh = await release_request(api, org, facts)
    assert (await api.post(release_url(org), json=fresh)).status_code == 201


async def test_failure_rolls_back_versions_and_receipt(api, session, monkeypatch):
    from modules.wms import invoice_remainder
    org, facts = await prepared_six(api, session)
    await partial(api, org, facts)
    body = await release_request(api, org, facts)
    async def fail(*args):
        raise RuntimeError('injected after release writes')
    monkeypatch.setattr(invoice_remainder, 'result', fail)
    with pytest.raises(RuntimeError, match='injected'):
        await api.post(release_url(org), json=body)
    await session.rollback()
    assert await session.scalar(select(func.count()).select_from(RemainderRelease)) == 0
    assert Decimal((await invoice_availability(session, org, ['A']))['rows'][0]['reserved']) == 4


async def test_corrupt_receipt_is_not_replayed(api, session):
    org, facts = await prepared_six(api, session)
    await partial(api, org, facts)
    body = await release_request(api, org, facts)
    assert (await api.post(release_url(org), json=body)).status_code == 201
    await session.execute(update(RemainderRelease).values(digest='0' * 64))
    await session.commit()
    assert (await api.post(release_url(org), json=body)).status_code == 409


async def test_foreign_reserve_and_pick_are_preserved(api, session):
    org, facts = await prepared_six(api, session)
    await invoice(session, 2, [{"sku_code": "A", "qty": "3"}], org)
    foreign = await SalesReservationSource().invoice_reservation(session, 2)
    await reserve(session, org, foreign, ReserveInput(allocations=[
        {"line_no": 1, "warehouse": "W", "qty": "3"}], journal_complete=True,
        evidence="Synthetic second order"), 'allocator')
    await apply(session, 2, [("A", "W", Decimal("3"))], organization_id=org, release=False)
    await session.commit()
    await partial(api, org, facts)
    body = await release_request(api, org, facts)
    response = await api.post(release_url(org), json=body)
    assert response.status_code == 201, response.text
    await AccountingService().lock_event_organization(session, org)
    row = (await invoice_availability(session, org, ['A']))['rows'][0]
    assert (row['physical'], row['reserved'], row['free']) == ('8.00', '3.00', '5.00')
    foreign_task = await session.scalar(select(Task).where(Task.doc_ref == 'sales:document:2'))
    assert foreign_task.status == 'open'


async def test_exhausted_line_is_not_released_or_relabelled(api, session):
    org, facts = await prepared_six(api, session)
    await partial(api, org, facts, '3')
    body = await release_request(api, org, facts)
    response = await api.post(release_url(org), json=body)
    assert response.status_code == 201, response.text
    assert [r['line_no'] for r in response.json()['snapshot']['lines']] == [2]
    identity = {"expected_version": facts['version'], "expected_content_sha256": facts['content_sha256']}
    preview = (await api.post(endpoint(org) + '/preview', json=identity)).json()
    assert [r['blocking_reason'] for r in preview['lines']] == ['fully_shipped', 'remainder_released']


async def test_read_only_role_cannot_release(api, session):
    org, facts = await prepared_six(api, session)
    await partial(api, org, facts)
    body = await release_request(api, org, facts)
    api.headers['X-User-Roles'] = 'logistics'
    assert (await api.post(release_url(org), json=body)).status_code == 403
    assert await session.scalar(select(func.count()).select_from(RemainderRelease)) == 0
