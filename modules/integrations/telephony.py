"""Коннектор облачной АТС zruchna — приём webhook-событий звонка + click-to-call.

Провайдер шлёт на наш endpoint HTTP GET/POST (query-params, form или JSON) на
каждый этап звонка (`type`: in/dial/answer/hangup/misscall/transfer). Коннектор —
**без состояния**: нормализует номер в E.164, маппит `type` в доменное событие
ядра (`telephony.call.incoming/answered/ended/transfer`) и пишет его в outbox.
Склейку событий одного звонка по `uniqueid`, журнал и резолв продавца ведёт
подписчик (`sales`), не зная про zruchna (правило границ, §2.4).

Исходящий звонок (`ZruchnaClient.originate`) — POST на `client_call_gen.php`
с `vnut` (внутренний номер сотрудника) и `number` (клиент).
"""
from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger("aios.integrations.telephony")

# zruchna `type` → доменное событие ядра. `dial`/`in` — старт звонка (входящий или
# исходящий набор): подписчик апсертит запись по `call_id`, поэтому повторный
# `incoming` (in → dial) лишь дополняет её внутренним номером сотрудника.
EVENT_BY_TYPE = {
    "in": "telephony.call.incoming",
    "dial": "telephony.call.incoming",
    "answer": "telephony.call.answered",
    "hangup": "telephony.call.ended",
    "misscall": "telephony.call.ended",
    "transfer": "telephony.call.transfer",
}

# Статус вызова провайдера → нормализованный (учтены опечатки спецификации BUSSY/NO ANSWERED).
STATUS_MAP = {
    "ANSWERED": "answered",
    "NO ANSWER": "no_answer",
    "NO ANSWERED": "no_answer",
    "BUSY": "busy",
    "BUSSY": "busy",
    "FAILED": "failed",
}


def _s(value: object) -> str:
    """Привести параметр (str из form/query или произвольный из JSON) к строке."""
    return "" if value is None else str(value).strip()


def normalize_e164(phone: object, default_cc: str = "375") -> str | None:
    """Нормализовать телефон в E.164 (по умолчанию РБ, +375).

    # ponytail: BY-центричная эвристика (8 0XX → +375, 9 цифр → +375…); для
    # мультистраны подключить libphonenumber.
    """
    s = _s(phone)
    if not s:
        return None
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if plus or digits.startswith("375"):
        return "+" + digits
    if digits.startswith("00") and len(digits) > 2:  # международный префикс 00 → +
        return "+" + digits[2:]
    if digits.startswith("80") and len(digits) >= 11:  # РБ-домашний набор 8 0XX …
        return "+375" + digits[2:]
    if digits.startswith("8") and len(digits) == 11:  # 8 + 10 цифр → межгород (+7)
        return "+7" + digits[1:]
    if len(digits) == 9:  # местный мобильный без кода страны
        return "+" + default_cc + digits
    return "+" + digits


def _to_seconds(value: object) -> int | None:
    """Длительность в секундах: целое или `HH:MM:SS`/`MM:SS`; иначе None."""
    s = _s(value)
    if not s:
        return None
    if ":" in s:
        segments = s.split(":")
        if len(segments) > 3:  # длиннее H:M:S — мусор провайдера, не угадываем
            return None
        try:
            parts = [int(p) for p in segments]
        except ValueError:
            return None
        if any(p < 0 for p in parts):
            return None
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + part
        return seconds
    try:
        result = int(float(s))  # OverflowError тоже: float("inf") иначе уронил бы вебхук в 500
    except (ValueError, OverflowError):
        return None
    return result if result >= 0 else None


def parse_event(params: dict) -> dict | None:
    """Разобрать webhook zruchna → ``{event_type, payload}`` или None (игнор).

    Возвращает None для неизвестного `type` или пустого `uniqueid` (без него нельзя
    связать события одного звонка).
    """
    raw_type = _s(params.get("type")).lower()
    event_type = EVENT_BY_TYPE.get(raw_type)
    if event_type is None:
        return None
    call_id = _s(params.get("uniqueid"))
    if not call_id:
        return None
    direction = "out" if _s(params.get("direct")).lower() == "out" else "in"
    payload = {
        "event": raw_type,
        "call_id": call_id,
        "direction": direction,
        "phone_e164": normalize_e164(params.get("phone")),
        "did": _s(params.get("did")) or None,  # внешняя линия, на которую звонил клиент
        "agent_ext": _s(params.get("code")) or None,  # внутренний номер сотрудника
        "to_ext": _s(params.get("totransfer")) or None,  # перевод: на кого
        "status": STATUS_MAP.get(_s(params.get("status")).upper()),
        "hold_sec": _to_seconds(params.get("hold")),
        "duration_sec": _to_seconds(params.get("duration")),
        "recording_url": _s(params.get("path")) or None,
        "at": _s(params.get("date")) or None,
        # для проекции в аудит (relay читает actor/entity_ref из payload)
        "actor": "telephony",
        "entity_ref": f"call:{call_id}",
    }
    return {"event_type": event_type, "payload": payload}


def ingest(session, event_bus, params: dict) -> dict:
    """Разобрать webhook и эмитнуть доменное событие в outbox (без commit — владеет роут)."""
    parsed = parse_event(params)
    if parsed is None:
        logger.info("telephony: событие проигнорировано (type=%r)", params.get("type"))
        return {"ok": True, "ignored": True}
    event_bus.emit(session, parsed["event_type"], parsed["payload"])
    return {"ok": True, "event": parsed["event_type"], "call_id": parsed["payload"]["call_id"]}


def originate_params(vnut: object, number: object) -> dict:
    """Параметры запроса инициации звонка: ``vnut`` (≤3 цифр) + ``number`` (клиент)."""
    vnut_digits = re.sub(r"\D", "", _s(vnut))[:3]
    return {"vnut": vnut_digits, "number": normalize_e164(number) or _s(number)}


class ZruchnaClient:
    """Реализация ``TelephonyGateway`` поверх облачной АТС zruchna."""

    def __init__(self, originate_url: str = "") -> None:
        self.originate_url = originate_url

    @property
    def configured(self) -> bool:
        return bool(self.originate_url)

    async def originate(self, vnut: str, number: str) -> dict:
        """Инициировать исходящий звонок: поднять трубку у ``vnut`` и набрать ``number``."""
        if not self.configured:
            raise RuntimeError("Телефония: AIOS_TELEPHONY_ORIGINATE_URL не задан")
        params = originate_params(vnut, number)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self.originate_url, params=params)
            resp.raise_for_status()
        return {"ok": True, "status": resp.status_code, **params}
