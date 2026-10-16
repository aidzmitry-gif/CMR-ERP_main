"""A book grant cannot retain access revoked while waiting for its lock."""
import pytest
from sqlalchemy import update

from core.domain.models import User
from modules.accounting import routes


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"status": "suspended"}, {"role": "sales"}])
async def test_identity_revoked_during_org_lock(client, db, book, monkeypatch, change):
    employee = User(username="tester", full_name="Synthetic accountant", role="director", status="active")
    db.add(employee)
    await db.commit()
    original = routes.organization_role

    async def wait_then_revoke(session, org_id, actor):
        role = await original(session, org_id, actor)
        # Keep the loaded object stale, as happens with another transaction.
        await session.execute(update(User).where(User.id == employee.id).values(**change)
                              .execution_options(synchronize_session=False))
        return role

    monkeypatch.setattr(routes, "organization_role", wait_then_revoke)
    response = await client.get(f"/accounting/organizations/{book[0]}/accounts?on=2026-09-19")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unlinked_dev_director_retains_book_access(client, book):
    response = await client.get(f"/accounting/organizations/{book[0]}/accounts?on=2026-09-19")
    assert response.status_code == 200

