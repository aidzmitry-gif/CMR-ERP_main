"""Приём лидов с сайта и почты (публичные коннекторы integrations) → лиды в воронку CRM."""


async def test_web_and_email_intake_create_leads(session, api, services):
    """Сайт (контакт-форма) и почта (вебхук) → событие → relay → лид со статусом new."""
    from sqlalchemy import select

    from core.services.eventbus import EventContext
    from modules.sales.models import Lead

    # 1) заявка с сайта
    r = await api.post(
        "/integrations/web/lead",
        json={
            "name": "Пётр Сидоров",
            "company": "ООО Ромашка",
            "phone": "+375291234567",
            "email": "p@romashka.by",
            "region": "Минск",
            "product": "арматура 12",
            "message": "Нужна цена и сроки",
        },
    )
    assert r.status_code == 200
    assert r.json()["source"] == "site"

    # 2) входящее письмо (вебхук почтового форвардера)
    r2 = await api.post(
        "/integrations/email/inbound",
        json={"from": "Иван Клиентов <ivan@client.by>", "subject": "Запрос КП", "text": "Пришлите прайс"},
    )
    assert r2.status_code == 200
    assert r2.json()["source"] == "email"

    # события доставлены фоновым relay (шина приложения с подписками) → on_intake_lead создаёт лиды
    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()

    leads = (await session.execute(select(Lead))).scalars().all()
    site_lead = next((x for x in leads if x.source == "site" and x.company == "ООО Ромашка"), None)
    email_lead = next((x for x in leads if x.source == "email" and x.email == "ivan@client.by"), None)
    assert site_lead is not None
    assert site_lead.status == "new" and site_lead.product == "арматура 12"
    assert email_lead is not None
    assert email_lead.name == "Иван Клиентов"
