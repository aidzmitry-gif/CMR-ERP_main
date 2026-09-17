from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core.runtime import telegram_routes


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows


class Session:
    def __init__(self, rows=(), approvals=None):
        self.rows = rows
        self.approvals = approvals or {}
        self.commits = 0
        self.executed = 0

    async def execute(self, _statement):
        self.executed += 1
        return Result(self.rows)

    async def get(self, _model, identifier):
        return self.approvals.get(identifier)

    async def commit(self):
        self.commits += 1


def core(*, secret="", environment="dev", commands=(), decide=None):
    return SimpleNamespace(
        config=SimpleNamespace(telegram_webhook_secret=secret, environment=environment),
        telegram_commands=list(commands),
        services=SimpleNamespace(
            approvals=SimpleNamespace(decide=decide or (lambda *args: None))
        ),
    )


def request(headers=None):
    return SimpleNamespace(headers=headers or {})


def test_telegram_secret_is_open_only_in_dev_and_constant_header_is_required():
    telegram_routes._check_telegram_secret(core(environment="dev"), request())

    with pytest.raises(HTTPException) as prod:
        telegram_routes._check_telegram_secret(core(environment="prod"), request())
    assert prod.value.status_code == 401

    secured = core(secret="секрет", environment="prod")
    telegram_routes._check_telegram_secret(secured, request({"X-Telegram-Bot-Api-Secret-Token": "секрет"}))
    with pytest.raises(HTTPException) as wrong:
        telegram_routes._check_telegram_secret(secured, request({"X-Telegram-Bot-Api-Secret-Token": "нет"}))
    assert wrong.value.status_code == 401


@pytest.mark.asyncio
async def test_handle_command_lists_help_module_commands_and_unknown_command():
    async def custom_handler():
        return "готово"

    commands = [SimpleNamespace(command="status", description="статус", handler=custom_handler)]
    bot = core(commands=commands)

    help_text = await telegram_routes.handle_command(bot, Session(), "/help")
    assert "/status — статус" in help_text
    assert await telegram_routes.handle_command(bot, Session(), "/status") == "готово"
    assert "не распознана" in await telegram_routes.handle_command(bot, Session(), "/unknown")


@pytest.mark.asyncio
async def test_handle_command_approvals_reports_empty_and_rows():
    empty = await telegram_routes.handle_command(core(), Session(), "/approvals")
    assert empty == "Нет согласований, ожидающих решения."

    rows = [SimpleNamespace(id=2, kind="payment", route="finance", subject="Счёт")]
    text = await telegram_routes.handle_command(core(), Session(rows), "approvals")
    assert text == "Ожидают согласования:\n#2 · payment · finance · Счёт"


@pytest.mark.asyncio
async def test_handle_command_approve_reject_validates_id_not_found_status_and_decides():
    for command in ("approve", "reject"):
        assert await telegram_routes.handle_command(core(), Session(), f"/{command} bad") == (
            f"Укажите номер: /{command} <id>"
        )

    assert await telegram_routes.handle_command(core(), Session(), "/approve 404") == "Согласование не найдено."

    processed = SimpleNamespace(id=5, status="approved")
    assert await telegram_routes.handle_command(core(), Session(approvals={5: processed}), "/approve 5") == (
        "Согласование #5 уже обработано (approved)."
    )

    calls = []

    async def decide(*args):
        calls.append(args)
        args[1].status = "rejected"

    pending = SimpleNamespace(id=5, status="pending")
    session = Session(approvals={5: pending})
    result = await telegram_routes.handle_command(core(decide=decide), session, "/reject 5")
    assert result == "Согласование #5: rejected."
    assert session.commits == 1 and calls[0][2:] == (False, "Telegram")


@pytest.mark.asyncio
async def test_telegram_webhook_returns_bot_api_send_message_shape():
    result = await telegram_routes.telegram_webhook(
        {"message": {"chat": {"id": 99}, "text": "/help"}},
        request(),
        core(),
        Session(),
    )
    assert result["method"] == "sendMessage"
    assert result["chat_id"] == 99
    assert result["text"].startswith("Бизнес-ОС")
