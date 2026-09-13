"""Reviewed direct-cost overhead preview, with production-owned order validation."""
import hashlib
import json
from collections import defaultdict
from fractions import Fraction
from typing import Literal

from pydantic import Field, model_validator

from modules.accounting.production_cost_allocation import (
    ProductionOverheadInput,
    preview_production_overhead,
)
from modules.accounting.production_cost_sources import cost_sources
from modules.accounting.schemas import Input
from modules.accounting.service import AccountingError


class CostClassification(Input):
    line_id: int = Field(gt=0, strict=True)
    role: Literal['direct_cost', 'overhead', 'excluded']
    evidence: str = Field(min_length=10, max_length=1000)


class CostOrderBinding(Input):
    analytical_order: str = Field(min_length=1, max_length=200)
    order_id: int = Field(gt=0, strict=True)
    evidence: str = Field(min_length=10, max_length=1000)


class ProductionCostReviewInput(Input):
    policy_id: int = Field(gt=0, strict=True)
    expected_source_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    classifications: list[CostClassification] = Field(min_length=1, max_length=10000)
    orders: list[CostOrderBinding] = Field(max_length=1000)

    @model_validator(mode='after')
    def unique_evidence(self):
        for values in ([v.line_id for v in self.classifications], [v.order_id for v in self.orders],
                       [v.analytical_order for v in self.orders]):
            if len(values) != len(set(values)):
                raise ValueError('Cost classifications and order bindings must be unique')
        return self


async def review_costs(session, org_id, month, data, production, *, correction_of=None):
    source = await cost_sources(session, org_id, month, data.policy_id, correction_of=correction_of)
    if source['digest'] != data.expected_source_digest:
        raise AccountingError('Production cost sources changed; repeat review')
    snapshot = source['snapshot']
    if snapshot['basis'] != 'direct_cost':
        raise AccountingError('This review requires direct-cost policy; labor/output bases need their authenticated registers')
    if production is None:
        raise AccountingError('Production order verification service is unavailable')
    classifications = {v.line_id: v for v in data.classifications}
    if set(classifications) != {v['line_id'] for v in snapshot['lines']}:
        raise AccountingError('Classify every source line exactly once, including excluded opening/history')
    bindings = {v.analytical_order: v.order_id for v in data.orders}
    if not bindings and correction_of is None:
        raise AccountingError('Initial allocation requires verified production order bindings')
    used = set()
    direct, pools = defaultdict(lambda: defaultdict(int)), defaultdict(int)
    settings = snapshot['settings']
    for line in snapshot['lines']:
        role = classifications[line['line_id']].role
        if role == 'excluded':
            continue
        if line['opening'] or line['posting_date'][:7] != month:
            raise AccountingError('Opening and earlier cost history cannot become current-month allocation bases')
        pool = tuple((key, line['dimensions'][key]) for key in settings['pool_dimensions'])
        cents = int(Fraction(line['amount_byn']) * 100) * (1 if line['side'] == 'debit' else -1)
        if role == 'direct_cost':
            if line['account'] != settings['wip_account']:
                raise AccountingError('Direct costs must originate from the configured WIP account')
            analytical = line['dimensions'][settings['order_dimension']]
            if analytical not in bindings:
                raise AccountingError('Direct cost order analytics require an explicit production order binding')
            used.add(analytical)
            direct[pool][bindings[analytical]] += cents
        else:
            if line['account'] not in settings['overhead_accounts']:
                raise AccountingError('Overhead must originate from a configured overhead account')
            pools[(line['account'], pool)] += cents
    if used != set(bindings):
        raise AccountingError('Production order bindings must match the reviewed direct-cost targets exactly')
    if any(value < 0 for orders in direct.values() for value in orders.values()) or any(value < 0 for value in pools.values()):
        raise AccountingError('Negative net cost pool or direct-cost base requires correction')
    try:
        order_snapshots = await production.cost_orders(session, org_id, sorted(bindings.values())) if bindings else []
    except ValueError as exc:
        raise AccountingError(str(exc)) from exc

    def money(cents):
        return f'{cents // 100}.{cents % 100:02d}'

    allocations = []
    for (account, pool), cents in sorted(pools.items()):
        if cents == 0:
            continue
        targets = direct.get(pool, {})
        if not targets or sum(targets.values()) <= 0:
            raise AccountingError('Every overhead pool requires a positive direct-cost base in the same analytics')
        allocation = preview_production_overhead(ProductionOverheadInput(amount_byn=money(cents), basis='direct_cost',
            rounding=settings['rounding'], targets=[{'order_id': order, 'basis_amount': money(value)} for order, value in sorted(targets.items())]))
        allocations.append({'account': account, 'pool_dimensions': dict(pool), 'allocation': allocation})
    if not allocations and correction_of is None:
        raise AccountingError('No positive reviewed overhead pool to allocate')
    result = {'organization_id': org_id, 'month': month, 'source': source, 'review': data.model_dump(mode='json'),
        'production_orders': order_snapshots, 'allocations': allocations,
        'status': 'reviewed_allocation_preview', 'posted': False, 'final_cost_certified': False}
    digest = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return {'snapshot': result, 'digest': digest}
