"""Internal finance-package access stays scoped to the current accounting book."""

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, update

from core.domain.models import User
from core.services.auth import CurrentUser, EffectiveIdentityLookupError
from modules.accounting import routes
from modules.accounting.gateway import AccountingService
from modules.accounting.models import AccessGrant


async def _seed_finance_member(
    db,
    organization_id,
    *,
    username,
    user_role,
    book_role,
    subject_id=None,
    status="active",
):
    db.add(
        User(
            username=username,
            full_name=username,
            keycloak_user_id=subject_id,
            role=user_role,
            status=status,
        )
    )
    actor = subject_id or username
    if book_role is not None:
        db.add(
            AccessGrant(
                organization_id=organization_id,
                subject=actor,
                role=book_role,
            )
        )
    await db.flush()
    return actor


def _finance_user(username, role="accountant", *, subject_id=None):
    return CurrentUser(username=username, roles=[role], keycloak_user_id=subject_id)


def _install_no_commit_sentinel(db, monkeypatch):
    attempts = []

    async def forbidden_commit(*_args, **_kwargs):
        attempts.append(True)
        raise AssertionError("finance_member must not commit")

    monkeypatch.setattr(db, "commit", forbidden_commit)
    return attempts


@pytest.mark.asyncio
async def test_finance_member_reader_read(db, book, monkeypatch):
    commit_attempts = _install_no_commit_sentinel(db, monkeypatch)
    actor = await _seed_finance_member(
        db,
        book[0],
        username="finance-reader",
        user_role="accountant",
        book_role="reader",
    )

    result = await AccountingService().finance_member(
        db, book[0], _finance_user("finance-reader"), write=False
    )

    assert actor == result == "finance-reader"
    assert db.in_transaction()
    assert commit_attempts == []


@pytest.mark.asyncio
async def test_finance_member_accountant_write(db, book, monkeypatch):
    commit_attempts = _install_no_commit_sentinel(db, monkeypatch)
    actor = await _seed_finance_member(
        db,
        book[0],
        username="finance-accountant",
        user_role="accountant",
        book_role="accountant",
    )

    result = await AccountingService().finance_member(
        db, book[0], _finance_user("finance-accountant", "accountant"), write=True
    )

    assert result == actor == "finance-accountant"
    assert commit_attempts == []


@pytest.mark.asyncio
async def test_finance_member_chief_write(db, book, monkeypatch):
    commit_attempts = _install_no_commit_sentinel(db, monkeypatch)
    actor = await _seed_finance_member(
        db,
        book[0],
        username="finance-chief",
        user_role="accountant",
        book_role="chief",
    )

    result = await AccountingService().finance_member(
        db, book[0], _finance_user("finance-chief"), write=True
    )

    assert result == actor == "finance-chief"
    assert commit_attempts == []


@pytest.mark.asyncio
async def test_finance_member_reader_write_denied(db, book):
    await _seed_finance_member(
        db,
        book[0],
        username="finance-reader-write",
        user_role="accountant",
        book_role="reader",
    )

    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(
            db, book[0], _finance_user("finance-reader-write"), write=True
        )

    assert error.value.status_code == 403
    assert error.value.detail == "Read-only finance access"


@pytest.mark.asyncio
async def test_finance_member_foreign_org_before_lock(db, book, monkeypatch):
    await _seed_finance_member(
        db,
        book[0],
        username="finance-foreign-book",
        user_role="accountant",
        book_role=None,
    )
    lock_calls = []
    original_lock = routes.service.lock_organization

    async def observe_lock(session, organization_id):
        lock_calls.append(organization_id)
        await original_lock(session, organization_id)

    monkeypatch.setattr(routes.service, "lock_organization", observe_lock)

    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(
            db, book[0], _finance_user("finance-foreign-book"), write=False
        )

    assert error.value.status_code == 403
    assert lock_calls == []


@pytest.mark.asyncio
async def test_finance_member_membership_revoked_after_lock(db, book, monkeypatch):
    actor = await _seed_finance_member(
        db,
        book[0],
        username="finance-revoked-member",
        user_role="accountant",
        book_role="accountant",
    )
    original_lock = routes.service.lock_organization

    async def lock_then_revoke(session, organization_id):
        await original_lock(session, organization_id)
        await session.execute(
            delete(AccessGrant).where(
                AccessGrant.organization_id == organization_id,
                AccessGrant.subject == actor,
            )
        )
        await session.flush()

    monkeypatch.setattr(routes.service, "lock_organization", lock_then_revoke)

    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(
            db, book[0], _finance_user("finance-revoked-member"), write=True
        )

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_finance_member_identity_suspended(db, book):
    subject_id = "finance-suspended-subject"
    await _seed_finance_member(
        db,
        book[0],
        username="finance-suspended",
        user_role="accountant",
        book_role="accountant",
        subject_id=subject_id,
        status="suspended",
    )

    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(
            db,
            book[0],
            _finance_user("finance-suspended", subject_id=subject_id),
            write=False,
        )

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_finance_member_finance_access_revoked(db, book, monkeypatch):
    subject_id = "finance-role-revoked-subject"
    await _seed_finance_member(
        db,
        book[0],
        username="finance-role-revoked",
        user_role="accountant",
        book_role="accountant",
        subject_id=subject_id,
    )
    original_lock = routes.service.lock_organization

    async def lock_then_revoke_package(session, organization_id):
        await original_lock(session, organization_id)
        await session.execute(
            update(User)
            .where(User.keycloak_user_id == subject_id)
            .values(role="finance")
            .execution_options(synchronize_session=False)
        )
        await session.flush()

    monkeypatch.setattr(routes.service, "lock_organization", lock_then_revoke_package)

    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(
            db,
            book[0],
            CurrentUser(
                username="finance-role-revoked",
                roles=["accountant", "finance"],
                keycloak_user_id=subject_id,
            ),
            write=False,
        )

    assert error.value.status_code == 403
    assert error.value.detail == "Finance access denied"


@pytest.mark.asyncio
async def test_finance_member_identity_subject_changed(db, book, monkeypatch):
    subject_id = "finance-original-subject"
    await _seed_finance_member(
        db,
        book[0],
        username="finance-subject-changed",
        user_role="accountant",
        book_role="accountant",
        subject_id=subject_id,
    )

    async def changed_subject(user, session):
        return CurrentUser(
            username=user.username,
            roles=["accountant"],
            keycloak_user_id="finance-replacement-subject",
        )

    monkeypatch.setattr(routes, "resolve_effective_oidc_user", changed_subject)

    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(
            db,
            book[0],
            _finance_user("finance-subject-changed", subject_id=subject_id),
            write=False,
        )

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_finance_member_oidc_lookup_failure(db, book, monkeypatch):
    subject_id = "finance-lookup-failure-subject"
    await _seed_finance_member(
        db,
        book[0],
        username="finance-lookup-failure",
        user_role="accountant",
        book_role="accountant",
        subject_id=subject_id,
    )

    async def fail_identity_lookup(user, session):
        raise EffectiveIdentityLookupError("lookup_failed")

    monkeypatch.setattr(routes, "resolve_effective_oidc_user", fail_identity_lookup)

    with pytest.raises(HTTPException) as error:
        await AccountingService().finance_member(
            db,
            book[0],
            _finance_user("finance-lookup-failure", subject_id=subject_id),
            write=False,
        )

    assert error.value.status_code == 403
    assert error.value.detail == "Current finance access could not be verified"
