"""Telegram как primary interface (часть 11, doc-11).

Каркас: HTTP-webhook принимает Telegram-update и диспетчеризует команды —
согласования (human-in-the-loop, ч.4) подтверждаются прямо в боте, плюс команды,
объявленные модулями (``core.telegram_commands``). Реальный aiogram-бот (polling
или регистрация webhook в Telegram) встаёт поверх этого контракта позже, без его
изменения.
"""
from __future__ import annotations

import hmac
import inspect
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Approval
from core.runtime.core import Core
from core.runtime.deps import get_core, get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


def _check_telegram_secret(core: Core, request: Request) -> None:
    """Проверить Telegram secret-token (SECURITY.md P0-6).

    Telegram передаёт значение из ``setWebhook`` в заголовке
    ``X-Telegram-Bot-Api-Secret-Token``. Если секрет задан — несовпадение даёт 401
    (constant-time, в байтах — не падать на non-ASCII). Секрет не задан → **fail-closed
    в проде** (DoD P0: аноним → 401), т.к. ``/telegram`` в OPEN_PREFIXES и публичный прод
    иначе принимал бы поддельные ``/approve``; в dev — открыт для локальной отладки.
    """
    expected = core.config.telegram_webhook_secret
    if not expected:
        if not core.config.environment.lower().startswith("dev"):
            raise HTTPException(status_code=401, detail="Telegram secret-token не настроен")
        logger.warning("telegram: webhook без AIOS_TELEGRAM_WEBHOOK_SECRET — приём открыт (dev)")
        return
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(got.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Неверный Telegram secret-token")


async def handle_command(core, session: AsyncSession, text: str) -> str:
    """Разобрать текст команды и вернуть ответ бота."""
    parts = text.split()
    cmd = parts[0].lstrip("/").lower() if parts else ""
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("", "start", "help"):
        lines = [
            "Бизнес-ОС — Telegram-интерфейс. Команды:",
            "/approvals — согласования, ожидающие решения",
            "/approve <id> — согласовать",
            "/reject <id> — отклонить",
        ]
        lines += [f"/{c.command} — {c.description}" for c in core.telegram_commands]
        return "\n".join(lines)

    if cmd == "approvals":
        rows = (
            await session.execute(
                select(Approval).where(Approval.status == "pending").order_by(Approval.id)
            )
        ).scalars().all()
        if not rows:
            return "Нет согласований, ожидающих решения."
        return "Ожидают согласования:\n" + "\n".join(
            f"#{a.id} · {a.kind} · {a.route} · {a.subject}" for a in rows
        )

    if cmd in ("approve", "reject"):
        if not arg.isdigit():
            return f"Укажите номер: /{cmd} <id>"
        approval = await session.get(Approval, int(arg))
        if approval is None:
            return "Согласование не найдено."
        if approval.status != "pending":
            return f"Согласование #{approval.id} уже обработано ({approval.status})."
        await core.services.approvals.decide(session, approval, cmd == "approve", "Telegram")
        await session.commit()
        return f"Согласование #{approval.id}: {approval.status}."

    # команды, объявленные модулями (caркас бота, ч.11)
    for c in core.telegram_commands:
        if c.command == cmd:
            result = c.handler()
            if inspect.isawaitable(result):
                result = await result
            return str(result)

    return f"Команда /{cmd} не распознана. /help — список команд."


@router.post("/telegram/webhook")
async def telegram_webhook(
    update: dict,
    request: Request,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Приём Telegram-update и ответ в формате Bot API (sendMessage).

    Аутентификация (SECURITY.md P0-6): secret-token из ``setWebhook`` — иначе кто угодно
    подделает ``/approve <id>`` (согласования гейтят действия с деньгами).
    """
    _check_telegram_secret(core, request)
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    reply = await handle_command(core, session, text)
    return {"method": "sendMessage", "chat_id": chat_id, "text": reply}
