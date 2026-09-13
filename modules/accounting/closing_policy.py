"""Explicit organization policy for technical transfers; no statutory defaults."""
from modules.accounting.service import AccountingError, accounts_on


async def validate_accounts(session, org_id, effective_date, settings):
    accounts = await accounts_on(session, org_id, effective_date)
    roles = [(code, {"income", "expense"}, None) for code in settings.monthly_accounts]
    roles += [(settings.result_account, {"income"}, settings.result_dimensions),
              (settings.retained_earnings_account, {"equity"}, settings.retained_dimensions)]
    for code, categories, dimensions in roles:
        account = accounts.get(code)
        if account is None:
            raise AccountingError(f"Closing account {code} must exist in this organization on the policy date")
        if account.category not in categories or account.cash or account.quantity_tracking:
            raise AccountingError(f"Closing account {code} has an incompatible category or tracking configuration")
        if dimensions is not None and set(dimensions) != set(account.required_dimensions):
            raise AccountingError(f"Closing account {code} requires its exact configured analytics")
    return accounts
