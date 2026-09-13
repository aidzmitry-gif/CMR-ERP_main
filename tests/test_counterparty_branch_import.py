"""Explicit source identity creates branches without changing legal or manual data."""
import pytest
from sqlalchemy import func, select

from core.domain.models import (
    AuditLog,
    Contact,
    Counterparty,
    CounterpartyAlias,
    CounterpartyBranch,
    CounterpartyBranchAlias,
)
from core.services.mdm import CounterpartyWriteError
from core.services.reference_import import import_counterparties

HEAD = {'id': 'head', 'unp': '600187521', 'name': 'Head', 'legal_name': 'Head Legal'}
BRANCH = {'id': 'branch', 'record_kind': 'branch', 'parent_external_ref': 'head', 'name': 'Branch', 'raw_branch_code': '0002'}


@pytest.mark.parametrize('kind', ['unknown', 'Branch', True, {}, 42])
async def test_unknown_classification_rejects_entire_batch_before_writes(session, kind):
    with pytest.raises(CounterpartyWriteError) as error:
        await import_counterparties(session, [HEAD, dict(HEAD, id='invalid', record_kind=kind)])
    assert error.value.code == 'invalid_record_kind'
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 0


async def test_nonbranch_parent_reference_rejects_before_head_creation(session):
    with pytest.raises(CounterpartyWriteError) as error:
        await import_counterparties(session, [HEAD, dict(HEAD, id='invalid', parent_external_ref='head')])
    assert error.value.code == 'branch_mapping_required'
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 0


@pytest.mark.parametrize('owner', ['manual', 'another_connector'])
async def test_raw_code_owned_elsewhere_is_preserved(session, owner):
    await import_counterparties(session, [HEAD, BRANCH])
    branch = await session.scalar(select(CounterpartyBranch))
    branch.provenance = {**branch.provenance, 'raw_branch_code': {'source': owner, 'value': '0099'}}
    await session.commit()
    await import_counterparties(session, [BRANCH])
    assert branch.provenance['raw_branch_code'] == {'source': owner, 'value': '0099'}


async def test_branch_before_head_is_idempotent_and_raw_code_is_not_portal_code(session):
    first = await import_counterparties(session, [BRANCH, HEAD, BRANCH])
    await session.commit()
    assert first['created'] == 1 and first['branches_created'] == 1
    branch = await session.scalar(select(CounterpartyBranch))
    revision = branch.revision
    assert branch.tax_mode == 'unknown' and branch.portal_branch_code is None
    assert branch.provenance['raw_branch_code']['value'] == '0002'
    second = await import_counterparties(session, [HEAD, BRANCH])
    await session.commit()
    assert second['branches_created'] == 0 and second['branches_matched'] == 1
    assert branch.revision == revision
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 1
    assert await session.scalar(select(func.count()).select_from(CounterpartyBranchAlias)) == 1
    assert await session.scalar(select(func.count()).select_from(AuditLog)) == 1


async def test_manual_fields_and_contacts_survive_source_refresh(session):
    await import_counterparties(session, [HEAD, BRANCH])
    branch = await session.scalar(select(CounterpartyBranch))
    branch.name, branch.address, branch.tax_mode, branch.portal_branch_code = 'Manual', 'Address', 'shared', '0042'
    branch.provenance = {**branch.provenance, 'name': {'source': 'manual'}}
    session.add(Contact(counterparty_id=branch.legal_entity_id, branch_id=branch.id, full_name='Contact'))
    await session.commit()
    await import_counterparties(session, [{**BRANCH, 'name': 'Source changed', 'raw_branch_code': '1234'}])
    await session.commit()
    assert (branch.name, branch.address, branch.tax_mode, branch.portal_branch_code) == ('Manual', 'Address', 'shared', '0042')
    assert branch.provenance['raw_branch_code']['value'] == '1234'
    assert await session.scalar(select(Contact.full_name)) == 'Contact'


@pytest.mark.parametrize('other_parent', [False, True])
async def test_legacy_legal_alias_is_never_converted_or_deleted(session, other_parent):
    await import_counterparties(session, [HEAD])
    parent = await session.scalar(select(Counterparty))
    if other_parent:
        other = Counterparty(name='Other')
        session.add(other)
        await session.flush()
        alias_parent = other.id
    else:
        alias_parent = parent.id
    session.add(CounterpartyAlias(counterparty_id=alias_parent, source='1c', external_ref='branch'))
    await session.commit()
    with pytest.raises(CounterpartyWriteError) as error:
        await import_counterparties(session, [BRANCH])
    assert error.value.code == ('source_kind_conflict' if other_parent else 'legacy_flattened_branch_alias')
    await session.rollback()
    assert await session.scalar(select(CounterpartyAlias.counterparty_id).where(CounterpartyAlias.external_ref == 'branch')) == alias_parent
    assert await session.scalar(select(func.count()).select_from(CounterpartyBranch)) == 0


@pytest.mark.parametrize('problem', ['missing_alias', 'inactive', 'no_legal_name', 'wrong_parent', 'kind_conflict'])
async def test_invalid_parent_or_classification_never_guesses_by_name_or_unp(session, problem):
    await import_counterparties(session, [HEAD])
    parent = await session.scalar(select(Counterparty))
    row = dict(BRANCH, unp=HEAD['unp'])
    if problem == 'missing_alias':
        row['parent_external_ref'] = 'absent'
    elif problem == 'inactive':
        parent.is_active = False
    elif problem == 'no_legal_name':
        parent.legal_name = None
    elif problem == 'wrong_parent':
        await import_counterparties(session, [BRANCH])
        await import_counterparties(session, [{**HEAD, 'id': 'other', 'unp': '600187522', 'name': 'Other'}])
        row['parent_external_ref'] = 'other'
    await session.commit()
    rows = [row, {**HEAD, 'id': 'branch'}] if problem == 'kind_conflict' else [row]
    with pytest.raises(CounterpartyWriteError):
        await import_counterparties(session, rows)
    await session.rollback()
    if problem == 'wrong_parent':
        branch = await session.scalar(select(CounterpartyBranch))
        assert branch.legal_entity_id == await session.scalar(select(CounterpartyAlias.counterparty_id).where(CounterpartyAlias.external_ref == 'head'))
    else:
        assert await session.scalar(select(func.count()).select_from(CounterpartyBranch)) == 0


async def test_existing_branch_ref_cannot_be_imported_as_a_legal_entity(session):
    await import_counterparties(session, [HEAD, BRANCH])
    await session.commit()
    with pytest.raises(CounterpartyWriteError, match='филиалу'):
        await import_counterparties(session, [{**HEAD, 'id': 'branch'}])


@pytest.mark.parametrize('bad_fields', [
    {'name': '   '},
    {'id': 'x' * 129},
    {'parent_external_ref': 'branch'},
    {'raw_branch_code': 2},
    {'raw_branch_code': '0' * 256},
])
async def test_invalid_branch_batch_never_partially_creates_head(session, bad_fields):
    with pytest.raises(CounterpartyWriteError) as error:
        await import_counterparties(session, [HEAD, {**BRANCH, **bad_fields}])
    assert error.value.status == 422
    # Deliberately commit rather than hiding partial writes with a test rollback.
    await session.commit()
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 0
    assert await session.scalar(select(func.count()).select_from(CounterpartyAlias)) == 0
    assert await session.scalar(select(func.count()).select_from(CounterpartyBranch)) == 0
