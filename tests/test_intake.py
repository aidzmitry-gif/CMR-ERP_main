"""Приём лидов с сайта и почты (публичные коннекторы integrations) → лиды в воронку CRM."""

from sqlalchemy import select

from config.settings import get_settings
from core.services.eventbus import EventContext
from modules.leads.models import Lead


async def test_web_and_email_intake_create_leads(session, api, services):
    """Сайт (контакт-форма) и почта (вебхук) → событие → relay → лид со статусом new."""
    from sqlalchemy import select

    from core.services.eventbus import EventContext
    from modules.leads.models import Lead

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


async def test_microchips_and_email_intake_token_dedup_and_persistence(
    session, api, services, monkeypatch
):
    """Токен обязателен, повтор сайта склеивается, письмо остаётся email-лидом."""
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(settings, "intake_webhook_token", "crm-git-001-test-token")

    rejected = await api.post(
        "/integrations/web/lead?token=wrong",
        json={"company": "ООО Микрочипс", "phone": "+375291112233"},
    )
    assert rejected.status_code == 403

    payload = {
        "company": "ООО Микрочипс",
        "phone": "+375291112233",
        "email": "buyer@microchips.by",
        "product": "Аккумулятор",
        "message": "Первая заявка",
        "landing_url": "https://microchips.by/catalog?utm_source=google&utm_campaign=battery",
    }
    first = await api.post(
        "/integrations/web/lead?token=crm-git-001-test-token", json=payload
    )
    repeated = await api.post(
        "/integrations/web/lead?token=crm-git-001-test-token",
        json={**payload, "message": "Повторная заявка"},
    )
    email = await api.post(
        "/integrations/email/inbound?token=crm-git-001-test-token",
        json={
            "from": "Закупщик <mail-lead@client.by>",
            "subject": "Запрос с почты",
            "text": "Нужна цена",
        },
    )
    assert first.status_code == repeated.status_code == email.status_code == 200

    await services.event_bus.relay_once(session, EventContext(session, services))
    await session.commit()
    leads = (await session.execute(select(Lead).order_by(Lead.id))).scalars().all()

    assert len(leads) == 2
    site = next(lead for lead in leads if lead.source == "site")
    inbound_email = next(lead for lead in leads if lead.source == "email")
    assert site.company == "ООО Микрочипс"
    assert "Первая заявка" in site.message and "Повторная заявка" in site.message
    assert site.utm_source == "google" and site.utm_campaign == "battery"
    assert inbound_email.email == "mail-lead@client.by"
    assert inbound_email.product == "Запрос с почты"


async def test_intake_without_configured_token_is_closed_in_production(
    api, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "intake_webhook_token", "")

    response = await api.post(
        "/integrations/web/lead", json={"phone": "+375291234567"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Токен приёма не настроен"
