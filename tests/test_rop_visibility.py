"""ROP facts follow the same persisted employee scope as CRM deal lists."""
from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from core.domain.models import User
from core.services.auth import CurrentUser
from modules.sales.models import Deal
from tests.test_identity_effective_access import _effective_access_client

PATH = "/sales/rop/plan-fact?period=2026-09"
HEADERS = {"X-User": "synthetic-rop-actor", "X-User-Roles": "sales"}


@pytest_asyncio.fixture
async def rop_scope_case(session):
    actor = User(
        username=HEADERS["X-User"], full_name="Shared synthetic owner", employee_id=101,
        keycloak_user_id="synthetic-rop-subject", department="Продажи", role="sales",
        status="active", deal_visibility="all",
    )
    session.add_all([
        actor,
        User(username="synthetic-rop-other", full_name=actor.full_name, employee_id=202,
             department="Продажи", role="sales", status="active", deal_visibility="all"),
    ])
    for number, owner_id, amount, stage, changed in [
        ("OWN", 101, "11", "won", datetime(2026, 9, 15)),
        ("OTHER", 202, "23", "won", datetime(2026, 9, 15)),
        ("UNASSIGNED", None, "37", "won", datetime(2026, 9, 15)),
        ("NOT-WON", 101, "101", "new", datetime(2026, 9, 15)),
        ("OTHER-MONTH", 101, "41", "won", datetime(2026, 8, 15)),
    ]:
        session.add(Deal(
            number="SYNTHETIC-ROP-" + number, title="Synthetic scope case",
            counterparty="Synthetic customer", owner=actor.full_name, owner_id=owner_id,
            amount=Decimal(amount), stage=stage, stage_changed_at=changed,
        ))
    await session.commit()
    return actor


def facts(response):
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["period"] == "2026-09"
    return (
        sum(row["fact_deals"] for row in data["managers"]),
        sum(Decimal(str(row["fact_revenue"])) for row in data["managers"]),
    )


async def test_rop_fact_uses_numeric_scope_and_current_persisted_visibility(api, session, rop_scope_case):
    assert facts(await api.get(PATH, headers=HEADERS)) == (3, Decimal("71"))
    assert facts(await api.get(PATH, headers={
        "X-User": "synthetic-unlinked-director", "X-User-Roles": "director",
    })) == (3, Decimal("71"))
    rop_scope_case.deal_visibility = "own"
    await session.commit()
    own = await api.get(PATH, headers=HEADERS)
    assert facts(own) == (1, Decimal("11"))
    assert own.json()["managers"][0]["name"] == rop_scope_case.full_name
    assert facts(await api.get(PATH + "&owner_id=202", headers={
        **HEADERS, "X-Owner-Id": "202",
    })) == (1, Decimal("11"))
    assert (await api.get(PATH, headers={**HEADERS, "X-User-Roles": "director"})).status_code == 403
    assert (await api.get("/sales/journal", headers=HEADERS)).status_code == 403
    rop_scope_case.deal_visibility = "all"
    await session.commit()
    assert facts(await api.get(PATH, headers=HEADERS)) == (3, Decimal("71"))


@pytest.mark.parametrize("problem", ["missing_employee", "inactive", "unknown_user", "invalid_visibility"])
async def test_rop_fact_refuses_unusable_dev_identity(api, session, rop_scope_case, problem):
    rop_scope_case.deal_visibility = "own"
    headers = dict(HEADERS)
    if problem == "missing_employee":
        rop_scope_case.employee_id = None
    elif problem == "inactive":
        rop_scope_case.status = "inactive"
    elif problem == "unknown_user":
        headers["X-User"] = "synthetic-unknown-rop-user"
    else:
        rop_scope_case.deal_visibility = "unknown"
        # Invalid visibility never reaches HTTP: the real storage constraint
        # rejects it before an unsafe identity can become request state.
        with pytest.raises(IntegrityError, match="ck_app_user_deal_visibility"):
            await session.commit()
        await session.rollback()
        return
    await session.commit()
    response = await api.get(PATH, headers=headers)
    assert response.status_code == 403
    assert rop_scope_case.full_name not in response.text


@pytest.mark.parametrize("scenario", ["renamed", "unknown_subject", "unlinked_subject", "inactive_subject"])
async def test_rop_fact_binds_oidc_subject(session, monkeypatch, rop_scope_case, scenario):
    rop_scope_case.deal_visibility = "own"
    username, subject = rop_scope_case.username, rop_scope_case.keycloak_user_id
    if scenario == "renamed":
        username = "synthetic-old-username"
    elif scenario == "unknown_subject":
        subject = "synthetic-unknown-subject"
    elif scenario == "unlinked_subject":
        rop_scope_case.keycloak_user_id = None
    else:
        rop_scope_case.status = "suspended"
    await session.commit()
    client = await _effective_access_client(session, monkeypatch, CurrentUser(username, ["sales"], subject))
    async with client:
        response = await client.get(PATH)
    if scenario == "renamed":
        assert facts(response) == (1, Decimal("11"))
    else:
        assert response.status_code == 403
        assert rop_scope_case.full_name not in response.text
