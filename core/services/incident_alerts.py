"""Безопасное уведомление о технических инцидентах.

Сервис намеренно не привязан к Slack/Telegram/Teams: любой endpoint, который
принимает JSON webhook, подходит. При пустом URL приложение продолжает работать
в режиме только логирования, поэтому отсутствие канала оповещений не ломает
запуск CRM.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from urllib.request import Request, urlopen

logger = logging.getLogger("aios.incident_alerts")

AlertSender = Callable[[str, dict[str, object], str], Awaitable[None]]
_SECRET_RE = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key|authorization)(\s*[:=]\s*)[^\s,;&]+"
)


def _safe_error_message(error: BaseException) -> str:
    """Сжать и обезличить текст ошибки перед записью/отправкой наружу."""
    message = f"{type(error).__name__}: {error}".strip()
    message = _SECRET_RE.sub(r"\1\2[REDACTED_SECRET]", message)
    return message[:1000]


def _send_webhook_sync(url: str, payload: dict[str, object], token: str) -> None:
    """Отправить JSON без дополнительной runtime-зависимости на HTTP-клиент."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "aios-incident-alert/1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=10) as response:  # noqa: S310 - URL задаётся владельцем системы
        status = getattr(response, "status", None)
        if status is None:
            status = response.getcode()
        if status >= 400:
            raise RuntimeError(f"incident webhook returned HTTP {status}")


async def _send_webhook(url: str, payload: dict[str, object], token: str) -> None:
    await asyncio.to_thread(_send_webhook_sync, url, payload, token)


class IncidentAlertSink:
    """Webhook-уведомитель с дедупликацией повторяющихся сбоев."""

    def __init__(
        self,
        webhook_url: str = "",
        webhook_token: str = "",
        cooldown_seconds: int = 300,
        *,
        sender: AlertSender | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.webhook_url = webhook_url.strip()
        self.webhook_token = webhook_token
        self.cooldown_seconds = max(0, cooldown_seconds)
        self._sender = sender or _send_webhook
        self._clock = clock or time.monotonic
        self._last_sent: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    async def emit(
        self,
        source: str,
        error: BaseException,
        *,
        details: Mapping[str, object] | None = None,
        force: bool = False,
    ) -> bool:
        """Отправить один инцидент; вернуть ``True`` только после успешной доставки."""
        message = _safe_error_message(error)
        if not self.enabled:
            logger.error("incident source=%s alerting=disabled error=%s", source, message)
            return False

        now = self._clock()
        previous = self._last_sent.get(source)
        if not force and previous is not None and now - previous < self.cooldown_seconds:
            logger.warning("incident source=%s alert=suppressed cooldown=%ss", source, self.cooldown_seconds)
            return False

        payload: dict[str, object] = {
            "event": "incident",
            "source": source,
            "severity": "critical",
            "message": message,
            "details": dict(details or {}),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self._sender(self.webhook_url, payload, self.webhook_token)
        except Exception:
            logger.exception("incident source=%s alert=failed", source)
            return False

        self._last_sent[source] = now
        logger.error("incident source=%s alert=sent", source)
        return True
