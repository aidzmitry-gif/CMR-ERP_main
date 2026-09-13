"""Reviewed correction arithmetic. Posting requires a separate immutable calculation revision."""
import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import select, text

from modules.accounting import service
from modules.accounting.models import (
    Line,
    Period,
    ProductionOverheadCorrectionWithdrawal,
    ProductionOverheadReceipt,
    ProductionOverheadRevision,
)
from modules.accounting.production_cost_posting import allocation_lines
from modules.accounting.production_cost_review import ProductionCostReviewInput, review_costs
from modules.accounting.schemas import Input, PostingInput
from modules.accounting.service import AccountingError, lock_organization


class ProductionOverheadCorrectionPreview(Input):
    original_entry_id: int = Field(gt=0, strict=True)
    review: ProductionCostReviewInput
    expected_review_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    method: Literal['delta']
    posting_date: date
    evidence: str = Field(min_length=10, max_length=1000)


class ProductionOverheadCorrectionConfirm(Input):
    request_key: UUID
    preview: ProductionOverheadCorrectionPreview
    expected_preview_digest: str = Field(pattern=r'^[a-f0-9]{64}$')


class ProductionOverheadCorrectionWithdraw(Input):
    command: ProductionOverheadCorrectionConfirm
    reason: str = Field(min_length=10, max_length=1000)


def correction_delta(original, desired):
    """Use integer BYN cents per complete account/analytics key; never allocate again on top."""
    differences = defaultdict(int)
    for multiplier, rows in [(-1, original), (1, desired)]:
        for row in rows:
            cents = Fraction(row['amount']) * 100
            if cents.denominator != 1 or cents < 0 or row['side'] not in {'debit', 'credit'}:
                raise AccountingError('Correction requires exact positive BYN source amounts')
            key = (row['account'], tuple(sorted(row['dimensions'].items())))
            differences[key] += multiplier * cents.numerator * (1 if row['side'] == 'debit' else -1)
    if sum(differences.values()) != 0:
        raise AccountingError('Correction differences must balance')
    return [{'account': account, 'dimensions': dict(dimensions), 'side': 'debit' if cents > 0 else 'credit',
        'amount': f'{abs(cents) // 100}.{abs(cents) % 100:02d}'}
        for (account, dimensions), cents in sorted(differences.items()) if cents]


async def preview_correction(session, org_id, month, data, production):
    await lock_organization(session, org_id)
    original = await session.get(ProductionOverheadReceipt, data.original_entry_id)
    if not original or original.organization_id != org_id or original.month != month:
        raise AccountingError('Original overhead allocation must belong to this organization and month')
    if data.posting_date.strftime('%Y-%m') != month:
        raise AccountingError('Cross-period corrections require their applicable prior-period correction policy')
    if data.posting_date.isoformat() < original.command['posting_date']:
        raise AccountingError('Correction cannot precede its original allocation')
    latest_revision = await session.scalar(select(ProductionOverheadRevision).where(
        ProductionOverheadRevision.original_entry_id == original.entry_id).order_by(ProductionOverheadRevision.sequence.desc()).limit(1))
    if latest_revision and data.posting_date.isoformat() < latest_revision.command['preview']['posting_date']:
        raise AccountingError('Correction cannot precede its latest calculation revision')
    if await session.scalar(select(Period.id).where(Period.organization_id == org_id, Period.month >= month, Period.closed.is_(True)).limit(1)):
        raise AccountingError('This correction preview requires an open month and no later closed periods')
    reviewed = await review_costs(session, org_id, month, data.review, production, correction_of=data.original_entry_id)
    if reviewed['digest'] != data.expected_review_digest:
        raise AccountingError('Corrected production allocation changed; review again')
    included = {row.line_id for row in data.review.classifications if row.role != 'excluded'}
    latest = max((line['posting_date'] for line in reviewed['snapshot']['source']['snapshot']['lines'] if line['line_id'] in included),
        default=original.command['posting_date'])
    if data.posting_date.isoformat() < latest:
        raise AccountingError('Correction cannot precede its included cost sources')
    desired = allocation_lines(reviewed['snapshot'])
    chain = reviewed['snapshot']['source']['snapshot']['calculation_chain']
    applied = (await session.scalars(select(Line).where(Line.entry_id.in_(chain['applied_entry_ids'])))).all()
    lines = correction_delta([{'account': row.account_code, 'side': row.side, 'dimensions': row.dimensions,
        'amount': row.amount} for row in applied], desired)
    if session.get_bind().dialect.name == 'postgresql':
        # Keep the authoritative DB calculation numeric until textual JSON decode;
        # the driver's default JSON float loader would lose large BYN cents.
        verified = await session.scalar(text('SELECT accounting.production_cost_delta(:org, '
            'accounting.verify_production_cost_review(:org, :month, :policy, CAST(:day AS date), '
            'CAST(:reviewed AS jsonb), CAST(:command AS jsonb), :applied, true), '
            ':applied)::text'), dict(org=org_id, month=month,
                policy=data.review.policy_id, day=data.posting_date.isoformat(), reviewed=json.dumps(reviewed),
                command=data.review.model_dump_json(), applied=chain['applied_entry_ids']))
        matrix = json.loads(verified, parse_float=Decimal)
        independently_calculated = correction_delta([], [{'account': account, 'side': side,
            'dimensions': dimensions, 'amount': amount} for account, side, dimensions, amount in matrix])
        if lines != independently_calculated:
            raise AccountingError('Correction differs from independently calculated ledger costs')
    snapshot = {'organization_id': org_id, 'month': month, 'original_entry_id': original.entry_id,
        'original_posting': original.posting, 'command': data.model_dump(mode='json'), 'reviewed': reviewed,
        'desired_allocation_lines': desired, 'correction_lines': lines, 'creates_entry': bool(lines),
        'status': 'correction_preview', 'posted': False,
        'confirmation_available': session.get_bind().dialect.name == 'postgresql', 'final_cost_certified': False}
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return {'snapshot': snapshot, 'digest': digest}


