"""Единое планирование продавца (sales-plan-unified): комментарий РОПа, возврат плана в
работу (reopen) и доска с согласованным планом + кумулятивным добором недобора.

SQLite в памяти. Роль `api`-фикстуры (director) имеет sales.deal.write и .approve.
"""
from decimal import Decimal

from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.sales.models import PlanTarget


async def _approved_plan(api, owner_id, metric, period_key, target):
    """Провести план через полный путь: draft → submit → decide(approve)."""
    created = await api.post(
        "/sales/plans",
        json={
            "owner_id": owner_id,
            "metric": metric,
            "period_type": "month",
            "period_key": period_key,
            "target": target,
        },
    )
    assert created.status_code == 200
    pid = created.json()["id"]
    assert (await api.post(f"/sales/plans/{pid}/submit")).status_code == 200
    return pid


# ── decide + комментарий РОПа ───────────────────────────────────────────────

async def test_decide_approve_writes_rop_comment(api):
    pid = await _approved_plan(api, 1, "gross_profit", "2026-07", 50000)
    r = await api.post(
        f"/sales/plans/{pid}/decide",
        json={"approved": True, "comment": "держим темп по Белтрансу"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["rop_comment"] == "держим темп по Белтрансу"

    # виден в списке (PlanTargetOut)
    lst = (await api.get("/sales/plans?owner_id=1")).json()
    assert lst[0]["rop_comment"] == "держим темп по Белтрансу"


async def test_decide_reject_writes_rop_comment(api):
    pid = await _approved_plan(api, 2, "gross_profit", "2026-07", 40000)
    r = await api.post(
        f"/sales/plans/{pid}/decide",
        json={"approved": False, "comment": "цель занижена, подними по постоянным"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected"
    assert body["rop_comment"] == "цель занижена, подними по постоянным"


# ── reopen: согласованный план обратно в работу ─────────────────────────────

async def test_reopen_approved_to_draft_emits_event(session, api):
    pid = await _approved_plan(api, 3, "gross_profit", "2026-07", 60000)
    approve = await api.post(f"/sales/plans/{pid}/decide", json={"approved": True})
    assert approve.json()["status"] == "approved"

    r = await api.post(f"/sales/plans/{pid}/reopen", json={"reason": "пересмотр по новому приходу"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft"
    assert body["approved_by"] is None
    assert body["approved_at"] is None
    assert body["rop_comment"] == "пересмотр по новому приходу"

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "sales.plan.reopened" in types


async def test_reopen_rejects_non_approved(api):
    # draft-план (без submit/approve) вернуть в работу нельзя → 409
    created = await api.post(
        "/sales/plans",
        json={
            "owner_id": 4,
            "metric": "gross_profit",
            "period_type": "month",
            "period_key": "2026-07",
            "target": 30000,
        },
    )
    pid = created.json()["id"]
    r = await api.post(f"/sales/plans/{pid}/reopen", json={})
    assert r.status_code == 409


# ── доска: согласованный план как «План» + кумулятивный добор ────────────────

async def _seed_approved(session, owner_id, metric, period_key, target):
    session.add(
        PlanTarget(
            owner_id=owner_id,
            metric=metric,
            period_type="month",
            period_key=period_key,
            target=Decimal(str(target)),
            status="approved",
        )
    )
    await session.commit()


async def test_kpis_owner_id_uses_approved_plan(session, api):
    # согласованный план текущего месяца → «План» метрики = его target (не дневная цель × mult)
    await _seed_approved(session, 7, "gross_profit", "2026-07", 50000)

    with_owner = (await api.get("/sales/kpis?period=2026-07&owner_id=7")).json()
    gp = next(k for k in with_owner if k["key"] == "gross_profit")
    assert gp["target"] == 50000.0

    # без owner_id — прежнее поведение (дневная цель × рабочие дни), НЕ равно плану продавца
    without = (await api.get("/sales/kpis?period=2026-07")).json()
    gp0 = next(k for k in without if k["key"] == "gross_profit")
    assert gp0["target"] != 50000.0


async def test_kpis_owner_cumulative_carryover(session, api):
    # payments_vat — метрика с РЕАЛЬНЫМ фактом: прошлый месяц недобрал (факт 0) →
    # недобор нарастающим итогом поднимает цель текущего месяца.
    await _seed_approved(session, 8, "payments_vat", "2026-06", 10000)
    await _seed_approved(session, 8, "payments_vat", "2026-07", 20000)

    res = (await api.get("/sales/kpis?period=2026-07&owner_id=8")).json()
    pv = next(k for k in res if k["key"] == "payments_vat")
    # target = план июля 20000 + добор (план июня 10000 − факт июня 0) = 30000
    assert pv["target"] == 30000.0


async def test_kpis_gross_profit_excluded_from_carryover(session, api):
    # gross_profit факт структурно 0 (нет landed-cost) → добор НЕ применяется, иначе цель
    # раздувалась бы на весь план прошлых месяцев, маскируя реальный недобор.
    await _seed_approved(session, 9, "gross_profit", "2026-06", 10000)
    await _seed_approved(session, 9, "gross_profit", "2026-07", 20000)

    res = (await api.get("/sales/kpis?period=2026-07&owner_id=9")).json()
    gp = next(k for k in res if k["key"] == "gross_profit")
    assert gp["target"] == 20000.0  # только план июля, без ложного добора


async def test_kpis_owner_override_month_only(session, api):
    # оверрайд согласованным месячным планом — только для месячного периода; на дневном
    # виде месячная цель НЕ подставляется против дневного факта (иначе бессмысленный процент).
    await _seed_approved(session, 10, "payments_vat", "2026-07", 20000)

    day = (await api.get("/sales/kpis?period=day&owner_id=10")).json()
    pv = next(k for k in day if k["key"] == "payments_vat")
    assert pv["target"] != 20000.0
