"""Strict configuration for the dedicated sales mailbox worker."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

MAILBOX = "order@microchips.by"
IMAP_HOST = "imap.yandex.ru"
IMAP_PORT = 993
ENDPOINT = "http://127.0.0.1:8000/integrations/sales-mail/v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_BATCH = 50
DEFAULT_ATTEMPTS = 3


class ConfigError(ValueError):
    """Raised when configuration would broaden the worker's trust boundary."""


@dataclass(frozen=True)
class Config:
    mailbox: str
    imap_host: str
    imap_port: int
    username: str
    password: str
    endpoint: str
    inbound_token: str
    imap_timeout: float = 30.0
    http_timeout: float = 15.0
    relay_attempts: int = DEFAULT_ATTEMPTS


def _private_file(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise ConfigError(f"{label}_symlink_not_allowed")
    if not path.exists() or not path.is_file():
        raise ConfigError(f"{label}_not_a_file")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ConfigError(f"{label}_requires_private_permissions")


def _positive_number(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise ConfigError(f"invalid_{label}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid_{label}") from exc
    if result <= 0 or not math.isfinite(result):
        raise ConfigError(f"invalid_{label}")
    return result


def _validate_endpoint(value: object) -> str:
    if value != ENDPOINT:
        raise ConfigError("unexpected_endpoint")
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != 8000:
        raise ConfigError("unexpected_endpoint")
    if parsed.path != "/integrations/sales-mail/v1" or parsed.query or parsed.fragment:
        raise ConfigError("unexpected_endpoint")
    return value


def load_config(path: str | Path) -> Config:
    """Load and validate JSON config without ever printing its contents."""

    config_path = Path(path)
    _private_file(config_path, label="config_file")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError("invalid_config_file") from exc
    if not isinstance(raw, dict):
        raise ConfigError("config_must_be_object")

    mailbox = raw.get("mailbox")
    if mailbox != MAILBOX:
        raise ConfigError("unexpected_mailbox")
    if raw.get("username") != mailbox:
        raise ConfigError("username_must_match_mailbox")
    if raw.get("imap_host") != IMAP_HOST or raw.get("imap_port") != IMAP_PORT:
        raise ConfigError("unexpected_imap_server")
    password = raw.get("password")
    token = raw.get("inbound_token")
    if not isinstance(password, str) or not password:
        raise ConfigError("missing_password")
    if not isinstance(token, str) or not token:
        raise ConfigError("missing_inbound_token")

    imap_timeout = _positive_number(raw.get("imap_timeout", 30), label="imap_timeout")
    http_timeout = _positive_number(raw.get("http_timeout", 15), label="http_timeout")
    attempts = raw.get("relay_attempts", DEFAULT_ATTEMPTS)
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 10:
        raise ConfigError("invalid_relay_attempts")

    return Config(
        mailbox=mailbox,
        imap_host=raw["imap_host"],
        imap_port=raw["imap_port"],
        username=raw["username"],
        password=password,
        endpoint=_validate_endpoint(raw.get("endpoint")),
        inbound_token=token,
        imap_timeout=imap_timeout,
        http_timeout=http_timeout,
        relay_attempts=attempts,
    )
