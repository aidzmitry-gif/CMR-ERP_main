"""Atomic reviewed overhead allocation; subsequent revisions need correction workflow."""
from datetime import date
from uuid import UUID

from pydantic import Field
from sqlalchemy import select

from modules.accounting import service
from modules.accounting.models import (
    ProductionOverheadReceipt,
    ProductionOverheadRevision,
    ProductionOverheadWithdrawal,
)
from modules.accounting.production_cost_review import ProductionCostReviewInput, review_costs
from modules.accounting.schemas import Input, PostingInput


class ProductionOverheadConfirm(Input):
    request_key: UUID
    review: ProductionCostReviewInput
    expected_review_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    posting_date: date
    evidence: str = Field(min_length=10, max_length=1000)


class ProductionOverheadWithdraw(Input):
    command: ProductionOverheadConfirm
    reason: str = Field(min_length=10, max_length=1000)


async def request_result(session, org_id, request_key):
    await service.lock_organization(session, org_id)
    receipt = await session.scalar(select(ProductionOverheadReceipt).where(
        ProductionOverheadReceipt.organization_id == org_id, ProductionOverheadReceipt.request_key == str(request_key)))
    if receipt:
        return 'posted', receipt
    withdrawal = await session.get(ProductionOverheadWithdrawal, (org_id, str(request_key)))
    return ('withdrawn', withdrawal) if withdrawal else (None, None)


async def withdraw_overhead(session, org_id, month, data, actor):
    """Serialize against confirmation, including a delayed first request after browser cancellation."""
    if data.command.posting_date.strftime('%Y-%m') != month:
        raise service.AccountingError('Withdrawal month must match the original command')
    status, existing = await request_result(session, org_id, data.command.request_key)
    command = data.command.model_dump(mode='json')
    if existing:
        if existing.actor != actor or existing.command != command or existing.month != month:
            raise service.AccountingError('Withdrawal conflicts with the stored request')
        if status == 'withdrawn' and existing.reason != data.reason:
            raise service.AccountingError('Withdrawal reason conflicts with the stored request')
        return status, existing
    row = ProductionOverheadWithdrawal(organization_id=org_id, month=month, request_key=str(data.command.request_key),
        command=command, actor=actor, reason=data.reason)
    session.add(row)
    service.audit(session, org_id, actor, 'production_overhead_request_withdrawn',
        {'month': month, 'request_key': row.request_key, 'reason': data.reason})
    await session.flush()
    return 'withdrawn', row


async def overhead_source_state(session, row):
    from modules.accounting.production_cost_sources import cost_sources

    try:
        current = await cost_sources(session, row.organization_id, row.month, row.command['review']['policy_id'], correction_of=row.entry_id)
        latest = await session.scalar(select(ProductionOverheadRevision).where(
            ProductionOverheadRevision.original_entry_id == row.entry_id).order_by(ProductionOverheadRevision.sequence.desc()).limit(1))
        reviewed = latest.preview['snapshot']['reviewed'] if latest else row.review
        return 'unchanged' if current['snapshot']['lines'] == reviewed['snapshot']['source']['snapshot']['lines'] else 'changed'
    except service.AccountingError:
        return 'unavailable'


async def validate_overhead_for_close(session, org_id, month):
    await service.lock_organization(session, org_id)
    rows = (await session.scalars(select(ProductionOverheadReceipt).where(
        ProductionOverheadReceipt.organization_id == org_id, ProductionOverheadReceipt.month <= month)
        .order_by(ProductionOverheadReceipt.month))).all()
    for row in rows:
        if await overhead_source_state(session, row) != 'unchanged':
            raise service.AccountingError(f'Production overhead sources changed or cannot be verified for {row.month}; review and correct allocation before closing')


async def overhead_history(session, org_id, month):
    await service.lock_organization(session, org_id)
    rows = (await session.scalars(select(ProductionOverheadReceipt).where(
        ProductionOverheadReceipt.organization_id == org_id, ProductionOverheadReceipt.month == month)
        .order_by(ProductionOverheadReceipt.entry_id))).all()
    results = []
    for row in rows:
        results.append((row, await overhead_source_state(session, row)))
    return results


def allocation_lines(review):
    settings = review['source']['snapshot']['settings']
    analytical_orders = {row['order_id']: row['analytical_order'] for row in review['review']['orders']}
    lines = []
    for pool in review['allocations']:
        for share in pool['allocation']['shares']:
            if share['amount_byn'] == '0.00':
                continue
            lines.append({'account': settings['wip_account'], 'side': 'debit', 'amount': share['amount_byn'],
                'dimensions': {**pool['pool_dimensions'], settings['order_dimension']: analytical_orders[share['order_id']]}})
        lines.append({'account': pool['account'], 'side': 'credit', 'amount': pool['allocation']['amount_byn'],
            'dimensions': pool['pool_dimensions']})
    return lines


def posting_candidate(org_id, month, command, reviewed):
    if command.posting_date.strftime('%Y-%m') != month:
        raise service.AccountingError('Overhead posting date must belong to the reviewed month')
    review = reviewed['snapshot']
    included = {row.line_id for row in command.review.classifications if row.role != 'excluded'}
    latest = max(line['posting_date'] for line in review['source']['snapshot']['lines'] if line['line_id'] in included)
    if command.posting_date.isoformat() < latest:
        raise service.AccountingError('Overhead posting cannot precede the allocated cost entries')
    lines = allocation_lines(review)
    return PostingInput(source=f'production:overhead:{org_id}:{month}', source_version=1,
        operation='production_overhead', document_date=command.posting_date, operation_date=command.posting_date,
        posting_date=command.posting_date, policy_id=command.review.policy_id,
        rule_version='production-overhead-v1', explanation=command.evidence, lines=lines)


async def confirm_overhead(session, org_id, month, command, actor, production):
    await service.lock_organization(session, org_id)
    normalized = command.model_dump(mode='json')
    if await session.get(ProductionOverheadWithdrawal, (org_id, str(command.request_key))):
        raise service.AccountingError('Production overhead request was withdrawn; prepare a new reviewed request')
    existing = await session.scalar(select(ProductionOverheadReceipt).where(
        ProductionOverheadReceipt.organization_id == org_id, ProductionOverheadReceipt.request_key == str(command.request_key)))
    if existing:
        if existing.actor != actor or existing.command != normalized or existing.month != month:
            raise service.AccountingError('Overhead request conflicts with its stored confirmation')
        return existing
    if await session.scalar(select(ProductionOverheadReceipt.entry_id).where(
        ProductionOverheadReceipt.organization_id == org_id, ProductionOverheadReceipt.month == month)):
        raise service.AccountingError('Overhead already allocated for this month; use a correction workflow')
    reviewed = await review_costs(session, org_id, month, command.review, production)
    if reviewed['digest'] != command.expected_review_digest:
        raise service.AccountingError('Reviewed production allocation changed; repeat confirmation preview')
    posting = posting_candidate(org_id, month, command, reviewed)
    entry = await service.post(session, org_id, posting, actor, production_overhead=True)
    receipt = ProductionOverheadReceipt(entry_id=entry.id, organization_id=org_id, month=month,
        request_key=str(command.request_key), command=normalized, review=reviewed,
        posting=posting.model_dump(mode='json'), actor=actor)
    session.add(receipt)
    await session.flush()
    return receipt
