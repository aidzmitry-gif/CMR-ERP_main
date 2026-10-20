"""Local synthetic book/access checks for the public release integration."""
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from config import access
from core.services.auth import CurrentUser
from modules.accounting import routes
from modules.accounting.gateway import AccountingService
from modules.accounting.models import AccessGrant, Organization


@pytest.fixture
async def finance_book(session, monkeypatch):
    user = CurrentUser(username="synthetic-reader", roles=["accountant"],
                       keycloak_user_id="synthetic-subject")
    session.add_all([
        Organization(id=900001, name="Synthetic book", unp="111111111"),
        Organization(id=900002, name="Synthetic other book", unp="222222222"),
    ])
    await session.flush()
    session.add(AccessGrant(organization_id=900001, subject=user.keycloak_user_id, role="reader"))
    await session.flush()
    fresh = AsyncMock(return_value=user)
    monkeypatch.setattr(routes, "resolve_effective_oidc_user", fresh)
    return user, fresh


async def test_finance_reader_with_current_book_and_package_is_allowed(session, finance_book):
    user, fresh = finance_book
    assert await AccountingService().finance_member(session, 900001, user, write=False) == user.keycloak_user_id
    fresh.assert_awaited_once()


async def test_finance_permission_revoked_after_book_lock_is_denied(session, finance_book):
    user, fresh = finance_book
    fresh.return_value = CurrentUser(username=user.username, roles=["seller"], keycloak_user_id=user.keycloak_user_id)
    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(session, 900001, user, write=False)
    assert error.value.status_code == 403


async def test_finance_foreign_book_without_grant_is_denied(session, finance_book):
    user, fresh = finance_book
    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(session, 900002, user, write=False)
    assert error.value.status_code == 403
    fresh.assert_not_awaited()


async def test_finance_revoked_book_membership_is_denied(session, finance_book):
    user, fresh = finance_book
    await session.execute(delete(AccessGrant).where(AccessGrant.organization_id == 900001))
    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(session, 900001, user, write=False)
    assert error.value.status_code == 403
    fresh.assert_not_awaited()


async def test_finance_readonly_grant_cannot_write(session, finance_book):
    user, _ = finance_book
    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(session, 900001, user, write=True)
    assert error.value.status_code == 403


async def test_accounting_default_and_internal_finance_package_are_preserved(session, finance_book, monkeypatch):
    user, _ = finance_book
    allowed = Mock(wraps=access.is_package_allowed)
    monkeypatch.setattr(access, "is_package_allowed", allowed)
    assert await routes.current_member(session, 900001, user) == (user.keycloak_user_id, "reader")
    allowed.assert_called_once_with("accounting", user.roles)
    allowed.reset_mock()
    await AccountingService().finance_member(session, 900001, user, write=False)
    allowed.assert_called_once_with("finance", user.roles)


async def test_finance_changed_identity_is_denied(session, finance_book):
    user, fresh = finance_book
    fresh.return_value = CurrentUser(username=user.username, roles=user.roles, keycloak_user_id="different-subject")
    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(session, 900001, user, write=False)
    assert error.value.status_code == 403


async def test_query_cannot_choose_accounting_package_or_bypass_finance_denial(api, session, monkeypatch):
    gateway = api._transport.app.state.core.services.accounting
    member = AsyncMock(side_effect=HTTPException(403, "Synthetic finance denial"))
    monkeypatch.setattr(gateway, "finance_member", member)
    response = await api.get("/finance/reconcile-1c?organization_id=1&package=accounting")
    assert response.status_code == 403
    assert member.await_args.args[:2] == (session, 1)
    assert member.await_args.kwargs == {"write": False}
