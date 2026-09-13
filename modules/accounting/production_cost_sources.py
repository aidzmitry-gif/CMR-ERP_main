"""Dated ledger evidence for production cost review; not cost classification."""
import hashlib
import json
from calendar import monthrange
from datetime import date
from fractions import Fraction

from sqlalchemy import select

from modules.accounting.models import (
    Entry,
    Line,
    Policy,
    ProductionOverheadReceipt,
    ProductionOverheadRevision,
)
from modules.accounting.production_cost_policy import validate_accounts
from modules.accounting.schemas import ProductionCostPolicyInput
from modules.accounting.service import AccountingError, lock_organization


async def cost_sources(session, org_id, month, policy_id, *, correction_of=None):
    await lock_organization(session, org_id)
    excluded = None
    applied = []
    chain = None
    if correction_of is not None:
        original = await session.get(ProductionOverheadReceipt, correction_of)
        if not original or original.organization_id != org_id or original.month != month or original.command['review']['policy_id'] != policy_id:
            raise AccountingError('Correction must identify the original allocation in this organization, month and policy')
        entry = await session.get(Entry, correction_of)
        excluded = {'entry_id': entry.id, 'entry_digest': entry.digest, 'request_key': original.request_key}
        revisions = (await session.scalars(select(ProductionOverheadRevision).where(
            ProductionOverheadRevision.original_entry_id == correction_of).order_by(ProductionOverheadRevision.sequence))).all()
        applied = [correction_of, *[row.entry_id for row in revisions if row.entry_id is not None]]
        chain = {'revision_ids': [row.id for row in revisions], 'applied_entry_ids': applied,
            'latest_digest': revisions[-1].preview['digest'] if revisions else original.review['digest']}
    first = date.fromisoformat(month + '-01')
    last = first.replace(day=monthrange(first.year, first.month)[1])
    policies = (await session.scalars(select(Policy).where(Policy.organization_id == org_id,
        Policy.effective_from <= last).order_by(Policy.effective_from.desc()))).all()
    if not policies or policies[0].id != policy_id or policies[0].effective_from > first:
        raise AccountingError('Select one applicable production policy for the whole reviewed month')
    policy = policies[0]
    if policy.production_costing is None:
        raise AccountingError('Production cost configuration is required')
    settings = ProductionCostPolicyInput.model_validate(policy.production_costing)
    await validate_accounts(session, org_id, last, settings)
    rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == org_id, Entry.posting_date <= last,
        Entry.id.not_in(applied),
        Line.account_code.in_([*settings.overhead_accounts, settings.wip_account])
    ).order_by(Entry.posting_date, Entry.id, Line.id))).all()
    buckets, evidence = {}, []
    for entry, line in rows:
        wip = line.account_code == settings.wip_account
        required = set(settings.pool_dimensions) | ({settings.order_dimension} if wip else set())
        if (line.currency != 'BYN' or line.cash or line.quantity is not None
            or line.category not in ({'asset'} if wip else {'asset', 'expense'})
            or not isinstance(line.dimensions, dict) or set(line.dimensions) != required
            or any(not isinstance(v, str) or not v.strip() for v in line.dimensions.values())):
            raise AccountingError('Production cost history has incompatible currency, tracking or analytics; reconcile first')
        cents = Fraction(line.amount) * 100
        if cents.denominator != 1 or cents < 0 or line.side not in {'debit', 'credit'}:
            raise AccountingError('Production cost history has invalid monetary values')
        key = (line.account_code, json.dumps(line.dimensions, sort_keys=True, ensure_ascii=False))
        bucket = buckets.setdefault(key, {'account': line.account_code, 'dimensions': line.dimensions,
            'role': 'wip' if wip else 'overhead', 'opening': 0, 'debit': 0, 'credit': 0})
        if entry.posting_date < first or entry.opening:
            bucket['opening'] += cents.numerator * (1 if line.side == 'debit' else -1)
        else:
            bucket[line.side] += cents.numerator
        evidence.append({'entry_id': entry.id, 'line_id': line.id, 'entry_digest': entry.digest,
            'source': entry.source, 'source_version': entry.source_version, 'operation': entry.operation,
            'posting_date': entry.posting_date.isoformat(), 'operation_date': entry.operation_date.isoformat(),
            'opening': entry.opening, 'correction_of': entry.correction_of, 'account': line.account_code,
            'account_title': line.account_title, 'dimensions': line.dimensions, 'side': line.side,
            'amount_byn': format(line.amount, '.2f')})

    def money(cents):
        sign = '-' if cents < 0 else ''
        return f'{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}'

    balances = [{**{k: v for k, v in bucket.items() if k not in {'opening', 'debit', 'credit'}},
        **{k + '_byn': money(bucket[k]) for k in ('opening', 'debit', 'credit')},
        'closing_byn': money(bucket['opening'] + bucket['debit'] - bucket['credit'])}
        for _, bucket in sorted(buckets.items())]
    snapshot = {'organization_id': org_id, 'month': month, 'policy_id': policy.id,
        'policy_reference': policy.reference, 'basis': policy.allocation_basis,
        'settings': settings.model_dump(mode='json'), 'balances': balances, 'lines': evidence,
        'scope': 'posted_production_cost_accounts', 'status': 'source_review', 'posted': False,
        'allocation_base_verified': False, 'production_order_links_verified': False, 'final_cost_certified': False}
    if excluded:
        snapshot['scope'] = 'production_cost_correction_sources'
        snapshot['excluded_allocation'] = excluded
        snapshot['calculation_chain'] = chain
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return {'snapshot': snapshot, 'digest': digest}
