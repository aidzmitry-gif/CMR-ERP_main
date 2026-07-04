"""Тесты вертикали лидов: приём → квалификация → распределение → сделка (ФАЗА 1)."""
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


# --- API: приём и жизненный цикл лида ---


async def test_lead_attachment_upload_list_download(session, api, monkeypatch, tmp_path):
    """Вложение лида: загрузка (data-URI) → список → скачивание байт назад."""
    import base64

    import modules.leads.storage as storage

    monkeypatch.setattr(storage, "_DATA_DIR", tmp_path / "leads-attachments")

    lead = (await api.post("/leads", json={"source": "tender", "company": "РУП Тест"})).json()
    lead_id = lead["id"]

    pdf_bytes = b"%PDF-1.4 fake content for test\n%%EOF"
    data_url = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode()

    r = await api.post(
        f"/leads/{lead_id}/attachments",
        json={"filename": "Спецификация.pdf", "data_url": data_url, "source": "tender"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["filename"] == "Спецификация.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["size_bytes"] == len(pdf_bytes)
    assert body["source"] == "tender"
    attachment_id = body["id"]

    listed = (await api.get(f"/leads/{lead_id}/attachments")).json()
    assert any(a["id"] == attachment_id for a in listed)

    dl = await api.get(f"/leads/{lead_id}/attachments/{attachment_id}/download")
    assert dl.status_code == 200
    assert dl.content == pdf_bytes
    assert dl.headers["content-type"] == "application/pdf"

    # чужой lead_id к тому же attachment_id — не найдено (нельзя скачать по чужому лиду)
    other_lead = (await api.post("/leads", json={"source": "site"})).json()
    assert (
        await api.get(f"/leads/{other_lead['id']}/attachments/{attachment_id}/download")
    ).status_code == 404


async def test_lead_attachment_rejects_bad_type_and_oversize(session, api, monkeypatch, tmp_path):
    """Граница доверия: неразрешённый тип и превышение размера — 422, файл не пишется."""
    import base64

    import modules.leads.storage as storage

    monkeypatch.setattr(storage, "_DATA_DIR", tmp_path / "leads-attachments")
    monkeypatch.setattr(storage, "MAX_SIZE_BYTES", 10)  # маленький лимит, чтобы не гонять 10 МБ в тесте

    lead = (await api.post("/leads", json={"source": "email"})).json()
    lead_id = lead["id"]

    bad_type_url = "data:application/x-msdownload;base64," + base64.b64encode(b"MZ...").decode()
    r1 = await api.post(
        f"/leads/{lead_id}/attachments",
        json={"filename": "virus.exe", "data_url": bad_type_url},
    )
    assert r1.status_code == 422

    oversize_url = "data:application/pdf;base64," + base64.b64encode(b"x" * 100).decode()
    r2 = await api.post(
        f"/leads/{lead_id}/attachments",
        json={"filename": "big.pdf", "data_url": oversize_url},
    )
    assert r2.status_code == 422

    assert (await api.get(f"/leads/{lead_id}/attachments")).json() == []


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


async def test_lead_route_manual_override(session, api):
    """Ручной выбор менеджера (Слайс 3): assigned_to из тела перебивает авто-правила."""
    lead = (
        await api.post(
            "/leads",
            json={"source": "site", "company": "ООО Минский", "region": "Минск", "product": "лист"},
        )
    ).json()
    await api.post(f"/leads/{lead['id']}/qualify")

    # без ручного выбора авто-правила отдали бы Иванова (Минск+лист) — переопределяем на Петрова
    r = await api.post(f"/leads/{lead['id']}/route", json={"assigned_to": "Петров П.П."})
    assert r.status_code == 200
    body = r.json()
    assert body["assigned_to"] == "Петров П.П."

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "leads.lead.routed" in types


async def test_lead_route_manual_rejects_unknown_manager(session, api):
    lead = (await api.post("/leads", json={"source": "site"})).json()
    r = await api.post(f"/leads/{lead['id']}/route", json={"assigned_to": "Неизвестный Ф.И.О."})
    assert r.status_code == 422


async def test_lead_managers_list_with_load(session, api):
    lead = (
        await api.post("/leads", json={"source": "site", "region": "Гомель", "product": "станок"})
    ).json()
    await api.post(f"/leads/{lead['id']}/route")  # авто → Петров (Гомель+станок), load=1

    r = await api.get("/leads/managers")
    assert r.status_code == 200
    managers = {m["name"]: m for m in r.json()}
    assert "Иванов И.И." in managers and "Петров П.П." in managers and "Сидоров С.С." in managers
    assert managers["Петров П.П."]["load"] == 1
    assert managers["Иванов И.И."]["load"] == 0

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "leads.lead.routed" in types


async def test_lead_reject(session, api):
    """Слайс 4: отклонение лида — терминальный статус + причина."""
    lead = (await api.post("/leads", json={"source": "site", "company": "ЧП Стройинструмент"})).json()

    r = await api.post(f"/leads/{lead['id']}/reject", json={"reason": "не наш профиль"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected"
    assert body["reject_reason"] == "не наш профиль"

    got = (await api.get(f"/leads/{lead['id']}")).json()
    assert got["status"] == "rejected"
    assert got["reject_reason"] == "не наш профиль"

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "leads.lead.rejected" in types


async def test_lead_reject_rejects_unknown_reason(session, api):
    lead = (await api.post("/leads", json={"source": "site"})).json()
    r = await api.post(f"/leads/{lead['id']}/reject", json={"reason": "просто не понравился"})
    assert r.status_code == 422


async def test_lead_reject_rejects_terminal_status(session, api):
    """Уже сконвертированный/отклонённый лид — 409, а не повторный отказ."""
    lead = (await api.post("/leads", json={"source": "site"})).json()
    await api.post(f"/leads/{lead['id']}/reject", json={"reason": "дубль"})

    r = await api.post(f"/leads/{lead['id']}/reject", json={"reason": "конкурент"})
    assert r.status_code == 409


async def test_lead_route_rejects_terminal_status(session, api):
    """Отклонённый лид нельзя распределить (409) — иначе drawer открыл бы раздачу мёртвому лиду."""
    lead = (await api.post("/leads", json={"source": "site"})).json()
    await api.post(f"/leads/{lead['id']}/reject", json={"reason": "дубль"})

    r = await api.post(f"/leads/{lead['id']}/route")
    assert r.status_code == 409


async def test_lead_route_sets_next_step(session, api):
    """Слайс 4: срок+заметка продавцу выставляются вместе с раздачей."""
    lead = (
        await api.post("/leads", json={"source": "site", "region": "Минск", "product": "лист"})
    ).json()
    await api.post(f"/leads/{lead['id']}/qualify")

    r = await api.post(
        f"/leads/{lead['id']}/route",
        json={"next_step_at": "2026-07-05T10:00:00", "next_step_note": "прозвонить, уточнить марку"},
    )
    assert r.status_code == 200

    got = (await api.get(f"/leads/{lead['id']}")).json()
    assert got["next_step_at"].startswith("2026-07-05T10:00:00")
    assert got["next_step_note"] == "прозвонить, уточнить марку"


async def test_lead_convert_creates_deal(session, api, services):
    from core.services.eventbus import EventContext

    lead = (
        await api.post(
            "/leads",
            json={"source": "site", "company": "ООО Конверт", "region": "Минск", "product": "лист"},
        )
    ).json()

    # без распределения конвертация запрещена
    assert (await api.post(f"/leads/{lead['id']}/convert")).status_code == 409

    await api.post(f"/leads/{lead['id']}/qualify")
    routed = (await api.post(f"/leads/{lead['id']}/route")).json()

    r = await api.post(f"/leads/{lead['id']}/convert")
    assert r.status_code == 201
    assert r.json()["status"] == "converted"

    # convert лишь публикует leads.lead.converted; сделку создаёт sales по подписке (cross-module).
    # relay дважды: leads.lead.converted → sales создаёт сделку (+sales.deal.created),
    # затем sales.deal.created → on_deal_created_from_lead проставляет лиду deal_id.
    await services.event_bus.relay_once(session, EventContext(session, services))
    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()

    # сделка появилась в воронке, ответственный = назначенный менеджер
    number = f"CRM-LEAD-{lead['id']}"
    deals = (await api.get("/sales/deals")).json()
    deal = next(d for d in deals if d["number"] == number)
    assert deal["owner"] == routed["assigned_to"]
    assert deal["stage"] == "new"

    # лид ссылается на сделку; повторная конвертация запрещена
    got = (await api.get(f"/leads/{lead['id']}")).json()
    assert got["deal_id"] is not None
    assert (await api.post(f"/leads/{lead['id']}/convert")).status_code == 409

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "leads.lead.converted" in types and "sales.deal.created" in types


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
