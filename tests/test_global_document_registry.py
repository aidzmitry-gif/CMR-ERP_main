import hashlib
import json
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from core.domain.models import CatalogSourceIdentity, Sku, SyncLink
from modules.sales import document_registry as registry
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import Deal, DealDocument

GUID_A = '11111111-1111-4111-8111-111111111111'
GUID_B = '22222222-2222-4222-8222-222222222222'
DIRECTOR = SimpleNamespace(roles=['director'])
ALL = SimpleNamespace(own_only=False, employee_id=None)


async def bind(session, org, guid):
    session.add(SyncLink(entity_type='organization', entity_id=org, system='1c',
                         external_ref=guid, origin='1c', direction='in', state='synced'))
    await session.flush()


def source(guid=GUID_A, number='TEST', *, revision=1, key=None, entity='Document_СчетНаОплатуКлиенту', lines=None):
    key = key or str(uuid4())
    value = dict(Ref_Key=key, DataVersion=str(revision), Number=number, Date='2026-08-31T10:00:00',
                 Posted=True, DeletionMark=False, Организация_Key=guid,
                 СуммаДокумента='12.50', Товары=lines or [])
    raw = json.dumps(value, ensure_ascii=False)
    return registry.Source(namespace='test-registry', entity=entity, source_guid=key,
                           source_scope='BOUND_ORGANIZATION', revision_no=revision,
                           source_sha=hashlib.sha256(raw.encode()).hexdigest(), data_version=str(revision),
                           source_text=raw, holds=['FINANCIAL_POSTING_NOT_ACCEPTED', 'OPERATIONAL_DOCUMENT_MAPPING_NOT_ACCEPTED'],
                           actor='test', organization_sha256=hashlib.sha256(guid.encode()).hexdigest(),
                           period_start=datetime(2026, 7, 1), period_end=datetime(2026, 9, 1),
                           entity_scopes_sha256='a'*64, entity_scopes_text='{}')


async def listing(session, org=1, *, user=DIRECTOR, access=ALL, page=1, limit=2, kind='', source='1c'):
    return await registry.registry(org, source, page, limit, '', kind, '', '', (session, user, access))


async def test_exact_organization_binding_and_personal_scope(session):
    await bind(session, 1, GUID_A)
    await bind(session, 2, GUID_B)
    assert await registry.source_binding(session, 1, ALL) == GUID_A
    assert await registry.source_binding(session, 2, ALL) == GUID_B
    with pytest.raises(HTTPException) as denied:
        await registry.source_binding(session, 1, SimpleNamespace(own_only=True))
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as missing:
        await registry.source_binding(session, 3, ALL)
    assert missing.value.status_code == 409


async def test_membership_checked_before_any_source_query():
    calls = []
    async def deny(session, org, user):
        calls.append(org)
        raise HTTPException(403, 'No book grant')
    async def rollback(): calls.append('rollback')
    core = SimpleNamespace(services=SimpleNamespace(accounting=SimpleNamespace(source_member=deny)))
    ctx = registry.context(2, SimpleNamespace(rollback=rollback), core, DIRECTOR, ALL)
    with pytest.raises(HTTPException) as rejected:
        await anext(ctx)
    assert rejected.value.status_code == 403 and calls == [2, 'rollback']


async def test_two_organizations_pagination_and_only_latest_revision(session):
    await bind(session, 1, GUID_A)
    await bind(session, 2, GUID_B)
    key = str(uuid4())
    session.add_all([source(number='OLD', key=key), source(number='LATEST', key=key, revision=2),
                     source(number='SECOND'), source(number='THIRD'), source(GUID_B, 'FOREIGN')])
    await session.flush()
    first = await listing(session)
    second = await listing(session, page=2)
    assert first['total'] == 3 and first['pages'] == 2 and len(first['items']) == 2
    assert second['total'] == 3 and len(second['items']) == 1
    assert {r['number'] for r in first['items']+second['items']} == {'LATEST', 'SECOND', 'THIRD'}
    assert (await listing(session, 2))['items'][0]['number'] == 'FOREIGN'


async def test_source_hash_and_organization_seals_reject_corruption():
    row = source()
    registry.parsed_source(row, GUID_A)
    with pytest.raises(HTTPException):
        registry.parsed_source(row, GUID_B)
    row.source_text = row.source_text.replace('12.50', '99.00')
    with pytest.raises(HTTPException) as invalid:
        registry.parsed_source(row, GUID_A)
    assert invalid.value.status_code == 409


async def test_preview_is_not_posted_and_excludes_private_source_fields(session):
    await bind(session, 1, GUID_A)
    await bind(session, 2, GUID_B)
    sku = Sku(code='REG-SKU', title='Verified source SKU')
    session.add(sku)
    await session.flush()
    sku_ref = str(uuid4())
    session.add(CatalogSourceIdentity(namespace='test-registry', entity='Catalog_Номенклатура',
                                      source_guid=sku_ref, kind='sku', sku_id=sku.id,
                                      source_sha='a'*64, revision_no=1, target_sha='b'*64, holds=[]))
    row = source(lines=[{'Номенклатура_Key': sku_ref, 'Количество': 2, 'Цена': '6.25', 'Паспорт': 'PRIVATE', 'НомерСчета': 'PRIVATE'}])
    foreign = source(GUID_B, 'FOREIGN')
    session.add_all([row, foreign])
    await session.flush()
    result = await registry.source_preview(1, row.id, 1, (session, DIRECTOR, ALL))
    assert result['native_posted'] is False and result['original_available'] is False
    assert result['holds'] == row.holds and result['lines'][0]['fields'] == {'Количество': '2', 'Цена': '6.25'}
    assert result['lines'][0]['name'] == sku.title
    assert 'PRIVATE' not in json.dumps(result)
    with pytest.raises(HTTPException) as denied:
        await registry.source_preview(1, foreign.id, 1, (session, DIRECTOR, ALL))
    assert denied.value.status_code == 404
    private = source(entity='Document_НачислениеЗарплаты')
    session.add(private)
    await session.flush()
    with pytest.raises(HTTPException) as denied:
        await registry.source_preview(1, private.id, 1, (session, SimpleNamespace(roles=['sales']), ALL))
    assert denied.value.status_code == 404


async def test_native_registry_respects_both_book_and_numeric_owner(session):
    for index, (org, owner) in enumerate([(1, 11), (1, 22), (2, 11)], 1):
        deal = Deal(number=f'REG-{index}', title='Test', counterparty='Company', owner_id=owner)
        session.add(deal)
        await session.flush()
        session.add(DealOwnership(deal_id=deal.id, organization_id=org, snapshot={}, evidence='test', actor='test'))
        session.add(DealDocument(deal_id=deal.id, kind='invoice', number=f'DOC-{index}'))
    await session.flush()
    result = await listing(session, source='erp', access=SimpleNamespace(own_only=True, employee_id=11))
    assert result['total'] == 1 and result['items'][0]['number'] == 'DOC-1'
