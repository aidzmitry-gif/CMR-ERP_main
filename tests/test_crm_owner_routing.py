"""Real lead owners, pre-commit validation and legacy delivery compatibility."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select, update

from core.domain.models import OutboxEvent, User
from core.services.eventbus import EventContext
from modules.leads.leads import route_lead
from modules.leads.models import Lead
from modules.sales.models import Deal


def _owner(name="Реальный менеджер", **overrides):
    fields = dict(username="owner", full_name=name, employee_id=901,
                  department="Продажи", role="sales", status="active", deal_visibility="own")
    fields.update(overrides)
    return User(**fields)


async def _routed_lead(session, name="Реальный менеджер"):
    lead = Lead(source="site", company="Synthetic owner contract", status="routed", assigned_to=name)
    session.add(lead)
    await session.commit()
    return lead


@pytest.mark.parametrize("case", [
    "missing", "inactive", "onboarding", "department", "role", "employee", "ambiguous", "blank",
])
async def test_invalid_owner_does_not_convert_or_emit(session, api, case):
    if case not in {"missing", "blank"}:
        changes = {
            "inactive": {"status": "inactive"},
            "onboarding": {"status": "onboarding"},
            "department": {"department": "Финансы / офис"},
            "role": {"role": "hr"},
            "employee": {"employee_id": None},
        }.get(case, {})
        session.add(_owner(**changes))
        if case == "ambiguous":
            session.add(_owner(username="duplicate", employee_id=902))
    name = "" if case == "blank" else "Реальный менеджер"
    lead = await _routed_lead(session, name)
    baseline = await session.scalar(select(func.count()).select_from(OutboxEvent))

    response = await api.post(f"/leads/{lead.id}/convert")

    assert response.status_code == 422, response.text
    await session.refresh(lead)
    assert lead.status == "routed" and lead.converted_at is None and lead.deal_id is None
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == baseline
    assert await session.scalar(select(func.count()).select_from(Deal)) == 0


async def test_managers_and_automatic_route_use_only_unambiguous_real_users(session, api):
    session.add_all([
        _owner("Анна", username="anna", employee_id=901),
        _owner("Борис", username="boris", employee_id=902),
        _owner("Отключён", username="inactive", employee_id=903, status="inactive"),
        _owner("Нет связи", username="unlinked", employee_id=None),
        _owner("Другой отдел", username="finance", employee_id=904, department="Финансы / офис"),
        _owner("Другой доступ", username="role", employee_id=905, role="onboarding"),
        _owner("Двойное имя", username="duplicate-a", employee_id=906),
        _owner("Двойное имя", username="duplicate-b", employee_id=907),
    ])
    session.add(Lead(source="site", status="routed", assigned_to="Анна"))
    lead = Lead(source="site", region="Минск", product="лист", status="qualified")
    session.add(lead)
    await session.commit()

    response = await api.get("/leads/managers")
    assert response.status_code == 200
    assert response.json() == [
        {"name": "Анна", "regions": [], "products": [], "load": 1},
        {"name": "Борис", "regions": [], "products": [], "load": 0},
    ]
    routed = await api.post(f"/leads/{lead.id}/route")
    assert routed.status_code == 200, routed.text
    assert routed.json()["assigned_to"] == "Борис"


async def test_no_real_candidates_do_not_fall_back_to_demo_managers(session, api):
    lead = Lead(source="site", status="qualified")
    session.add(lead)
    await session.commit()
    assert (await api.get("/leads/managers")).json() == []
    response = await api.post(f"/leads/{lead.id}/route")
    assert response.status_code == 422
    await session.refresh(lead)
    assert lead.status == "qualified" and not lead.assigned_to
    with pytest.raises(ValueError, match="Нет доступных"):
        route_lead(lead, {}, False, managers=[])


@pytest.mark.parametrize("role", ["sales_head", "sales", "sales_manager", "sales_cli"])
async def test_conversion_uses_employee_id_and_enforces_deal_visibility(session, api, role):
    owner = _owner(id=11, role=role)
    foreign = _owner("Другой менеджер", id=12, username="foreign", employee_id=902)
    session.add_all([owner, foreign])
    lead = await _routed_lead(session)
    response = await api.post(f"/leads/{lead.id}/convert")
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["deal_id"] is not None
    deal = await session.get(Deal, result["deal_id"])
    assert deal.owner_id == owner.employee_id == 901
    assert deal.owner_id != owner.id
    assert deal.owner == owner.full_name
    event = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "leads.lead.converted",
    ))).scalar_one()
    assert event.payload["owner_id"] == 901 and event.payload["owner"] == owner.full_name
    own_headers = {"X-User": owner.username, "X-User-Roles": "sales"}
    foreign_headers = {"X-User": foreign.username, "X-User-Roles": "sales"}
    assert (await api.get(f"/sales/deals/{deal.id}", headers=own_headers)).status_code == 200
    assert (await api.get(f"/sales/deals/{deal.id}", headers=foreign_headers)).status_code == 404
    assert (await api.post(f"/leads/{lead.id}/convert")).status_code == 409
    assert await session.scalar(select(func.count()).select_from(Deal)) == 1


async def test_conversion_refreshes_cached_lead_before_status_check(session, api):
    session.add(_owner())
    lead = await _routed_lead(session)
    await session.execute(update(Lead).where(Lead.id == lead.id).values(status="converted")
                          .execution_options(synchronize_session=False))
    await session.commit()
    assert lead.status == "routed"  # Simulate a cached read preceding a concurrent commit.
    response = await api.post(f"/leads/{lead.id}/convert")
    assert response.status_code == 409
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    assert await session.scalar(select(func.count()).select_from(Deal)) == 0


@pytest.mark.parametrize("numeric_owner,deactivate", [(False, False), (False, True), (True, True)])
async def test_relay_preserves_assignment_snapshot_and_legacy_replay(
    session, services, numeric_owner, deactivate,
):
    owner = _owner()
    session.add(owner)
    lead = await _routed_lead(session)
    payload = {"lead_id": lead.id, "owner": owner.full_name, "title": "Snapshot"}
    if numeric_owner:
        payload["owner_id"] = owner.employee_id
    services.event_bus.emit(session, "leads.lead.converted", payload)
    await session.commit()
    if deactivate:
        owner.status = "inactive"
        owner.full_name = "Новое имя"
        await session.commit()
    ctx = EventContext(session, services)
    await services.event_bus.relay_once(session, ctx)
    await services.event_bus.relay_once(session, ctx)
    services.event_bus.emit(session, "leads.lead.converted", payload)
    await session.commit()
    await services.event_bus.relay_once(session, ctx)

    deal = (await session.execute(select(Deal))).scalar_one()
    assert deal.owner == "Реальный менеджер"
    assert deal.owner_id == (901 if numeric_owner else None)
    await session.refresh(lead)
    assert lead.deal_id == deal.id
    assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.processed_at.is_(None),
    )) == 0
