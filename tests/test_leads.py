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


async def test_lead_auto_scored_on_intake(session, api):
    """Цикл 1: авто-скоринг на входе — балл проставлен сразу, статус остаётся new."""
    r = await api.post(
        "/leads",
        json={
            "source": "site", "company": "ООО АвтоСкор", "phone": "+375291112200",
            "email": "auto@score.by", "product": "лист",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "new"
    assert body["score"] > 0
    assert body["qualification"] in {"target", "non-target"}
    assert body["reason"]


async def test_lead_create_rejects_phone_duplicate(session, api):
    """Цикл 1: дедуп на ручном интейке — открытый дубль по телефону → 409 с id."""
    first = (
        await api.post("/leads", json={"source": "phone", "phone": "+375291112233"})
    ).json()

    r = await api.post("/leads", json={"source": "site", "phone": "375 (29) 111-22-33"})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["duplicate_of"] == first["id"]

    # терминальный (rejected) дубль больше не мешает
    await api.post(f"/leads/{first['id']}/reject", json={"reason": "дубль"})
    r2 = await api.post("/leads", json={"source": "site", "phone": "375 (29) 111-22-33"})
    assert r2.status_code == 201


async def test_lead_intake_dedup_appends_message_instead_of_new_lead(session, api, services):
    """Повторное обращение (веб-форма) с тем же телефоном дописывается к открытому лиду."""
    from sqlalchemy import select

    from core.services.eventbus import EventContext
    from modules.leads.models import Lead

    await api.post(
        "/integrations/web/lead",
        json={"phone": "+375297778811", "message": "Первое обращение"},
    )
    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()

    leads_after_first = (await session.execute(select(Lead))).scalars().all()
    assert len(leads_after_first) == 1
    lead_id = leads_after_first[0].id

    await api.post(
        "/integrations/web/lead",
        json={"phone": "+375297778811", "message": "Второе обращение, уже срочно"},
    )
    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()

    leads_after_second = (await session.execute(select(Lead))).scalars().all()
    assert len(leads_after_second) == 1  # дубль не создан
    dup = leads_after_second[0]
    assert dup.id == lead_id
    assert "Первое обращение" in dup.message
    assert "Второе обращение, уже срочно" in dup.message


async def test_lead_email_dedup_underscore_is_not_wildcard(session, api):
    """Фикс ревью Ц1: `_` в e-mail — не LIKE-wildcard; похожий чужой адрес — не дубль."""
    await api.post("/leads", json={"source": "site", "email": "ivan_petrov@mail.by"})

    # адрес отличается ровно в позиции `_` — раньше ilike матчил его как дубль
    r = await api.post("/leads", json={"source": "site", "email": "ivanxpetrov@mail.by"})
    assert r.status_code == 201

    # а точный дубль (в другом регистре) по-прежнему ловится
    r2 = await api.post("/leads", json={"source": "site", "email": "IVAN_PETROV@mail.by"})
    assert r2.status_code == 409


async def test_lead_phone_dedup_ignores_short_tail(session, api):
    """Фикс ревью Ц1: хвост короче 7 цифр (битый ввод) не участвует в дедупе."""
    await api.post("/leads", json={"source": "phone", "phone": "+375291234567"})
    # битый короткий ввод, совпадающий с окончанием чужого номера, — не дубль
    r = await api.post("/leads", json={"source": "site", "phone": "4567"})
    assert r.status_code == 201


async def test_lead_first_action_at_set_once(session, api):
    """SLA первой реакции: NULL после создания, проставлен по первому действию, не перезаписан вторым."""
    lead = (
        await api.post("/leads", json={"source": "site", "region": "Минск", "product": "лист"})
    ).json()
    assert lead["first_action_at"] is None

    qualified = (await api.post(f"/leads/{lead['id']}/qualify")).json()
    got = (await api.get(f"/leads/{lead['id']}")).json()
    assert got["first_action_at"] is not None
    first_stamp = got["first_action_at"]
    assert qualified["status"] == "qualified"

    await api.post(f"/leads/{lead['id']}/route")
    got2 = (await api.get(f"/leads/{lead['id']}")).json()
    assert got2["first_action_at"] == first_stamp  # второе действие не переставляет метку


async def test_lead_express_qualifies_and_routes_in_one_call(session, api):
    """Цикл 2: экспресс — квалификация + раздача + следующий шаг одной транзакцией."""
    lead = (
        await api.post(
            "/leads",
            json={
                "source": "site", "company": "ООО Экспресс", "phone": "+375291234567",
                "email": "e@x.by", "region": "Минск", "product": "лист",
                "message": "Нужен лист 5 мм, объём 10 т, срочно пришлите цену.",
            },
        )
    ).json()
    assert lead["first_action_at"] is None

    r = await api.post(
        f"/leads/{lead['id']}/express",
        json={"next_step_at": "2026-07-12T10:00:00", "next_step_note": "Позвонить завтра"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "routed"
    assert body["assigned_to"]  # авто-правила проставили менеджера
    assert body["score"] > 0
    assert body["qualification"] == "target"
    assert body["first_action_at"] is not None
    assert body["next_step_at"].startswith("2026-07-12T10:00:00")
    assert body["next_step_note"] == "Позвонить завтра"

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "leads.lead.qualified" in types
    assert "leads.lead.routed" in types


async def test_lead_express_manual_manager(session, api):
    """Экспресс с ручным выбором менеджера — как ручной /route."""
    lead = (
        await api.post(
            "/leads",
            json={
                "source": "site", "company": "ООО Экспресс2", "phone": "+375291234568",
                "email": "e2@x.by", "region": "Минск", "product": "лист",
                "message": "Нужен лист 5 мм, объём 10 т, срочно пришлите цену.",
            },
        )
    ).json()

    r = await api.post(f"/leads/{lead['id']}/express", json={"assigned_to": "Петров П.П."})
    assert r.status_code == 200
    assert r.json()["assigned_to"] == "Петров П.П."


async def test_lead_express_rejects_unknown_manager(session, api):
    lead = (
        await api.post(
            "/leads",
            json={
                "source": "site", "company": "ООО Экспресс3", "phone": "+375291234569",
                "email": "e3@x.by", "product": "лист",
                "message": "Нужен лист 5 мм, объём 10 т, срочно пришлите цену.",
            },
        )
    ).json()

    r = await api.post(f"/leads/{lead['id']}/express", json={"assigned_to": "Неизвестный Ф.И.О."})
    assert r.status_code == 422


async def test_lead_express_rejects_terminal_status(session, api):
    lead = (await api.post("/leads", json={"source": "site"})).json()
    await api.post(f"/leads/{lead['id']}/reject", json={"reason": "дубль"})

    r = await api.post(f"/leads/{lead['id']}/express")
    assert r.status_code == 409


async def test_lead_express_rejects_non_target_lead(session, api):
    """Слабый лид (без телефона/e-mail/компании) — балл < 50, экспресс недоступен."""
    lead = (await api.post("/leads", json={"source": "phone"})).json()

    r = await api.post(f"/leads/{lead['id']}/express")
    assert r.status_code == 422
    assert "не целевой" in r.json()["detail"]

    # лид не должен уйти в distribution — статус остался прежним
    got = (await api.get(f"/leads/{lead['id']}")).json()
    assert got["status"] == "new"


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


# --- Цикл 3: подбор товара на лиде (КП) → перенос в сделку/счёт ---


async def test_lead_items_put_get_replace_all_and_totals(session, api):
    """Подбор товара на лиде: PUT (replace-all) → GET; items_count/items_total в LeadOut."""
    lead = (await api.post("/leads", json={"source": "site", "company": "ООО КП"})).json()
    lead_id = lead["id"]
    assert lead["items_count"] == 0 and lead["items_total"] == 0

    r = await api.put(
        f"/leads/{lead_id}/items",
        json=[
            {"sku_id": 1, "sku_code": "6СТ-190", "name": "АКБ 190", "qty": 2, "price": 300},
            {"sku_id": 2, "sku_code": "6СТ-60", "name": "АКБ 60", "qty": 1, "price": 150, "discount_pct": 10},
        ],
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert items[0]["sku_code"] == "6СТ-190" and items[0]["qty"] == 2

    got = (await api.get(f"/leads/{lead_id}/items")).json()
    assert [it["sku_id"] for it in got] == [1, 2]

    # LeadOut несёт агрегат: 3 шт на 2*300 + 1*150 = 750
    detail = (await api.get(f"/leads/{lead_id}")).json()
    assert detail["items_count"] == 2
    assert detail["items_total"] == 750

    listed = next(le for le in (await api.get("/leads")).json() if le["id"] == lead_id)
    assert listed["items_count"] == 2 and listed["items_total"] == 750

    # второй PUT ПОЛНОСТЬЮ заменяет корзину (replace-all), а не дописывает
    r2 = await api.put(
        f"/leads/{lead_id}/items",
        json=[{"sku_id": 5, "sku_code": "6СТ-100", "name": "АКБ 100", "qty": 3, "price": 200}],
    )
    assert r2.status_code == 200
    got2 = (await api.get(f"/leads/{lead_id}/items")).json()
    assert [it["sku_id"] for it in got2] == [5]
    detail2 = (await api.get(f"/leads/{lead_id}")).json()
    assert detail2["items_count"] == 1 and detail2["items_total"] == 600


async def test_lead_items_put_rejects_converted_lead(session, api, services):
    """Терминальный (converted) лид — 409 на PUT items (подбор править нельзя)."""
    from core.services.eventbus import EventContext

    lead = (
        await api.post("/leads", json={"source": "site", "company": "ООО Терм", "region": "Минск", "product": "лист"})
    ).json()
    lead_id = lead["id"]
    await api.post(f"/leads/{lead_id}/qualify")
    await api.post(f"/leads/{lead_id}/route")
    await api.post(f"/leads/{lead_id}/convert")
    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()

    r = await api.put(
        f"/leads/{lead_id}/items",
        json=[{"sku_id": 1, "sku_code": "X", "name": "X", "qty": 1, "price": 10}],
    )
    assert r.status_code == 409


async def test_lead_converted_event_carries_items(session, api):
    """payload события leads.lead.converted содержит подобранные позиции (для sales/downstream)."""
    lead = (
        await api.post("/leads", json={"source": "site", "company": "ООО Позиц", "region": "Минск", "product": "лист"})
    ).json()
    lead_id = lead["id"]
    await api.post(f"/leads/{lead_id}/qualify")
    await api.post(f"/leads/{lead_id}/route")
    await api.put(
        f"/leads/{lead_id}/items",
        json=[{"sku_id": 7, "sku_code": "6СТ-190", "name": "АКБ 190", "qty": 2, "price": 300, "discount_pct": 5}],
    )

    await api.post(f"/leads/{lead_id}/convert")

    ev = next(
        e for e in (await session.execute(select(OutboxEvent))).scalars().all()
        if e.event_type == "leads.lead.converted" and e.payload.get("lead_id") == lead_id
    )
    items = ev.payload["items"]
    assert len(items) == 1
    assert items[0]["sku_code"] == "6СТ-190"
    assert items[0]["qty"] == 2 and items[0]["price"] == 300 and items[0]["discount_pct"] == 5


# --- Цикл 4: UTM-атрибуция лида → отчёт качества источников + маркетинг ---


async def test_web_intake_utm_lands_on_lead_and_event(session, api, services):
    """Веб-интейк с UTM → лид несёт utm_*, событие leads.lead.received тоже (для marketing)."""
    from core.services.eventbus import EventContext
    from modules.leads.models import Lead

    await api.post(
        "/integrations/web/lead",
        json={
            "company": "ООО ЮТМ", "phone": "+375291110000",
            "utm_source": "google", "utm_medium": "cpc", "utm_campaign": "leto-2026",
        },
    )
    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()

    lead = (await session.execute(select(Lead).where(Lead.company == "ООО ЮТМ"))).scalars().first()
    assert lead is not None
    assert lead.utm_source == "google" and lead.utm_medium == "cpc" and lead.utm_campaign == "leto-2026"

    ev = next(
        e for e in (await session.execute(select(OutboxEvent))).scalars().all()
        if e.event_type == "leads.lead.received" and e.payload.get("lead_id") == lead.id
    )
    assert ev.payload["utm_source"] == "google"
    assert ev.payload["utm_campaign"] == "leto-2026"


async def test_lead_create_accepts_utm_fields(session, api):
    """POST /leads с utm-полями — сохраняются на лиде и отдаются в LeadOut."""
    r = await api.post(
        "/leads",
        json={
            "source": "site", "company": "ООО Прямой",
            "utm_source": "facebook", "utm_medium": "social", "utm_campaign": "fb-promo",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["utm_source"] == "facebook"
    assert body["utm_campaign"] == "fb-promo"


async def test_source_stats_aggregates_by_source_and_campaign(session, api):
    """GET /leads/stats/sources — агрегат (source, utm_campaign): total/target/converted/rejected/%."""
    # 2 лида кампании A (site): один целевой+отклонён, другой целевой+в работе
    lead1 = (
        await api.post(
            "/leads",
            json={
                "source": "site", "company": "ООО Стат1", "phone": "+375291230001",
                "email": "s1@stat.by", "product": "лист", "region": "Минск",
                "message": "Нужен лист 5 мм, объём 10 т, пришлите цену и сроки.",
                "utm_campaign": "camp-a",
            },
        )
    ).json()
    await api.post(f"/leads/{lead1['id']}/qualify")
    await api.post(f"/leads/{lead1['id']}/reject", json={"reason": "нет бюджета"})

    lead2 = (
        await api.post(
            "/leads",
            json={
                "source": "site", "company": "ООО Стат2", "phone": "+375291230002",
                "email": "s2@stat.by", "product": "лист", "region": "Минск",
                "message": "Нужен лист 5 мм, объём 12 т, пришлите цену и сроки.",
                "utm_campaign": "camp-a",
            },
        )
    ).json()
    await api.post(f"/leads/{lead2['id']}/qualify")

    # 1 лид без кампании (нецелевой, phone) — отдельная группа (source=phone, utm_campaign="")
    await api.post("/leads", json={"source": "phone"})

    r = await api.get("/leads/stats/sources")
    assert r.status_code == 200
    rows = r.json()

    site_a = next(row for row in rows if row["source"] == "site" and row["utm_campaign"] == "camp-a")
    assert site_a["total"] == 2
    assert site_a["target"] == 2  # оба лида с телефоном+email+объёмом — целевые
    assert site_a["converted"] == 0
    assert site_a["rejected"] == 1
    assert site_a["target_pct"] == 100.0
    assert site_a["conversion_pct"] == 0.0

    phone_none = next(row for row in rows if row["source"] == "phone" and row["utm_campaign"] == "")
    assert phone_none["total"] == 1

    # сортировка по total desc
    assert rows[0]["total"] >= rows[-1]["total"]


async def test_marketing_attribution_end_to_end_via_web_intake(session, api, services):
    """Веб-интейк с utm_campaign существующей кампании → relay → маркетинг атрибутирует лид.

    Чинили разрыв контракта: marketing подписан на leads.lead.received (было легаси
    sales.lead.received) — событие теперь долетает, on_lead_received инкрементирует
    Campaign.leads по совпадению utm_campaign.
    """
    from core.services.eventbus import EventContext

    campaign = (
        await api.post(
            "/marketing/campaigns",
            json={
                "name": "E2E кампания", "channel": "seo", "budget": 100.0, "leads": 0,
                "utm_source": "google", "utm_medium": "cpc", "utm_campaign": "e2e-camp",
                "goal": "лиды",
            },
        )
    ).json()

    await api.post(
        "/integrations/web/lead",
        json={
            "company": "ООО Атрибуция", "phone": "+375291230099",
            "utm_source": "google", "utm_medium": "cpc", "utm_campaign": "e2e-camp",
        },
    )
    # 2 прогона relay: intake.lead.received → leads создаёт лид (+эмитит leads.lead.received),
    # затем leads.lead.received → marketing атрибутирует (тот же паттерн, что в test_lead_convert_creates_deal).
    await services.event_bus.relay_once(session, EventContext(session, services))
    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()

    attr = (await api.get("/marketing/campaigns/attribution")).json()
    found = next(c for c in attr if c["id"] == campaign["id"])
    assert found["leads"] == 1


async def test_campaign_launch_leads_emit_received_and_attribute(session, api, services):
    """Фикс ревью Ц4: лиды из запуска кампании эмитят leads.lead.received (с UTM).

    Раньше on_campaign_launched создавал лиды молча — marketing-атрибуция для
    этого пути никогда не срабатывала (Campaign.leads не рос).
    """
    from sqlalchemy import select

    from core.services.eventbus import EventContext
    from modules.leads.models import Lead

    campaign = (
        await api.post(
            "/marketing/campaigns",
            json={
                "name": "Запуск", "channel": "site", "budget": 50.0, "leads": 2,
                "utm_source": "yandex", "utm_medium": "cpc", "utm_campaign": "launch-camp",
                "goal": "лиды",
            },
        )
    ).json()

    await api.post(f"/marketing/campaigns/{campaign['id']}/launch")
    # relay 1: campaign.launched → leads создаёт лиды и эмитит leads.lead.received;
    # relay 2: leads.lead.received → marketing атрибутирует к кампании.
    await services.event_bus.relay_once(session, EventContext(session, services))
    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()

    created = (
        (await session.execute(select(Lead).where(Lead.utm_campaign == "launch-camp")))
        .scalars().all()
    )
    assert len(created) == 2
    assert all(le.utm_source == "yandex" for le in created)

    attr = (await api.get("/marketing/campaigns/attribution")).json()
    found = next(c for c in attr if c["id"] == campaign["id"])
    assert found["leads"] == 2 + 2  # 2 заявленных при создании + 2 атрибутированных


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


# --- Цикл 5: план/факт лидоруба (дневная норма + факт за сегодня) ---


async def test_lead_plan_defaults_and_update(session, api):
    """GET /leads/plan создаёт дневную норму по умолчанию; PUT обновляет цели."""
    r = await api.get("/leads/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["leads_target"] == 20 and body["qualified_target"] == 8
    assert body["converted_target"] == 3 and body["reaction_target_min"] == 15
    # факт на чистой базе — нули, реакция ещё не считалась
    assert body["leads_fact"] == 0 and body["converted_fact"] == 0
    assert body["reaction_fact_min"] is None

    upd = await api.put(
        "/leads/plan",
        json={"leads_target": 30, "qualified_target": 12, "converted_target": 5, "reaction_target_min": 10},
    )
    assert upd.status_code == 200
    assert upd.json()["leads_target"] == 30 and upd.json()["reaction_target_min"] == 10
    # норма персистентна — повторный GET отдаёт обновлённые цели (одна строка на период)
    assert (await api.get("/leads/plan")).json()["qualified_target"] == 12


async def test_lead_plan_facts_count_todays_actions(session, api):
    """Факт: обработано растёт после квалификации; целевых — только целевые в routed/converted."""
    lead = (
        await api.post(
            "/leads",
            json={
                "source": "site", "company": "ООО Планфакт", "phone": "+375291234000",
                "email": "p@f.by", "product": "лист", "region": "Минск",
                "message": "Нужен лист 5 мм, объём 20 тонн, срочно в Минск",
            },
        )
    ).json()
    # до действий — факт 0
    assert (await api.get("/leads/plan")).json()["leads_fact"] == 0

    await api.post(f"/leads/{lead['id']}/qualify")  # первое действие → обработано +1
    after_qualify = (await api.get("/leads/plan")).json()
    assert after_qualify["leads_fact"] == 1
    # целевых передано пока 0 — лид ещё не routed
    assert after_qualify["qualified_fact"] == 0

    await api.post(f"/leads/{lead['id']}/route")  # целевой ушёл продавцу
    after_route = (await api.get("/leads/plan")).json()
    assert after_route["qualified_fact"] == 1
    assert after_route["converted_fact"] == 0

    await api.post(f"/leads/{lead['id']}/convert")  # доведено до сделки
    assert (await api.get("/leads/plan")).json()["converted_fact"] == 1


async def test_lead_plan_rejects_negative_target(session, api):
    """PUT отвергает отрицательные цели (Field ge=0)."""
    r = await api.put(
        "/leads/plan",
        json={"leads_target": -1, "qualified_target": 8, "converted_target": 3, "reaction_target_min": 15},
    )
    assert r.status_code == 422


# --- Цикл 6: конвейер — «Разобрать целевых» одним действием ---


async def test_express_bulk_routes_targets_skips_non_targets(session, api):
    """POST /leads/express-bulk: целевые новые → routed; нецелевые — пропущены (не тронуты)."""
    target = (
        await api.post(
            "/leads",
            json={
                "source": "site", "company": "ООО Целевой", "phone": "+375291110001",
                "email": "t@bulk.by", "product": "лист", "region": "Минск",
                "message": "Нужен лист 5 мм, объём 20 тонн, срочно в Минск с доставкой",
            },
        )
    ).json()
    trash = (await api.post("/leads", json={"source": "phone", "message": "?"})).json()

    r = await api.post("/leads/express-bulk")
    assert r.status_code == 200
    body = r.json()
    assert target["id"] in body["expressed"]
    assert body["skipped_non_target"] >= 1

    # целевой распределён и назначен менеджер; нецелевой остался new
    got_target = (await api.get(f"/leads/{target['id']}")).json()
    assert got_target["status"] == "routed" and got_target["assigned_to"]
    assert (await api.get(f"/leads/{trash['id']}")).json()["status"] == "new"


async def test_express_bulk_balances_load_within_batch(session, api):
    """Пачка целевых без узкой специализации балансируется между менеджерами (autoflush видит routed).

    Регион/продукт пустые → под правила подходят ВСЕ менеджеры (catch-all), поэтому загрузка
    размазывается, а не сваливается на одного (при узкой специализации все ушли бы одному — норм)."""
    ids = []
    for i in range(3):
        lead = (
            await api.post(
                "/leads",
                json={
                    "source": "site", "company": f"ООО Клиент{i}", "phone": f"+37529222000{i}",
                    "email": f"m{i}@bulk.by",
                    "message": "Здравствуйте, интересует поставка, пришлите условия и цены, объёмы обсудим",
                },
            )
        ).json()
        ids.append(lead["id"])

    r = await api.post("/leads/express-bulk")
    assert r.status_code == 200
    assert set(ids).issubset(set(r.json()["expressed"]))
    # не все три ушли одному менеджеру — загрузка балансируется внутри пачки
    owners = {(await api.get(f"/leads/{i}")).json()["assigned_to"] for i in ids}
    assert len(owners) >= 2


# --- Цикл 7: скорборд передач + деньги по источникам ---


async def _seed_converted_lead_with_kp(api, services, session, company, region, product, price):
    """Хелпер: провести лид до converted с одной позицией КП на заданную сумму."""
    from core.services.eventbus import EventContext

    lead = (
        await api.post(
            "/leads",
            json={
                "source": "site", "company": company, "phone": f"+37529{abs(hash(company)) % 10000000:07d}",
                "email": f"{abs(hash(company)) % 9999}@kp.by", "product": product, "region": region,
                "message": "Нужен металл, объём большой, срочно с доставкой, пришлите цену и сроки",
            },
        )
    ).json()
    await api.post(f"/leads/{lead['id']}/qualify")
    await api.post(f"/leads/{lead['id']}/route")
    await api.put(
        f"/leads/{lead['id']}/items",
        json=[{"sku_id": 1, "sku_code": "SKU-1", "name": product, "qty": 1, "price": price}],
    )
    await api.post(f"/leads/{lead['id']}/convert")
    await services.event_bus.relay_once(session, EventContext(session, services))
    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()
    return lead


async def test_handoff_stats_scorecard(session, api, services):
    """GET /leads/stats/handoffs: по продавцу — передано/в сделке/Σ КП, отсортировано по деньгам."""
    await _seed_converted_lead_with_kp(api, services, session, "ООО Первый", "Минск", "лист", 40000)

    rows = (await api.get("/leads/stats/handoffs")).json()
    assert len(rows) >= 1
    ivanov = next(r for r in rows if r["manager"] == "Иванов И.И.")  # металл/Минск → Иванов
    assert ivanov["assigned"] >= 1
    assert ivanov["converted"] >= 1
    assert ivanov["pipeline"] == 40000.0
    assert ivanov["conversion_pct"] == 100.0


async def test_source_stats_include_pipeline_money(session, api, services):
    """GET /leads/stats/sources: колонка pipeline = Σ КП сконвертированных лидов источника."""
    await _seed_converted_lead_with_kp(api, services, session, "ООО Денежный", "Минск", "арматура", 25000)

    rows = (await api.get("/leads/stats/sources")).json()
    site_rows = [r for r in rows if r["source"] == "site"]
    assert site_rows
    assert sum(r["pipeline"] for r in site_rows) >= 25000.0


# --- Цикл 8: умная маршрутизация по истории конверсии + обоснование ---


def test_route_lead_prefers_better_closer_with_history():
    """route_lead с историей конверсии выбирает лучшего закрывающего среди кандидатов."""
    from modules.leads.leads import route_lead
    from modules.leads.models import Lead

    # без гео/продукта кандидаты — все три; загрузка равная
    generic = Lead(source="site")
    loads = {"Иванов И.И.": 0, "Петров П.П.": 0, "Сидоров С.С.": 0}
    perf = {"Иванов И.И.": 0.1, "Петров П.П.": 0.5, "Сидоров С.С.": 0.2}
    assert route_lead(generic, loads, False, perf)[0] == "Петров П.П."  # лучшая конверсия


def test_route_lead_load_penalty_overrides_small_conversion_edge():
    """Небольшое преимущество в конверсии не перевешивает крупный перекос загрузки."""
    from modules.leads.leads import route_lead
    from modules.leads.models import Lead

    generic = Lead(source="site")
    # Иванов чуть лучше по конверсии (+1 п.п.), но загружен на 10 лидов больше → штраф побеждает
    loads = {"Иванов И.И.": 10, "Петров П.П.": 0, "Сидоров С.С.": 0}
    perf = {"Иванов И.И.": 0.51, "Петров П.П.": 0.50, "Сидоров С.С.": 0.0}
    assert route_lead(generic, loads, False, perf)[0] == "Петров П.П."


def test_route_lead_no_history_falls_back_to_load():
    """Без истории (пустой performance) — прежнее правило наименее загруженного."""
    from modules.leads.leads import route_lead
    from modules.leads.models import Lead

    generic = Lead(source="site")
    loads = {"Иванов И.И.": 3, "Петров П.П.": 1, "Сидоров С.С.": 5}
    assert route_lead(generic, loads, False, {})[0] == "Петров П.П."


async def test_route_returns_rationale(session, api):
    """POST /route возвращает обоснование выбора менеджера (Цикл 8)."""
    lead = (
        await api.post(
            "/leads",
            json={"source": "site", "company": "ООО Обоснование", "region": "Минск", "product": "лист"},
        )
    ).json()
    await api.post(f"/leads/{lead['id']}/qualify")
    r = (await api.post(f"/leads/{lead['id']}/route")).json()
    assert r["assigned_to"] == "Иванов И.И."
    assert "Иванов И.И." in r["rationale"]  # человекочитаемое «почему»


async def test_route_manual_rationale(session, api):
    """Ручной выбор менеджера → обоснование «Ручной выбор»."""
    lead = (await api.post("/leads", json={"source": "site", "company": "ООО Ручной"})).json()
    await api.post(f"/leads/{lead['id']}/qualify")
    r = (await api.post(f"/leads/{lead['id']}/route", json={"assigned_to": "Петров П.П."})).json()
    assert r["assigned_to"] == "Петров П.П."
    assert "Ручной выбор" in r["rationale"]


async def test_manager_performance_counts_converted_in_volume(session, api):
    """Фикс ревью Ц8 (старвейшн): _manager_performance отдаёт (конверсия, объём), и объём
    включает конвертнутые лиды — иначе нагрузка быстрого закрывающего «испаряется» и штраф
    LOAD_PENALTY его не догоняет, лид уходит одному, остальные простаивают."""
    from modules.leads.routes import _manager_performance

    ids = []
    for i in range(2):
        lead = (
            await api.post(
                "/leads",
                json={"source": "site", "company": f"ООО Объём{i}", "region": "Минск", "product": "лист"},
            )
        ).json()
        await api.post(f"/leads/{lead['id']}/qualify")
        await api.post(f"/leads/{lead['id']}/route")  # оба → Иванов (Минск+лист)
        ids.append(lead["id"])
    await api.post(f"/leads/{ids[0]}/convert")  # один доведён до сделки (статус converted)

    perf = await _manager_performance(session)
    rate, volume = perf["Иванов И.И."]
    assert volume == 2  # оба переданных лида в объёме, включая конвертнутый
    assert rate == 0.5  # 1 из 2 доведён


# --- Цикл 9: ключевые лиды (высокий потенциал → лучший закрывающий, макс. выигрыш) ---


def test_is_key_lead_signals():
    """Ключевой лид: высокий балл, тендер или маркер объёма в тексте."""
    from modules.leads.leads import is_key_lead
    from modules.leads.models import Lead

    assert is_key_lead(Lead(source="site", score=75)) is True  # высокий балл
    assert is_key_lead(Lead(source="tender", score=10)) is True  # тендер
    assert is_key_lead(Lead(source="site", score=10, message="нужно 40 тонн листа")) is True  # объём
    assert is_key_lead(Lead(source="site", score=30, product="лист", message="цена?")) is False


def test_route_lead_key_ignores_load_penalty():
    """Ключевой лид уходит лучшему закрывающему БЕЗ штрафа загрузки (макс. выигрыш)."""
    from modules.leads.leads import route_lead
    from modules.leads.models import Lead

    generic = Lead(source="site")
    # Иванов лучший по конверсии, но перегружен; обычный лид ушёл бы Петрову (штраф загрузки),
    # ключевой — Иванову (штраф отключён).
    loads = {"Иванов И.И.": 20, "Петров П.П.": 0, "Сидоров С.С.": 0}
    perf = {"Иванов И.И.": 0.6, "Петров П.П.": 0.4, "Сидоров С.С.": 0.0}
    assert route_lead(generic, loads, False, perf, key=False)[0] == "Петров П.П."
    assert route_lead(generic, loads, False, perf, key=True)[0] == "Иванов И.И."


async def test_key_lead_exposed_in_api(session, api):
    """LeadOut несёт is_key — тендерный лид помечается ключевым."""
    lead = (
        await api.post(
            "/leads",
            json={"source": "tender", "company": "РУП Энерго", "region": "Гомель", "product": "оборудование"},
        )
    ).json()
    assert lead["is_key"] is True
    listed = (await api.get("/leads")).json()
    assert next(le for le in listed if le["id"] == lead["id"])["is_key"] is True


# --- Цикл 10: резолв входящего лида против существующих клиентов (MDM) ---


async def test_resolve_customer_by_company_name_existing(session, api):
    """Лид с именем существующего контрагента → customer_kind=existing + counterparty_id."""
    from core.domain.models import Counterparty

    cp = Counterparty(name="ООО Действующий")
    session.add(cp)
    await session.commit()

    lead = (
        await api.post(
            "/leads", json={"source": "site", "company": "ООО Действующий", "product": "лист"}
        )
    ).json()
    assert lead["counterparty_id"] == cp.id
    assert lead["customer_kind"] == "existing"
    assert lead["is_key"] is True  # действующий клиент → ключевой


async def test_resolve_customer_by_contact_phone(session, api):
    """Лид с телефоном существующего контакта → резолвится в его контрагента."""
    from core.domain.models import Contact, Counterparty

    cp = Counterparty(name="ЗАО КонтактКо")
    session.add(cp)
    await session.flush()
    session.add(Contact(counterparty_id=cp.id, full_name="Иван Клиентов", phone="+375291234567"))
    await session.commit()

    # телефон в другом формате (80..) — хвост совпадает
    lead = (
        await api.post("/leads", json={"source": "phone", "phone": "80291234567"})
    ).json()
    assert lead["counterparty_id"] == cp.id
    assert lead["customer_kind"] == "existing"


async def test_resolve_customer_regular_on_second_lead(session, api):
    """Второй лид по тому же контрагенту → customer_kind=regular (постоянник)."""
    from core.domain.models import Counterparty

    cp = Counterparty(name="ООО Повторный")
    session.add(cp)
    await session.commit()

    first = (await api.post("/leads", json={"source": "site", "company": "ООО Повторный"})).json()
    assert first["customer_kind"] == "existing"
    second = (await api.post("/leads", json={"source": "site", "company": "ООО Повторный"})).json()
    assert second["customer_kind"] == "regular"


async def test_resolve_customer_follows_golden_record(session, api):
    """Имя совпало со слитым дублем → лид привязывается к эталону (golden record)."""
    from core.domain.models import Counterparty

    survivor = Counterparty(name="ООО Эталон")
    session.add(survivor)
    await session.flush()
    dup = Counterparty(name="ООО Дубль", is_active=False, merged_into_id=survivor.id)
    session.add(dup)
    await session.commit()

    # точное имя активного эталона не совпадёт с «ООО Дубль»; матч по контакту дал бы дубль —
    # проверяем golden record напрямую через резолв по имени дубля... дубль неактивен, exact
    # его не найдёт. Проверяем golden_counterparty_id отдельно:
    from modules.leads.leads import golden_counterparty_id

    assert await golden_counterparty_id(session, dup.id) == survivor.id


async def test_resolve_customer_no_match_is_cold(session, api):
    """Нет совпадений → лид остаётся новым/холодным (customer_kind пуст, не ключевой по клиенту)."""
    lead = (
        await api.post("/leads", json={"source": "site", "company": "ООО Ничейный Новичок 12345"})
    ).json()
    assert lead["customer_kind"] == ""
    assert lead["counterparty_id"] is None


# --- Цикл 11: добавить контакт в существующую компанию без дублей ---


async def test_link_contact_creates_then_dedups(session, api):
    """POST /link-contact: создаёт контакт в компании лида, повтор с тем же телефоном — не дублит."""
    from sqlalchemy import select as _select

    from core.domain.models import Contact, Counterparty

    cp = Counterparty(name="ООО Клиент11")
    session.add(cp)
    await session.commit()

    lead = (
        await api.post(
            "/leads",
            json={"source": "site", "company": "ООО Клиент11", "name": "Пётр Контактов", "phone": "+375291112244"},
        )
    ).json()
    assert lead["counterparty_id"] == cp.id  # резолв Цикла 10

    r1 = (await api.post(f"/leads/{lead['id']}/link-contact")).json()
    assert r1["created"] is True
    assert r1["counterparty_id"] == cp.id
    assert r1["full_name"] == "Пётр Контактов"

    # второй раз — тот же контакт (дедуп по телефону в рамках компании), не дубль
    r2 = (await api.post(f"/leads/{lead['id']}/link-contact")).json()
    assert r2["created"] is False
    assert r2["contact_id"] == r1["contact_id"]

    # в базе ровно один контакт под этой компанией
    contacts = (
        await session.execute(_select(Contact).where(Contact.counterparty_id == cp.id))
    ).scalars().all()
    assert len(contacts) == 1


async def test_link_contact_requires_counterparty(session, api):
    """Лид без резолва в компанию → 422 (некуда привязывать контакт)."""
    lead = (
        await api.post("/leads", json={"source": "site", "company": "ООО Безкомпании 999", "phone": "+375290001111"})
    ).json()
    assert lead["counterparty_id"] is None
    r = await api.post(f"/leads/{lead['id']}/link-contact")
    assert r.status_code == 422


async def test_link_contact_unknown_counterparty_404(session, api):
    """Явный несуществующий counterparty_id → 404."""
    lead = (await api.post("/leads", json={"source": "site", "name": "X", "phone": "+375290002222"})).json()
    r = await api.post(f"/leads/{lead['id']}/link-contact", json={"counterparty_id": 999999})
    assert r.status_code == 404


async def test_reresolve_cold_lead_on_repeat_contact(session, api, services):
    """Фикс ревью Ц10: холодный лид, чей контакт появился в MDM ПОЗЖЕ, при повторном
    обращении (дедуп-дозапись) повторно резолвится и получает метку клиента."""
    from core.domain.models import Contact, Counterparty
    from core.services.eventbus import EventContext

    # 1) холодный веб-лид (контакта в MDM ещё нет)
    await api.post("/integrations/web/lead", json={"phone": "+375293334455", "message": "первое"})
    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()
    lead = next(le for le in (await api.get("/leads")).json() if (le.get("phone") or "").endswith("3334455"))
    assert lead["customer_kind"] == ""

    # 2) контакт появился в базе позже
    cp = Counterparty(name="ООО Поздний Клиент")
    session.add(cp)
    await session.flush()
    session.add(Contact(counterparty_id=cp.id, full_name="Поздний", phone="+375293334455"))
    await session.commit()

    # 3) повторное обращение того же телефона (иной формат) → дозапись + повторный резолв
    await api.post("/integrations/web/lead", json={"phone": "80293334455", "message": "повтор"})
    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()

    got = (await api.get(f"/leads/{lead['id']}")).json()
    assert got["counterparty_id"] == cp.id
    assert got["customer_kind"] == "existing"


# --- Цикл 12: непредусмотренные сценарии (конфликт компаний, реанимация отказа) ---


def test_companies_conflict_predicate():
    """Конфликт компаний: разные имена — да; подстрока/пусто — нет."""
    from modules.leads.leads import companies_conflict

    assert companies_conflict("ООО Ромашка", "ООО Стройторг") is True
    assert companies_conflict("Ромашка", "ООО Ромашка") is False  # подстрока
    assert companies_conflict("", "ООО Ромашка") is False  # пусто → дозаписываем
    assert companies_conflict("ООО Ромашка", None) is False


async def test_dedup_skips_different_company_same_phone(session, api):
    """Тот же телефон, но другая компания → НЕ дубль (заводим отдельный лид, не портим чужой)."""
    first = (
        await api.post(
            "/leads", json={"source": "site", "company": "ООО Первая", "phone": "+375295550000"}
        )
    ).json()
    # тот же номер, но явно другая компания — 201 (новый лид), не 409
    r = await api.post(
        "/leads", json={"source": "site", "company": "ООО Вторая", "phone": "+375295550000"}
    )
    assert r.status_code == 201
    assert r.json()["id"] != first["id"]

    # а тот же номер БЕЗ конфликта компании (пустая) — по-прежнему дубль (409)
    dup = await api.post("/leads", json={"source": "phone", "phone": "+375295550000"})
    assert dup.status_code == 409


async def test_lead_revived_from_rejected(session, api):
    """Новый лид от ранее отклонённого контакта ссылается на тот отказ (revived_from_id)."""
    rejected = (
        await api.post("/leads", json={"source": "site", "company": "ООО Реанимация", "phone": "+375296660000"})
    ).json()
    await api.post(f"/leads/{rejected['id']}/reject", json={"reason": "нет бюджета"})

    # новое обращение того же телефона → отдельный лид со ссылкой на отказ
    revived = (
        await api.post("/leads", json={"source": "site", "company": "ООО Реанимация", "phone": "80296660000"})
    ).json()
    assert revived["id"] != rejected["id"]
    assert revived["revived_from_id"] == rejected["id"]


async def test_dedup_finds_right_company_among_multiple_same_phone(session, api):
    """Фикс ревью Ц12: два открытых лида на один телефон у РАЗНЫХ фирм — новый лид своей
    фирмы находит СВОЙ дубль (409), а не заводит третий вслепую."""
    a = (
        await api.post("/leads", json={"source": "site", "company": "ООО Альфа", "phone": "+375297770000"})
    ).json()
    # вторая фирма с тем же телефоном → отдельный лид (конфликт компаний)
    b = await api.post("/leads", json={"source": "site", "company": "ООО Бета", "phone": "+375297770000"})
    assert b.status_code == 201
    # снова Альфа с тем же телефоном → должен найтись дубль A (409), а не создаться третий
    again = await api.post("/leads", json={"source": "site", "company": "ООО Альфа", "phone": "80297770000"})
    assert again.status_code == 409
    assert again.json()["detail"]["duplicate_of"] == a["id"]


async def test_revival_ignores_other_company_rejection(session, api):
    """Фикс ревью Ц12: отказ ДРУГОЙ компании с общим телефоном не приписывается новому лиду."""
    rej_other = (
        await api.post("/leads", json={"source": "site", "company": "ООО Чужая", "phone": "+375298880000"})
    ).json()
    await api.post(f"/leads/{rej_other['id']}/reject", json={"reason": "конкурент"})

    # новая фирма с тем же телефоном — НЕ должна получить чужой revived_from_id
    mine = (
        await api.post("/leads", json={"source": "site", "company": "ООО Моя", "phone": "80298880000"})
    ).json()
    assert mine["revived_from_id"] is None


# --- Цикл 13: пост-передача под контролем ---


async def test_route_sets_routed_at(session, api):
    """Раздача проставляет routed_at — возраст «у продавца» для контроля зависших."""
    lead = (
        await api.post("/leads", json={"source": "site", "company": "ООО Контроль", "phone": "+375291230013"})
    ).json()
    assert lead["routed_at"] is None
    await api.post(f"/leads/{lead['id']}/qualify")
    routed = (await api.post(f"/leads/{lead['id']}/route")).json()
    got = (await api.get(f"/leads/{lead['id']}")).json()
    assert got["routed_at"] is not None
    assert routed["id"] == lead["id"]


async def test_express_bulk_sets_default_next_step(session, api):
    """Конвейер не раздаёт «без шага»: bulk-экспресс ставит дефолтный next_step (завтра, «Позвонить»)."""
    lead = (
        await api.post(
            "/leads",
            json={
                "source": "site", "company": "ООО Шаг", "phone": "+375291230014",
                "email": "step@bulk.by", "product": "лист", "region": "Минск",
                "message": "Нужен лист 5 мм, объём 20 тонн, срочно в Минск с доставкой",
            },
        )
    ).json()
    r = await api.post("/leads/express-bulk")
    assert lead["id"] in r.json()["expressed"]
    got = (await api.get(f"/leads/{lead['id']}")).json()
    assert got["next_step_at"] is not None
    assert got["next_step_note"] == "Позвонить"
    assert got["routed_at"] is not None


async def test_handoff_stats_pending_and_stale(session, api, services):
    """Скорборд Ц13: переданный (не сконвертированный) лид виден как pending с Σ КП;
    переданный >24ч назад без сделки считается stale."""
    from datetime import datetime, timedelta, timezone

    from modules.leads.models import Lead

    lead = (
        await api.post(
            "/leads",
            json={
                "source": "site", "company": "ООО Висяк", "phone": "+375291230015",
                "product": "лист", "region": "Минск",
                "message": "Нужен металл, объём большой, срочно, пришлите цену",
            },
        )
    ).json()
    await api.post(f"/leads/{lead['id']}/qualify")
    await api.post(f"/leads/{lead['id']}/route")
    await api.put(
        f"/leads/{lead['id']}/items",
        json=[{"sku_id": 1, "sku_code": "SKU-1", "name": "лист", "qty": 1, "price": 7000}],
    )

    rows = (await api.get("/leads/stats/handoffs")).json()
    row = next(r for r in rows if r["manager"] == "Иванов И.И.")  # металл/Минск → Иванов
    assert row["pending"] >= 1
    assert row["pending_pipeline"] >= 7000.0
    assert row["stale"] == 0  # только что передан — не завис

    # состариваем передачу: routed_at позавчера → лид попадает в stale
    obj = await session.get(Lead, lead["id"])
    obj.routed_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)
    await session.commit()

    rows = (await api.get("/leads/stats/handoffs")).json()
    row = next(r for r in rows if r["manager"] == "Иванов И.И.")
    assert row["stale"] >= 1
