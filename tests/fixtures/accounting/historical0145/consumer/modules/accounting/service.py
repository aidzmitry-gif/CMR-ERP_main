from __future__ import annotations
import hashlib
import json
from decimal import Decimal
from sqlalchemy import select
from core.domain.reference import Currency
from modules.accounting.models import Account, Audit, Entry, Line, Organization, Period, Policy
from modules.accounting.schemas import PostingInput

class AccountingError(ValueError):
    pass

async def lock_organization(session, organization_id):
    org = await session.scalar(select(Organization).where(Organization.id == organization_id).with_for_update().execution_options(populate_existing=True))
    if org is None:
        raise AccountingError('Organization not found')
    return org

def audit(session, org_id, actor, action, detail):
    session.add(Audit(organization_id=org_id, actor=actor, action=action, detail=detail))

async def period_for(session, org_id, month):
    row = await session.scalar(select(Period).where(Period.organization_id == org_id, Period.month == month).execution_options(populate_existing=True))
    if row is None:
        row = Period(organization_id=org_id, month=month, generation=0, closed=False)
        session.add(row)
        await session.flush()
    return row

async def accounts_on(session, org_id, on):
    rows = (await session.scalars(select(Account).where(Account.organization_id == org_id, Account.valid_from <= on).order_by(Account.valid_from, Account.id))).all()
    return {row.code: row for row in rows}