async def correction_result(session, org_id, request_key):
    await lock_organization(session, org_id)
    return await session.scalar(select(ProductionOverheadRevision).where(
        ProductionOverheadRevision.organization_id == org_id, ProductionOverheadRevision.request_key == str(request_key)))


async def confirm_correction(session, org_id, month, command, actor, production):
    existing = await correction_result(session, org_id, command.request_key)
    if await session.get(ProductionOverheadCorrectionWithdrawal, (org_id, str(command.request_key))):
        raise AccountingError('Correction request was withdrawn; prepare a new reviewed calculation')
    normalized = command.model_dump(mode='json')
    if existing:
        if existing.command != normalized or existing.actor != actor or existing.month != month:
            raise AccountingError('Correction request conflicts with its saved calculation')
        return existing
    if session.get_bind().dialect.name != 'postgresql':
        raise AccountingError('Correction confirmation requires PostgreSQL admission checks')
    preview = await preview_correction(session, org_id, month, command.preview, production)
    if preview['digest'] != command.expected_preview_digest:
        raise AccountingError('Correction calculation changed; repeat review')
    snapshot = preview['snapshot']
    chain = snapshot['reviewed']['snapshot']['source']['snapshot']['calculation_chain']
    sequence = len(chain['revision_ids']) + 1
    posting = None
    entry_id = None
    if snapshot['correction_lines']:
        data = command.preview
        candidate = PostingInput(source=f'production:overhead:{org_id}:{month}', source_version=sequence,
            operation='production_overhead_correction', correction_of=chain['applied_entry_ids'][-1],
            document_date=data.posting_date, operation_date=data.posting_date, posting_date=data.posting_date,
            policy_id=data.review.policy_id, rule_version='production-overhead-correction-v1',
            explanation=data.evidence, lines=snapshot['correction_lines'])
        entry = await service.post(session, org_id, candidate, actor, production_correction=True)
        posting = candidate.model_dump(mode='json')
        entry_id = entry.id
    row = ProductionOverheadRevision(organization_id=org_id, original_entry_id=command.preview.original_entry_id,
        sequence=sequence, previous_id=chain['revision_ids'][-1] if chain['revision_ids'] else None,
        month=month, request_key=str(command.request_key), command=normalized, preview=preview,
        actor=actor, entry_id=entry_id, posting=posting)
    session.add(row)
    service.audit(session, org_id, actor, 'production_overhead_corrected',
        {'original_entry_id': row.original_entry_id, 'sequence': sequence, 'entry_id': entry_id, 'request_key': row.request_key})
    await session.flush()
    if entry_id is None:
        org = await lock_organization(session, org_id)
        org.generation += 1
        affected = (await session.scalars(select(Period).where(Period.organization_id == org_id,
            Period.month >= month).execution_options(populate_existing=True))).all()
        for period in affected:
            period.generation += 1
            period.evidence = {}
        await session.flush()
    return row


async def correction_request_result(session, org_id, request_key):
    revision = await correction_result(session, org_id, request_key)
    if revision:
        return 'confirmed', revision
    withdrawal = await session.get(ProductionOverheadCorrectionWithdrawal, (org_id, str(request_key)))
    return ('withdrawn', withdrawal) if withdrawal else (None, None)


async def withdraw_correction(session, org_id, month, data, actor):
    if data.command.preview.posting_date.strftime('%Y-%m') != month:
        raise AccountingError('Correction withdrawal month must match its saved command')
    status, existing = await correction_request_result(session, org_id, data.command.request_key)
    normalized = data.command.model_dump(mode='json')
    if existing:
        if existing.actor != actor or existing.month != month or existing.command != normalized:
            raise AccountingError('Correction withdrawal conflicts with the saved request')
        if status == 'withdrawn' and existing.reason != data.reason:
            raise AccountingError('Correction withdrawal reason conflicts with the saved request')
        return status, existing
    row = ProductionOverheadCorrectionWithdrawal(organization_id=org_id, month=month,
        request_key=str(data.command.request_key), command=normalized, actor=actor, reason=data.reason)
    session.add(row)
    service.audit(session, org_id, actor, 'production_overhead_correction_withdrawn',
        {'request_key': row.request_key, 'month': month, 'reason': data.reason})
    await session.flush()
    return 'withdrawn', row
