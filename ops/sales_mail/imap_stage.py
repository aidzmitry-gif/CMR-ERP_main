"""Read-only IMAP collection for the dedicated sales mailbox."""

from __future__ import annotations

import hashlib
import imaplib
import re
import ssl
from typing import Callable, Protocol

from .config import MAX_BATCH, MAX_BYTES, Config
from .queue import Queue, QueueError


class ImapError(RuntimeError):
    """A safe, non-content IMAP operation error."""


class UIDValidityChanged(ImapError):
    """The mailbox identity changed and collection was durably halted."""


class ImapClient(Protocol):
    def select(self, mailbox: str, readonly: bool = False): ...

    def response(self, name: str): ...

    def uid(self, command: str, *args): ...


def _positive(value: object, *, label: str) -> int:
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="strict")
    try:
        number = int(str(value))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ImapError(f"invalid_{label}") from exc
    if number <= 0:
        raise ImapError(f"invalid_{label}")
    return number


def mailbox_state(client: ImapClient) -> tuple[int, int]:
    status, _ = client.select("INBOX", readonly=True)
    if status != "OK":
        raise ImapError("inbox_unavailable")
    values: dict[str, int] = {}
    for name in ("UIDVALIDITY", "UIDNEXT"):
        _, data = client.response(name)
        if not data or data[0] is None:
            raise ImapError(f"missing_{name}")
        values[name] = _positive(data[0], label=name.lower())
    return values["UIDVALIDITY"], values["UIDNEXT"]


def real_client(config: Config) -> imaplib.IMAP4_SSL:
    context = ssl.create_default_context()
    try:
        client = imaplib.IMAP4_SSL(
            config.imap_host,
            config.imap_port,
            ssl_context=context,
            timeout=config.imap_timeout,
        )
        client.login(config.username, config.password)
    except Exception as exc:
        raise ImapError("imap_connect_or_login_failed") from exc
    return client


def _open_client(
    config: Config, client_factory: Callable[[Config], ImapClient]
) -> ImapClient:
    try:
        return client_factory(config)
    except ImapError:
        raise
    except Exception as exc:
        raise ImapError("imap_connect_failed") from exc


def _close_client(client: ImapClient) -> None:
    close = getattr(client, "close", None)
    logout = getattr(client, "logout", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
    if callable(logout):
        try:
            logout()
        except Exception:
            pass


def _size_from_fetch(data: object) -> int | None:
    chunks: list[bytes] = []
    if isinstance(data, (bytes, bytearray)):
        chunks.append(bytes(data))
    elif isinstance(data, (list, tuple)):
        for item in data:
            if isinstance(item, (bytes, bytearray)):
                chunks.append(bytes(item))
            elif isinstance(item, (list, tuple)):
                chunks.extend(bytes(x) for x in item if isinstance(x, (bytes, bytearray)))
    match = re.search(rb"RFC822\.SIZE\s+(\d+)", b" ".join(chunks), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _raw_from_fetch(data: object) -> bytes | None:
    if not isinstance(data, (list, tuple)):
        return None
    for item in data:
        if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
            return item[1]
    return None


def _search_uids(data: object, last_uid: int, upper: int) -> list[int]:
    if not isinstance(data, (list, tuple)) or not data or data[0] is None:
        raise ImapError("search_malformed_response")
    value = data[0]
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii", errors="strict")
        except UnicodeError as exc:
            raise ImapError("search_malformed_response") from exc
    if not isinstance(value, str):
        raise ImapError("search_malformed_response")
    if not value.strip():
        return []
    result: set[int] = set()
    for item in value.split():
        if not item.isdigit():
            raise ImapError("search_invalid_uid_token")
        uid = int(item)
        if uid <= 0:
            raise ImapError("search_invalid_uid_token")
        if last_uid < uid <= upper:
            result.add(uid)
    return sorted(result)[:MAX_BATCH]


def initialize(queue: Queue, config: Config, client_factory: Callable[[Config], ImapClient] = real_client):
    queue.ensure_namespace(config.mailbox)
    if queue.initialized:
        raise QueueError("already_initialized_do_not_reset")
    client = _open_client(config, client_factory)
    try:
        uidvalidity, uidnext = mailbox_state(client)
    finally:
        _close_client(client)
    return queue.initialize(config.mailbox, uidvalidity, uidnext)


def poll_once(queue: Queue, config: Config, client_factory: Callable[[Config], ImapClient] = real_client):
    queue.require_collection_ready(config.mailbox)
    client = _open_client(config, client_factory)
    counts = {"fetched": 0, "pending": 0, "review": 0, "oversize": 0}
    try:
        observed_validity, uidnext = mailbox_state(client)
        expected_validity = queue.uidvalidity
        if observed_validity != expected_validity:
            queue.halt_uidvalidity(expected_validity or 0, observed_validity)
            raise UIDValidityChanged("uidvalidity_changed_review_required")
        upper = uidnext - 1
        if upper <= queue.last_uid:
            return counts
        status, data = client.uid("search", None, "UID", f"{queue.last_uid + 1}:{upper}")
        if status != "OK":
            raise ImapError("search_failed")
        uids = _search_uids(data, queue.last_uid, upper)
        if not uids:
            queue.advance_empty_search(upper)
            return counts
        for uid in uids:
            status, sizes = client.uid("fetch", str(uid), "(RFC822.SIZE)")
            size = _size_from_fetch(sizes)
            if status != "OK" or size is None:
                raise ImapError("size_fetch_failed_watermark_preserved")
            if size > MAX_BYTES:
                queue.stage_oversize(uid, size)
                counts["fetched"] += 1
                counts["oversize"] += 1
                counts["review"] += 1
                continue
            status, parts = client.uid("fetch", str(uid), "(BODY.PEEK[])")
            raw = _raw_from_fetch(parts)
            if status != "OK" or raw is None:
                raise ImapError("body_fetch_failed_watermark_preserved")
            if len(raw) > MAX_BYTES:
                queue.stage_oversize(uid, len(raw), raw_sha256=hashlib.sha256(raw).hexdigest())
                counts["fetched"] += 1
                counts["oversize"] += 1
                counts["review"] += 1
                continue
            review_reason = None
            try:
                from email import policy
                from email.parser import BytesParser

                if BytesParser(policy=policy.default).parsebytes(raw).defects:
                    review_reason = "message_parse_defects"
            except (TypeError, ValueError, UnicodeError):
                review_reason = "message_parse_failed"
            queue.stage_raw(uid, raw, review_reason=review_reason)
            counts["fetched"] += 1
            if review_reason:
                counts["review"] += 1
            else:
                counts["pending"] += 1
        return counts
    finally:
        _close_client(client)
