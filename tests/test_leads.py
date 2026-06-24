"""Тесты вертикали лидов (модуль leads): приём → квалификация → распределение → конвертация.

После выноса лидов в отдельный модуль конвертация НЕ создаёт сделку напрямую —
публикует ``leads.lead.converted``, сделку создаёт модуль sales (проверяется на его стороне).
"""
from sqlalchemy import select

from core.domain.models import OutboxEvent

# --- Юнит: движок скоринга и распределения (без БД) ---


def test_score_lead_target_vs_non_target():
    from modules.leads.leads import QUALIFY_THRESHOLD, score_lead
    from modules.leads.models import Lead

    rich = Lead(
        source="site", company="ООО ТеплоСеть", phone="+375290000000",
        email="a@b.by", product="лист 5 мм",
        message="Нужен лист 5 мм, объём 15 т, пришлите цену и сроки.",
    )
    score, verdict, reason = score_lead(rich, known_customer=True)
    assert score >= QUALIFY_THRESHOLD
    assert verdict == "target"
    assert "телефон" in reason

    poor = Lead(source="phone", message="наличие?")
    score2, verdict2, _ = score_lead(poor, known_customer=False)
    assert verdict2 == "non-target"
    assert score2 < QUALIFY_THRESHOLD


def test_route_lead_by_region_and_product():
    from modules.leads.leads import route_lead
    from modules.leads.models import Lead

    # Минск + прокат → специалист Иванов независимо от нагрузки
    minsk = Lead(source="site", region="Минск", product="лист горячекатаный")
    manager, _ = route_lead(minsk, loads={}, known_customer=False)
    assert manager == "Иванов И.И."

    # Гомель + оборудование → Петров
    gomel = Lead(source="tender", region="Гомель", product="оборудование")
    manager2, funnel2 = route_lead(gomel, loads={}, known_customer=False)
    assert manager2 == "Петров П.П."
    assert funnel2 == "tender"  # источник tender → воронка тендеров


def test_route_lead_load_balancing():
    from modules.leads.leads import route_lead
    from modules.leads.models import Lead

    # без гео/продукта кандидаты — все; наименее загруженный побеждает
    generic = Lead(source="site")
    loads = {"Иванов И.И.": 3, "Петров П.П.": 1, "Сидоров С.С.": 5}
    assert route_lead(generic, loads, known_customer=False)[0] == "Петров П.П."


def test_choose_funnel():
    from modules.leads.leads import choose_funnel
    from modules.leads.models import Lead

    assert choose_funnel(Lead(source="tender"), False) == "tender"
    assert choose_funnel(Lead(source="site", message="проектная поставка"), False) == "project"
    assert choose_funnel(Lead(source="site"), known_customer=True) == "regular"
    assert choose_funnel(Lead(source="site"), known_customer=False) == "new"


# --- API: приём и жизненный цикл лида (модуль смонтирован под /leads) ---


async def test_leads_module_mounted(api):
    assert (await api.get("/leads/ping")).json()["module"] == "leads"