def digest(data):
    return hashlib.sha256(json.dumps(data.model_dump(mode='json'), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

async def validate_posting(session, org_id, data: PostingInput, *, inventory_issue=False, inventory_sale=False, financial_transfer=False, late_cost=False, production_overhead=False, production_correction=False, production_output_transfer=False, production_output_correction=False, production_labor_import=False, payroll_accrual_import=False, payroll_statutory_import=False, fixed_asset_depreciation=False, repair_accounting=False, fx_revaluation=False, settlement_offset=False):
    if data.operation == 'production_output_cost_correction' and (not production_output_correction):
        raise AccountingError('Output cost correction requires dedicated reviewed confirmation')
    if production_output_correction and (data.operation != 'production_output_cost_correction' or data.opening or (not data.correction_of)):
        raise AccountingError('Invalid internal output cost correction')
    if data.operation == 'production_overhead_correction' and (not production_correction):
        raise AccountingError('Production correction requires its dedicated reviewed confirmation')
    if production_correction and (data.operation != 'production_overhead_correction' or data.opening or (not data.correction_of)):
        raise AccountingError('Invalid internal production correction')
    if data.operation == 'production_output_transfer' and (not production_output_transfer):
        raise AccountingError('Production output transfer requires its dedicated reviewed confirmation')
    if production_output_transfer and (data.operation != 'production_output_transfer' or data.opening or data.correction_of):
        raise AccountingError('Invalid internal production output transfer')
    if data.operation == 'production_labor_import' and (not production_labor_import):
        raise AccountingError('Production labor imports require their dedicated reviewed confirmation')
    if production_labor_import and (data.operation != 'production_labor_import' or data.opening or data.correction_of):
        raise AccountingError('Invalid internal production labor import')
    if data.operation == 'payroll_accrual_import' and (not payroll_accrual_import):
        raise AccountingError('Payroll accrual imports require their dedicated reviewed confirmation')
    if payroll_accrual_import and (data.operation != 'payroll_accrual_import' or data.opening or data.correction_of):
        raise AccountingError('Invalid internal payroll accrual import')
    if data.operation == 'payroll_statutory_import' and (not payroll_statutory_import):
        raise AccountingError('Statutory payroll imports require their dedicated reviewed confirmation')
    if payroll_statutory_import and (data.operation != 'payroll_statutory_import' or data.opening or data.correction_of):
        raise AccountingError('Invalid internal statutory payroll import')
    if data.operation == 'fixed_asset_depreciation' and (not fixed_asset_depreciation):
        raise AccountingError('Fixed-asset depreciation requires its dedicated reviewed confirmation')
    if fixed_asset_depreciation and (data.operation != 'fixed_asset_depreciation' or data.opening or data.correction_of):
        raise AccountingError('Invalid internal fixed-asset depreciation')
    if data.operation == 'repair_service' and (not repair_accounting):
        raise AccountingError('Repair service postings require their dedicated reviewed confirmation')
    if repair_accounting and (data.operation != 'repair_service' or data.opening or data.correction_of):
        raise AccountingError('Invalid internal repair service operation')
    if data.operation == 'fx_revaluation' and (not fx_revaluation):
        raise AccountingError('FX revaluation requires its dedicated reviewed confirmation')
    if fx_revaluation and (data.operation != 'fx_revaluation' or data.opening):
        raise AccountingError('Invalid internal FX revaluation operation')
    if data.operation == 'settlement_offset' and (not settlement_offset):
        raise AccountingError('Settlement offsets require their dedicated reviewed confirmation')
    if settlement_offset and (data.operation != 'settlement_offset' or data.opening or data.correction_of):
        raise AccountingError('Invalid internal settlement offset operation')
    if data.operation == 'production_overhead' and (not production_overhead):
        raise AccountingError('Production overhead requires its dedicated reviewed confirmation')
    if production_overhead and (data.operation != 'production_overhead' or data.opening or data.correction_of):
        raise AccountingError('Invalid internal production overhead operation')
    if data.operation == 'inventory_late_cost' and (not late_cost):
        raise AccountingError('Late costs require the dedicated cost-layer confirmation rule')
    if late_cost and (data.operation != 'inventory_late_cost' or data.opening or data.correction_of):
        raise AccountingError('Invalid internal late-cost operation')
    if data.operation == 'inventory_sale' and (not inventory_sale):
        raise AccountingError('Inventory sales require the dedicated cost-confirmation rule')
    if data.operation == 'inventory_issue' and (not inventory_issue):
        raise AccountingError('Inventory issues require the dedicated cost-confirmation rule')
    if data.operation in {'period_close', 'period_reopen'} and (not financial_transfer):
        raise AccountingError('Financial-result transfer requires the dedicated closing or reopening command; period_close is reserved')
    if financial_transfer and (data.operation not in {'period_close', 'period_reopen'} or data.opening):
        raise AccountingError('Invalid internal financial transfer')
    month = data.posting_date.strftime('%Y-%m')
    closed = await session.scalar(select(Period.id).where(Period.organization_id == org_id, Period.month >= month, Period.closed.is_(True)).limit(1))
    if closed:
        raise AccountingError('Reopen this and all later closed periods before posting')
    policy = await session.scalar(select(Policy).where(Policy.organization_id == org_id, Policy.effective_from <= data.posting_date).order_by(Policy.effective_from.desc()).limit(1))
    reversing = financial_transfer and data.operation == 'period_reopen'
    if reversing:
        policy = await session.get(Policy, data.policy_id)
    if policy is None or policy.id != data.policy_id or policy.organization_id != org_id:
        raise AccountingError('An effective approved organization policy is required')
    if data.operation_date > data.posting_date or data.document_date > data.posting_date:
        raise AccountingError('Posting cannot precede the document or economic operation')
    previous = await session.scalar(select(Entry).where(Entry.organization_id == org_id, Entry.source == data.source, Entry.operation == data.operation).order_by(Entry.source_version.desc()).limit(1))
    if previous and (data.source_version <= previous.source_version or data.correction_of != previous.id):
        raise AccountingError('A later source version must explicitly correct its latest entry')
    if data.correction_of:
        original = await session.get(Entry, data.correction_of)
        if not original or original.organization_id != org_id:
            raise AccountingError('Correction must reference an entry in this organization')
        if original.operation in {'production_overhead', 'production_overhead_correction'} and (not production_correction):
            raise AccountingError('Production overhead corrections require a dedicated allocation correction workflow')
        if original.posting_date > data.posting_date:
            raise AccountingError('Correction cannot precede its original')
        if original.operation in {'period_close', 'period_reopen'} and (not reversing):
            raise AccountingError('Technical financial transfers require the dedicated reopening command')
        if reversing and (original.operation != 'period_close' or original.policy_id != data.policy_id):
            raise AccountingError('Financial reopening requires its original closing entry and policy')
    elif reversing:
        raise AccountingError('Financial reopening requires its original entry')
    if data.opening:
        existing = await session.scalar(select(Entry.id).where(Entry.organization_id == org_id, Entry.opening.is_(False)).limit(1))
        if existing or data.posting_date.day != 1 or data.correction_of:
            raise AccountingError('Opening balances must precede operations on the first of a month')
        other_date = await session.scalar(select(Entry.id).where(Entry.organization_id == org_id, Entry.opening.is_(True), Entry.posting_date != data.posting_date).limit(1))
        if other_date:
            raise AccountingError('Opening balances must share one cutover date')
    else:
        later_opening = await session.scalar(select(Entry.id).where(Entry.organization_id == org_id, Entry.opening.is_(True), Entry.posting_date > data.posting_date).limit(1))
        if later_opening:
            raise AccountingError('Posting predates imported opening balances')
    accounts = await accounts_on(session, org_id, data.posting_date)
    if reversing:
        original_lines = (await session.scalars(select(Line).where(Line.entry_id == data.correction_of))).all()
        accounts = {line.account_code: await session.get(Account, line.account_id) for line in original_lines}
    total = Decimal('0')
    has_on_balance = False
    foreign = {line.currency for line in data.lines if line.currency != 'BYN'}
    if foreign:
        known = set((await session.scalars(select(Currency.code).where(Currency.code.in_(foreign), Currency.is_active.is_(True)))).all())
        if foreign - known:
            raise AccountingError(f'Unknown or inactive currency: {sorted(foreign - known)}')
    categories = {accounts[line.account].category for line in data.lines if line.account in accounts}
    if not financial_transfer and (not data.opening) and ('equity' in categories) and categories & {'income', 'expense'}:
        raise AccountingError('Financial-result transfer between profit/loss and equity requires the dedicated closing command')
    for line in data.lines:
        account = accounts.get(line.account)
        if account is None:
            raise AccountingError(f'Account {line.account} is not effective for this organization')
        missing = set(account.required_dimensions) - line.dimensions.keys()
        if missing:
            raise AccountingError(f'Account {line.account}: missing analytics {sorted(missing)}')
        if line.currency != 'BYN' and (not account.currency_tracking):
            raise AccountingError(f'Account {line.account} does not support foreign currency')
        cost_only = late_cost and account.quantity_tracking and (line.quantity is None) and (line.side == 'debit')
        if cost_only and (account.category != 'asset' or account.cash or line.currency != 'BYN' or (line.account.split('.')[0] not in {'10', '41'})):
            raise AccountingError('Late cost requires owned BYN inventory')
        if production_output_correction and account.quantity_tracking and (line.quantity is None):
            if account.category != 'asset' or account.cash or line.currency != 'BYN':
                raise AccountingError('Output cost correction requires owned BYN inventory')
            cost_only = True
        if not cost_only and account.quantity_tracking != (line.quantity is not None):
            raise AccountingError(f'Account {line.account}: quantity tracking mismatch')
        if account.cash and (not data.opening) and (not line.cash_activity):
            raise AccountingError('Cash movement needs a cash-flow activity')
        if not account.cash and line.cash_activity:
            raise AccountingError('Only cash accounts may carry cash-flow activities')
        if account.category != 'off_balance':
            has_on_balance = True
            if line.amount == 0:
                raise AccountingError('On-balance amounts must be positive')
            total += line.amount if line.side == 'debit' else -line.amount
    if has_on_balance and total != 0:
        raise AccountingError('Debits and credits do not balance')
    return (accounts, policy)

async def preview_posting(session, org_id, data: PostingInput):
    """An identical retry remains previewable even after posting/period close."""
    existing = await session.scalar(select(Entry).where(Entry.organization_id == org_id, Entry.source == data.source, Entry.source_version == data.source_version, Entry.operation == data.operation))
    if existing is not None:
        if existing.digest != digest(data):
            raise AccountingError('Idempotency key reused with different content')
        return (await accounts_on(session, org_id, data.posting_date), await session.get(Policy, existing.policy_id))
    return await validate_posting(session, org_id, data)

async def post(session, org_id, data: PostingInput, actor, event_bus=None, *, inventory_issue=False, inventory_sale=False, financial_transfer=False, late_cost=False, production_overhead=False, production_correction=False, production_output_transfer=False, production_output_correction=False, production_labor_import=False, payroll_accrual_import=False, payroll_statutory_import=False, fixed_asset_depreciation=False, repair_accounting=False, fx_revaluation=False, settlement_offset=False):
    org = await lock_organization(session, org_id)
    existing = await session.scalar(select(Entry).where(Entry.organization_id == org_id, Entry.source == data.source, Entry.source_version == data.source_version, Entry.operation == data.operation))
    checksum = digest(data)
    if existing:
        if existing.digest != checksum:
            raise AccountingError('Idempotency key reused with different content')
        return existing
    accounts, _ = await validate_posting(session, org_id, data, inventory_issue=inventory_issue, inventory_sale=inventory_sale, financial_transfer=financial_transfer, late_cost=late_cost, production_overhead=production_overhead, production_correction=production_correction, production_output_transfer=production_output_transfer, production_output_correction=production_output_correction, production_labor_import=production_labor_import, payroll_accrual_import=payroll_accrual_import, payroll_statutory_import=payroll_statutory_import, fixed_asset_depreciation=fixed_asset_depreciation, repair_accounting=repair_accounting, fx_revaluation=fx_revaluation, settlement_offset=settlement_offset)
    period = await period_for(session, org_id, data.posting_date.strftime('%Y-%m'))
    entry = Entry(**data.model_dump(exclude={'lines'}), organization_id=org_id, digest=checksum, actor=actor)
    session.add(entry)
    await session.flush()
    for item in data.lines:
        account = accounts[item.account]
        session.add(Line(**item.model_dump(exclude={'account'}), entry_id=entry.id, account_id=account.id, account_code=account.code, account_title=account.title, category=account.category, cash=account.cash))
    affected = (await session.scalars(select(Period).where(Period.organization_id == org_id, Period.month >= period.month).execution_options(populate_existing=True))).all()
    for affected_period in affected:
        affected_period.generation += 1
        affected_period.evidence = {}
    org.generation += 1
    audit(session, org_id, actor, 'posted', {'entry_id': entry.id, 'digest': checksum})
    if event_bus is not None:
        event_bus.emit(session, 'accounting.entry.posted', {'organization_id': org_id, 'entry_id': entry.id, 'digest': checksum, 'source': data.source, 'source_version': data.source_version})
    await session.flush()
    return entry
