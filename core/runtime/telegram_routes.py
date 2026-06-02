"""Telegram как primary interface (часть 11, doc-11).

Каркас: HTTP-webhook принимает Telegram-update и диспетчеризует команды —
согласования (human-in-the-loop, ч.4) подтверждаются прямо в боте, плюс команды,
объявленные модулями (``core.telegram_commands``). Реальный aiogram-бот (polling
или регистрация webhook в Telegram) встаёт поверх этого контракта позже, без его
изменения.
"""
from __future__ import annotations

import inspect

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Approval
from core.runtime.core import Core
from core.runtime.deps import get_core, get_session

router = APIRouter(tags=["telegram"])


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
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Приём Telegram-update и ответ в формате Bot API (sendMessage)."""
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    reply = await handle_command(core, session, text)
    return {"method": "sendMessage", "chat_id": chat_id, "text": reply}
