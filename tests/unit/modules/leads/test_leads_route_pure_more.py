from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select

from modules.leads import routes
from modules.leads.models import Lead


def test_mark_first_action_sets_clock_once(monkeypatch):
    first_action = datetime(2026, 9, 17, 8, 30)
    lead = Lead(source="site")
    monkeypatch.setattr(routes, "_utcnow", lambda: first_action)

    routes._mark_first_action(lead)
    assert lead.first_action_at == first_action

    monkeypatch.setattr(routes, "_utcnow", lambda: datetime(2026, 9, 17, 9, 0))
    routes._mark_first_action(lead)
    assert lead.first_action_at == first_action


def test_apply_score_updates_qualification_without_overwriting_existing_status(monkeypatch):
    action_at = datetime(2026, 9, 17, 8, 30)
    monkeypatch.setattr(routes, "_utcnow", lambda: action_at)

    new_lead = Lead(source="site", status="new")
    routes._apply_score(new_lead, 72, "target", "есть телефон")
    assert (new_lead.score, new_lead.qualification, new_lead.reason) == (
        72,
        "target",
        "есть телефон",
    )
    assert new_lead.status == "qualified"
    assert new_lead.first_action_at == action_at

    routed_at = datetime(2026, 9, 17, 7, 0)
    routed_lead = Lead(source="site", status="routed", first_action_at=routed_at)
    routes._apply_score(routed_lead, 20, "non-target", "недостаточно данных")
    assert routed_lead.status == "routed"
    assert routed_lead.first_action_at == routed_at


def test_route_rationale_explains_key_conversion_and_rules_paths():
    assert routes._route_rationale("Иванов", {"Иванов": 4}, {"Иванов": 0.816}, key=True) == (
        "🔑 ключевой → Иванов: конверсия 82%"
    )
    assert routes._route_rationale("Иванов", {"Иванов": 4}, {"Иванов": 0.816}) == (
        "Иванов: конверсия 82%, загрузка 4"
    )
    assert routes._route_rationale("Петров", {}, {}) == "Петров: по правилам (гео/продукт), загрузка 0"


def test_apply_route_assigns_route_and_optional_next_step_without_resetting_first_action(monkeypatch):
    routed_at = datetime(2026, 9, 17, 10, 15)
    original_action = datetime(2026, 9, 17, 9, 0)
    next_step = datetime(2026, 9, 18, 8, 0)
    monkeypatch.setattr(routes, "_utcnow", lambda: routed_at)
    lead = Lead(source="site", first_action_at=original_action)

    routes._apply_route(lead, "Иванов И.И.", "new", next_step, None)

    assert (lead.assigned_to, lead.funnel, lead.status, lead.routed_at) == (
        "Иванов И.И.",
        "new",
        "routed",
        routed_at,
    )
    assert (lead.first_action_at, lead.next_step_at, lead.next_step_note) == (
        original_action,
        next_step,
        "",
    )


def test_activity_window_and_item_totals_query_cover_all_business_activity_columns():
    since = datetime(2026, 9, 1)
    activity_sql = str(select(Lead.id).where(routes._activity_in_window(since)))
    assert "leads.lead.created_at >=" in activity_sql
    assert "leads.lead.routed_at >=" in activity_sql
    assert "leads.lead.converted_at >=" in activity_sql

    totals = routes._lead_item_totals_subquery()
    totals_sql = str(select(totals.c.lead_id, totals.c.lead_total))
    assert set(totals.c.keys()) == {"lead_id", "lead_total"}
    assert "sum(leads.lead_item.qty * leads.lead_item.price)" in totals_sql
    assert "GROUP BY leads.lead_item.lead_id" in totals_sql


def test_plan_out_keeps_targets_and_facts_in_the_response_contract():
    plan = SimpleNamespace(
        leads_target=20,
        qualified_target=8,
        converted_target=3,
        reaction_target_min=15,
    )

    out = routes._plan_out(plan, (19, 7, 2, None))

    assert out.model_dump() == {
        "leads_target": 20,
        "qualified_target": 8,
        "converted_target": 3,
        "reaction_target_min": 15,
        "leads_fact": 19,
        "qualified_fact": 7,
        "converted_fact": 2,
        "reaction_fact_min": None,
    }
