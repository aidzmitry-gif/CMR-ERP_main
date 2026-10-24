"""Validate configured production accounts without choosing statutory defaults."""
from modules.accounting.service import AccountingError, accounts_on


async def validate_accounts(session, org_id, effective_date, settings):
    accounts = await accounts_on(session, org_id, effective_date)
    configured = [*settings.overhead_accounts, settings.wip_account]
    if settings.finished_goods_account is not None:
        configured.append(settings.finished_goods_account)
    for code in configured:
        account = accounts.get(code)
        if account is None:
            raise AccountingError(f'Production cost account {code} must exist for this organization and date')
        wip = code == settings.wip_account
        finished_goods = code == settings.finished_goods_account
        categories = {'asset'} if wip else {'asset', 'expense'}
        dimensions = set(settings.pool_dimensions) | ({settings.order_dimension} if wip else set())
        if finished_goods:
            categories = {'asset'}
            dimensions = set(account.required_dimensions)
            if (not account.quantity_tracking or account.cash or account.currency_tracking
                    or account.category not in categories):
                raise AccountingError(f'Finished goods account {code} must be a non-cash quantity-tracking asset')
            continue
        if account.category not in categories or account.cash or account.currency_tracking or account.quantity_tracking:
            raise AccountingError(f'Production cost account {code} has incompatible category or tracking')
        if set(account.required_dimensions) != dimensions:
            raise AccountingError(f'Production cost account {code} requires exact pool and order analytics')
    return accounts
