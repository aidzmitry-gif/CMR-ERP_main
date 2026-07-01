"""HTTP-API модуля Integrations. Монтируется под префиксом ``/integrations``."""
from __future__ import annotations

import hmac
import logging
import re
from urllib.parse import parse_qsl, parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.core import Core
from core.runtime.deps import get_core, get_session
from core.services import sync_outbound
from core.services.auth import require_permission
from modules.integrations import telephony
from modules.integrations.models import StockItem
from modules.integrations.schemas import OriginateIn, RegistryOut, StockOut
from modules.integrations.service import sync_1c

logger = logging.getLogger("aios.integrations.telephony")

router = APIRouter(tags=["integrations"])


async def _collect_params(request: Request) -> dict:
    """Слить параметры webhook из query + (POST) form/JSON в один dict.

    zruchna может слать и GET с query, и POST с form-полями, и JSON — принимаем всё.
    Form (``application/x-www-form-urlencoded``) парсим stdlib-ом ``parse_qsl``, а не
    ``request.form()``, чтобы не тянуть зависимость ``python-multipart`` (её нет в
    requirements; иначе form-POST провайдера падал бы 500 и звонок терялся).
    """
    data: dict = dict(request.query_params)
    if request.method == "POST":
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001 — кривой JSON просто не добавляем
                body = None
            if isinstance(body, dict):
                data.update(body)
        else:
            raw = (await request.body()).decode("utf-8", "replace")
            data.update(dict(parse_qsl(raw, keep_blank_values=True)))
    return data


