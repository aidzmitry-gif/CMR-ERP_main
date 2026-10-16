"""Import explicitly classified branches; never infer identity from a name or UNP."""
from copy import deepcopy
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select

from core.domain.models import (
    AuditLog,
    Counterparty,
    CounterpartyAlias,
    CounterpartyBranch,
    CounterpartyBranchAlias,
    lock_counterparty_unps,
)
from core.services.counterparty_branches import BranchPatch, branch_dict
from core.services.mdm import CounterpartyWriteError


async def import_branch_batch(session, rows, *, source):
    # The entry point imports this module lazily; keep the existing head importer.
    from core.services.reference_import import _lock_alias_refs, import_counterparties

    if not isinstance(source, str) or not source or len(source) > 32 or source == 'merge':
        raise CounterpartyWriteError('invalid_source', 'Недопустимый источник филиалов', 422)
    unique, heads, branches = {}, [], []
    for row in rows:
        ref = row.get('external_ref') or row.get('id')
        if ref:
            if not isinstance(ref, str) or len(ref) > 128:
                raise CounterpartyWriteError('invalid_source_ref', 'Некорректный ID источника', 422)
            if ref in unique:
                if unique[ref] != row:
                    raise CounterpartyWriteError('source_kind_conflict', 'Один ID источника имеет разные значения')
                continue
            unique[ref] = row
        if row.get('record_kind') == 'branch':
            parent_ref = row.get('parent_external_ref')
            if not ref or not isinstance(parent_ref, str) or not parent_ref or len(parent_ref) > 128 or parent_ref == ref:
                raise CounterpartyWriteError('branch_mapping_required', 'Нужны разные точные ID филиала и головного предприятия', 422)
            try:
                BranchPatch(name=row.get('name'))  # Same text constraints as the editor.
            except ValidationError as exc:
                raise CounterpartyWriteError('invalid_branch_name', 'Некорректное наименование филиала', 422) from exc
            raw = row.get('raw_branch_code')
            if raw is not None and (not isinstance(raw, str) or len(raw) > 255):
                raise CounterpartyWriteError('invalid_branch_code', 'Некорректный исходный код филиала', 422)
            branches.append(row)
        else:
            heads.append(row)

    refs = set(unique) | {row['parent_external_ref'] for row in branches}
    parent_ids = set(await session.scalars(select(CounterpartyAlias.counterparty_id).where(
        CounterpartyAlias.source == source, CounterpartyAlias.external_ref.in_(refs),
    )))
    parent_ids.update(await session.scalars(select(CounterpartyBranch.legal_entity_id).join(
        CounterpartyBranchAlias, CounterpartyBranchAlias.branch_id == CounterpartyBranch.id,
    ).where(CounterpartyBranchAlias.source == source, CounterpartyBranchAlias.external_ref.in_(refs))))
    unps = {(r.get('unp') or '').strip() for r in heads} - {''}
    known = dict((await session.execute(select(Counterparty.id, Counterparty.unp).where(
        Counterparty.id.in_(parent_ids) | Counterparty.unp.in_(unps),
    ))).all())
    unps.update(value for value in known.values() if value)
    await session.run_sync(lambda sync: lock_counterparty_unps(sync, unps))
    await _lock_alias_refs(session, source, refs)
    locked = list(await session.scalars(select(Counterparty).where(Counterparty.id.in_(known))
        .order_by(Counterparty.id).with_for_update().execution_options(populate_existing=True)))
    if any(parent.unp != known[parent.id] for parent in locked):
        raise CounterpartyWriteError('parent_changed', 'Головное предприятие изменилось; повторите импорт после проверки')
    summary = await import_counterparties(session, heads, source=source)
    # All old parents are locked; new parents came from this transaction's heads.
    aliases = {alias.external_ref: alias for alias in await session.scalars(select(CounterpartyAlias).where(
        CounterpartyAlias.source == source, CounterpartyAlias.external_ref.in_(refs),
    ))}
    available_ids = set(known) | {a.counterparty_id for ref, a in aliases.items() if ref in {
        r.get('external_ref') or r.get('id') for r in heads
    }}
    branch_aliases = {a.external_ref: a for a in await session.scalars(select(CounterpartyBranchAlias).where(
        CounterpartyBranchAlias.source == source, CounterpartyBranchAlias.external_ref.in_(refs),
    ))}
    stored = {b.id: b for b in await session.scalars(select(CounterpartyBranch).where(
        CounterpartyBranch.id.in_([a.branch_id for a in branch_aliases.values()]),
    ).order_by(CounterpartyBranch.id).with_for_update().execution_options(populate_existing=True))}
    created = matched = 0
    now = datetime.now(UTC).isoformat()
    for row in branches:
        ref = row.get('external_ref') or row['id']
        parent_alias = aliases.get(row['parent_external_ref'])
        if parent_alias is None or parent_alias.counterparty_id not in available_ids or row['parent_external_ref'] in branch_aliases:
            raise CounterpartyWriteError('branch_parent_not_found', 'Головное предприятие не сопоставлено по ID источника', 422)
        parent = await session.get(Counterparty, parent_alias.counterparty_id)
        if parent is None or not parent.is_active or parent.merged_into_id is not None:
            raise CounterpartyWriteError('parent_archived', 'Головное предприятие архивировано или объединено')
        if not parent.unp or len(parent.unp) != 9 or not parent.unp.isascii() or not parent.unp.isdigit() or not (parent.legal_name or '').strip():
            raise CounterpartyWriteError('parent_identity_required', 'Сначала подтвердите УНП и юридическое наименование головного предприятия', 422)
        if ref in aliases:
            code = 'legacy_flattened_branch_alias' if aliases[ref].counterparty_id == parent.id else 'source_kind_conflict'
            raise CounterpartyWriteError(code, 'ID филиала уже записан как источник юридического лица; требуется отдельная проверка соответствия')
        alias = branch_aliases.get(ref)
        branch = stored.get(alias.branch_id) if alias else None
        if alias and (branch is None or branch.legal_entity_id != parent.id or not branch.is_active):
            raise CounterpartyWriteError('branch_identity_conflict', 'ID связан с другим или архивным филиалом')
        before = branch_dict(branch) if branch else None
        if branch is None:
            branch = CounterpartyBranch(legal_entity_id=parent.id, name=row['name'].strip(), tax_mode='unknown', provenance={})
            session.add(branch)
            created += 1
        else:
            matched += 1
        provenance = deepcopy(branch.provenance or {})
        if before is None or provenance.get('name', {}).get('source') == source:
            if before is None or branch.name != row['name'].strip():
                branch.name = row['name'].strip()
                provenance['name'] = {'source': source, 'at': now}
        if provenance.get('raw_branch_code', {}).get('source') in (None, source) and 'raw_branch_code' in row and (provenance.get('raw_branch_code', {}).get('value') != row['raw_branch_code']
                                          or 'raw_branch_code' not in provenance):
            provenance['raw_branch_code'] = {'source': source, 'value': row['raw_branch_code'], 'at': now}
        branch.provenance = provenance
        await session.flush()
        if alias is None:
            session.add(CounterpartyBranchAlias(branch_id=branch.id, source=source, external_ref=ref))
        after = branch_dict(branch)
        if before != after:
            session.add(AuditLog(actor=source, action='counterparty.branch.imported', entity_ref=f'counterparty:{parent.id}',
                                detail={'branch_id': branch.id, 'external_ref': ref, 'before': before, 'after': after}))
    await session.flush()
    return {**summary, 'total': len(rows), 'branches_created': created, 'branches_matched': matched}