async def test_lead_intake_emits_event(session, api):
    r = await api.post(
        "/leads",
        json={"source": "site", "company": "ООО Тест", "phone": "+375290000000", "product": "лист"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "new"
    assert body["company"] == "ООО Тест"

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "leads.lead.received" in types

    # список и фильтр по статусу
    leads = (await api.get("/leads")).json()
    assert any(le["id"] == body["id"] for le in leads)
    new_only = (await api.get("/leads?status=new")).json()
    assert all(le["status"] == "new" for le in new_only)

    assert (await api.get("/leads/999999")).status_code == 404


async def test_lead_qualify_scores_and_emits(session, api):
    lead = (
        await api.post(
            "/leads",
            json={
                "source": "site", "company": "ООО Качество", "phone": "+375291112233",
                "email": "z@q.by", "product": "арматура",
                "message": "Нужна арматура 12, объём 8 т, сроки и цена?",
            },
        )
    ).json()

    r = await api.post(f"/leads/{lead['id']}/qualify")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "qualified"
    assert body["score"] > 0
    assert body["qualification"] in {"target", "non-target"}
    # AI выключен в тестах → текстового обоснования нет, но скоринг работает
    assert body["ai_rationale"] is None

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "leads.lead.qualified" in types

    assert (await api.post("/leads/999999/qualify")).status_code == 404


async def test_lead_route_assigns_manager(session, api):
    lead = (
        await api.post(
            "/leads",
            json={"source": "site", "company": "ООО Минский", "region": "Минск", "product": "лист"},
        )
    ).json()
    await api.post(f"/leads/{lead['id']}/qualify")

    r = await api.post(f"/leads/{lead['id']}/route")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "routed"
    assert body["assigned_to"] == "Иванов И.И."  # Минск + прокат
    assert body["funnel"] in {"new", "regular", "project", "tender"}

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "leads.lead.routed" in types


async def test_lead_convert_emits_converted_event(session, api):
    lead = (
        await api.post(
            "/leads",
            json={"source": "site", "company": "ООО Конверт", "region": "Минск", "product": "лист"},
        )
    ).json()

    # без распределения конвертация запрещена
    assert (await api.post(f"/leads/{lead['id']}/convert")).status_code == 409

    await api.post(f"/leads/{lead['id']}/qualify")
    await api.post(f"/leads/{lead['id']}/route")

    r = await api.post(f"/leads/{lead['id']}/convert")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "converted"
    assert body["lead_id"] == lead["id"]

    # сделку создаёт sales по событию (асинхронно через шину) — здесь проверяем публикацию
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "leads.lead.converted" in types

    # повторная конвертация запрещена
    assert (await api.post(f"/leads/{lead['id']}/convert")).status_code == 409


async def test_lead_known_customer_boosts_and_regular_funnel(session, api):
    from core.domain.models import Counterparty

    session.add(Counterparty(name="ООО Постоянный"))
    await session.commit()

    lead = (
        await api.post(
            "/leads",
            json={"source": "site", "company": "ООО Постоянный", "product": "лист", "region": "Минск"},
        )
    ).json()
    q = (await api.post(f"/leads/{lead['id']}/qualify")).json()
    assert "действующий контрагент" in q["reason"]

    routed = (await api.post(f"/leads/{lead['id']}/route")).json()
    assert routed["funnel"] == "regular"  # действующий клиент → воронка постоянных


# --- Юнит: AI-обоснование квалификации (AI включён, mock-режим) ---


async def test_ai_qualify_lead_unit():
    from core.services.litellm import LLMGateway
    from modules.leads.ai import qualify_lead
    from modules.leads.models import Lead

    class _Settings:
        ai_enabled = True
        llm_base_url = ""  # mock-режим
        llm_model = "qwen2.5"

    gateway = LLMGateway(_Settings())
    lead = Lead(source="site", company="ООО Клиент", region="Минск", product="лист", message="Запрос")
    text = await qualify_lead(gateway, lead, 80, "target")
    assert isinstance(text, str) and len(text) > 0


# --- Телефония → лид: входящий звонок с неизвестного номера заводит лид ---


def _call_ctx(session):
    from types import SimpleNamespace

    from core.services.eventbus import EventContext, OutboxEventBus

    return EventContext(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))


async def test_unknown_call_creates_lead(session):
    from modules.leads.events import on_call_logged
    from modules.leads.models import Lead

    await on_call_logged(
        {"direction": "in", "phone": "+375290000001", "agent_ext": "101"}, _call_ctx(session)
    )
    await session.commit()

    leads = (await session.execute(select(Lead))).scalars().all()
    assert len(leads) == 1
    assert leads[0].source == "phone"
    assert leads[0].phone == "+375290000001"
    assert leads[0].status == "new"
    assert "101" in leads[0].message

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "leads.lead.received" in types


async def test_known_caller_does_not_create_lead(session):
    from core.domain.models import Contact, Counterparty
    from modules.leads.events import on_call_logged
    from modules.leads.models import Lead

    cp = Counterparty(name="ООО Известный")
    session.add(cp)
    await session.flush()
    session.add(Contact(counterparty_id=cp.id, full_name="К", phone="+375291110000", is_primary=True))
    await session.commit()

    await on_call_logged({"direction": "in", "phone": "+375291110000"}, _call_ctx(session))
    await session.commit()

    assert (await session.execute(select(Lead))).scalars().first() is None


async def test_repeat_call_does_not_duplicate_lead(session):
    from modules.leads.events import on_call_logged
    from modules.leads.models import Lead

    payload = {"direction": "in", "phone": "+375290000002", "agent_ext": "102"}
    await on_call_logged(payload, _call_ctx(session))
    await session.commit()
    await on_call_logged(payload, _call_ctx(session))
    await session.commit()

    assert len((await session.execute(select(Lead))).scalars().all()) == 1


async def test_outgoing_call_ignored(session):
    from modules.leads.events import on_call_logged
    from modules.leads.models import Lead

    await on_call_logged({"direction": "out", "phone": "+375290000003"}, _call_ctx(session))
    await session.commit()
    assert (await session.execute(select(Lead))).scalars().first() is None
