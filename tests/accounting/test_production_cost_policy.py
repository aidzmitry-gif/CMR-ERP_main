from copy import deepcopy
from datetime import date

import pytest
from sqlalchemy import select

from modules.accounting.models import Account, Policy


def body():
    return dict(effective_from='2026-10-01', reference='Synthetic production policy', inventory_method='specific',
        allocation_basis='direct_cost', depreciation_method='straight_line', normative_reference='Synthetic only',
        production_costing=dict(overhead_accounts=['25'], wip_account='20', pool_dimensions=['department'],
            order_dimension='order', rounding='largest_remainder_cent', reference='Synthetic approved overhead instruction'))


async def seed(db, org):
    for code, dimensions in [('25', ['department']), ('20', ['department', 'order'])]:
        db.add(Account(organization_id=org, code=code, title='Synthetic production account', category='asset',
            valid_from=date(2026, 1, 1), required_dimensions=dimensions, cash=False,
            currency_tracking=False, quantity_tracking=False, normative_ref='Synthetic'))
    await db.commit()


async def test_production_settings_versioned_and_optional(client, db, book):
    await seed(db, book[0])
    path = f'/accounting/organizations/{book[0]}/policies'
    response = await client.post(path, json=body())
    assert response.status_code == 201, response.text
    assert response.json()['production_costing'] == body()['production_costing']
    assert response.json()['normative_verified'] is False
    assert next(p for p in (await client.get(path)).json() if p['id'] == book[1])['production_costing'] is None
    row = await db.get(Policy, response.json()['id'])
    row.production_costing = {**row.production_costing, 'wip_account': '99'}
    with pytest.raises(ValueError, match='immutable'):
        await db.flush()
    await db.rollback()


@pytest.mark.parametrize('field,value', [
    ('overhead_accounts', []), ('overhead_accounts', ['25', '25']), ('overhead_accounts', ['20']),
    ('overhead_accounts', ['999']), ('wip_account', '51'), ('wip_account', '60'),
    ('pool_dimensions', []), ('pool_dimensions', ['department', 'department']),
    ('order_dimension', 'sku'), ('rounding', 'guess'), ('reference', ''),
])
async def test_invalid_production_policy_creates_no_version(client, db, book, field, value):
    await seed(db, book[0])
    data = deepcopy(body())
    data['production_costing'][field] = value
    response = await client.post(f'/accounting/organizations/{book[0]}/policies', json=data)
    assert response.status_code == 422, response.text
    assert len((await db.scalars(select(Policy).where(Policy.organization_id == book[0]))).all()) == 1


async def test_missing_production_account_cannot_use_another_company(client, db, book):
    from modules.accounting.models import Organization
    other = Organization(name='Other synthetic company', unp='987654321')
    db.add(other)
    await db.flush()
    await seed(db, other.id)
    response = await client.post(f'/accounting/organizations/{book[0]}/policies', json=body())
    assert response.status_code == 422, response.text


@pytest.mark.parametrize('changes,accepted', [
    ({}, True), ({'quantity_tracking': False}, False), ({'cash': True}, False),
    ({'currency_tracking': True}, False), ({'category': 'expense'}, False), ({'code': '43.01'}, False),
])
async def test_material_account_rule_requires_native_quantity_asset(client, db, book, changes, accepted):
    await seed(db, book[0])
    values = dict(code='10.01', category='asset', cash=False, currency_tracking=False, quantity_tracking=True)
    values.update(changes)
    db.add(Account(organization_id=book[0], title='Material stock', valid_from=date(2026, 1, 1),
        required_dimensions=['warehouse', 'sku', 'lot'], normative_ref='Synthetic', **values))
    await db.commit()
    data = body()
    data['production_costing']['material_inventory_account'] = values['code']
    response = await client.post(f'/accounting/organizations/{book[0]}/policies', json=data)
    assert response.status_code == (201 if accepted else 422), response.text
    if accepted:
        assert response.json()['production_costing']['material_inventory_account'] == values['code']
    else:
        assert len((await db.scalars(select(Policy).where(Policy.organization_id == book[0]))).all()) == 1