@router.api_route("/telephony/zruchna", methods=["GET", "POST"])
async def telephony_webhook(
    request: Request,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Приём событий звонка от облачной АТС zruchna → доменное событие в шину.

    Аутентификация — общий секрет ``?token=`` (если задан в настройках). Прод
    публичен, поэтому при незаданном токене предупреждаем в лог (SECURITY: задать
    ``AIOS_TELEPHONY_WEBHOOK_TOKEN``). Дальше склейку/журнал ведёт sales-подписчик.
    """
    params = await _collect_params(request)
    expected = core.config.telephony_webhook_token
    if expected:
        # constant-time сравнение секрета (в байтах — не падать TypeError на non-ASCII токене)
        if not hmac.compare_digest(str(params.get("token", "")).encode(), expected.encode()):
            raise HTTPException(status_code=403, detail="Неверный токен телефонии")
    else:
        logger.warning("telephony: webhook без AIOS_TELEPHONY_WEBHOOK_TOKEN — приём открыт")
    result = telephony.ingest(session, core.event_bus, params)
    await session.commit()
    return result


# ──────────────── Приём лидов с сайта и почты (публично, токен) ────────────────


def _check_intake_token(core: Core, params: dict) -> None:
    """Проверить общий секрет приёма (?token=), если он задан в настройках."""
    expected = core.config.intake_webhook_token
    if expected:
        if not hmac.compare_digest(str(params.get("token", "")).encode(), expected.encode()):
            raise HTTPException(status_code=403, detail="Неверный токен приёма")
    else:
        logger.warning("intake: приём без AIOS_INTAKE_WEBHOOK_TOKEN — открыт")


def _extract_utm(params: dict) -> dict[str, str]:
    """UTM из явных полей формы или из landing_url / referrer."""
    out = {
        "utm_source": str(params.get("utm_source") or params.get("utmSource") or "").strip(),
        "utm_medium": str(params.get("utm_medium") or params.get("utmMedium") or "").strip(),
        "utm_campaign": str(params.get("utm_campaign") or params.get("utmCampaign") or "").strip(),
        "landing_url": str(params.get("landing_url") or params.get("landingUrl") or params.get("page_url") or "").strip(),
    }
    if out["utm_source"] and out["utm_campaign"]:
        return out
    for key in ("landing_url", "page_url", "referrer", "url"):
        raw = str(params.get(key) or "").strip()
        if not raw:
            continue
        qs = parse_qs(urlparse(raw).query)
        out["landing_url"] = out["landing_url"] or raw
        out["utm_source"] = out["utm_source"] or (qs.get("utm_source", [""])[0] or "")
        out["utm_medium"] = out["utm_medium"] or (qs.get("utm_medium", [""])[0] or "")
        out["utm_campaign"] = out["utm_campaign"] or (qs.get("utm_campaign", [""])[0] or "")
        if out["utm_source"]:
            break
    return out


def _parse_sender(s: str) -> tuple[str, str]:
    """«Имя <addr@dom>» → (имя, адрес); просто адрес → ('', адрес)."""
    m = re.match(r"^\s*(.*?)\s*<([^>]+)>\s*$", s)
    if m:
        return m.group(1).strip().strip('"'), m.group(2).strip()
    return ("", s.strip())


@router.api_route("/web/lead", methods=["POST"])
async def web_lead_intake(
    request: Request,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Заявка с сайта (контакт-форма) → лид в приём CRM. Публично, токен ?token= (если задан).

    Принимает JSON или form-поля (name/company/phone/email/region/product/message). Сам лид
    создаёт sales-подписчик события ``intake.lead.received`` (границы §2.4).
    """
    params = await _collect_params(request)
    _check_intake_token(core, params)
    utm = _extract_utm(params)
    core.event_bus.emit(
        session,
        "intake.lead.received",
        {
            "source": "site",
            "name": str(params.get("name", "") or "").strip(),
            "company": str(params.get("company", "") or "").strip(),
            "phone": str(params.get("phone", "") or "").strip(),
            "email": str(params.get("email", "") or "").strip(),
            "region": str(params.get("region", "") or "").strip(),
            "product": str(params.get("product", "") or "").strip(),
            "message": str(params.get("message", "") or "").strip(),
            **utm,
        },
    )
    await session.commit()
    return {"ok": True, "source": "site"}


@router.api_route("/email/inbound", methods=["POST"])
async def email_lead_intake(
    request: Request,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Входящее письмо (от почтового форвардера/вебхука) → лид. Публично, токен ?token=.

    Поля: ``from`` («Имя <addr>»), ``subject``, ``text``/``body``. Тема + текст → сообщение лида.
    """
    params = await _collect_params(request)
    _check_intake_token(core, params)
    name, email = _parse_sender(str(params.get("from", "") or "").strip())
    subject = str(params.get("subject", "") or "").strip()
    body = str(params.get("text") or params.get("body") or "").strip()
    core.event_bus.emit(
        session,
        "intake.lead.received",
        {
            "source": "email",
            "name": name,
            "email": email,
            "product": subject,
            "message": (f"{subject}\n{body}").strip() or subject,
        },
    )
    await session.commit()
    return {"ok": True, "source": "email"}


@router.post("/telephony/originate")
async def telephony_originate(
    body: OriginateIn,
    core: Core = Depends(get_core),
    _: object = Depends(require_permission("integrations.telephony")),
) -> dict:
    """Инициировать исходящий звонок (click-to-call): ``vnut`` звонит ``number``."""
    gateway = core.services.telephony
    if gateway is None or not getattr(gateway, "configured", False):
        raise HTTPException(status_code=503, detail="Телефония не подключена")
    try:
        return await gateway.originate(body.vnut, body.number)
    except Exception as exc:  # noqa: BLE001 — ошибку АТС отдаём вызывающему как 502
        raise HTTPException(status_code=502, detail=f"АТС недоступна: {exc}") from exc


@router.post("/1c/sync")
async def sync(core: Core = Depends(get_core), session: AsyncSession = Depends(get_session)) -> dict:
    """Прочитать данные из 1С и синхронизировать в бизнес-память."""
    summary = await sync_1c(session, core.event_bus, core.services.onec)
    await session.commit()
    return {"ok": True, **summary}


@router.post("/1c/sync-out")
async def sync_out(
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
    _: object = Depends(require_permission("integrations.sync")),
) -> dict:
    """Выгрузить очередь pending-записей ERP → 1С (исходящий синк, M3).

    Каркас на шлюзе ``core.services.onec.post_document``: успех → external_ref + synced,
    ошибка → error с текстом (виден в журнале, ручной повтор). Реальный OData-POST подключается
    в OneCClient без правки этого роута.
    """
    summary = await sync_outbound.flush_pending(session, core.services.onec)
    await session.commit()
    return {"ok": True, **summary}


@router.get("/1c/sync-journal")
async def sync_journal(
    session: AsyncSession = Depends(get_session),
    _: object = Depends(require_permission("integrations.sync")),
) -> dict:
    """Журнал выгрузки: что/куда/статус/когда/ошибка (зеркало журнала импорта)."""
    return {"entries": await sync_outbound.journal(session)}


@router.post("/1c/enqueue/{entity_type}/{entity_id}")
async def enqueue_out(
    entity_type: str,
    entity_id: int,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
    _: object = Depends(require_permission("integrations.sync")),
) -> dict:
    """Поставить запись ERP в очередь на выгрузку в 1С («Создать здесь» / ручная переотправка)."""
    if entity_type not in ("counterparty", "sku"):
        raise HTTPException(status_code=400, detail="entity_type: counterparty|sku")
    link = await sync_outbound.enqueue(
        session, entity_type=entity_type, entity_id=entity_id, origin="erp"
    )
    await session.commit()
    return {"ok": True, "state": link.state, "entity_type": entity_type, "entity_id": entity_id}


@router.get("/1c/stock", response_model=list[StockOut])
async def stock(session: AsyncSession = Depends(get_session)):
    """Остатки/цены (синхронизированные из 1С)."""
    return (await session.execute(select(StockItem).order_by(StockItem.sku_code))).scalars().all()


@router.get("/egr/{unp}", response_model=RegistryOut)
async def egr_lookup(unp: str, core: Core = Depends(get_core)):
    """Подтянуть контрагента по УНП из реестра ЕГР РБ (sales-28)."""
    if core.services.registry is None:
        raise HTTPException(status_code=503, detail="Реестр ЕГР не подключён")
    data = await core.services.registry.lookup(unp)
    if data is None:
        raise HTTPException(status_code=404, detail="Контрагент по УНП не найден")
    return data
