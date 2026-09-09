"""Durable loopback relay for staged sales messages."""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .config import Config
from .queue import Message, Queue

MAX_RESPONSE_BYTES = 64 * 1024


class RelayError(RuntimeError):
    """A safe relay error without response bodies or secrets."""


class TransientRelayError(RelayError):
    """Network, 429, or 5xx failure; the row remains pending."""


class RemoteEndpointError(RelayError):
    """The loopback endpoint attempted to redirect or otherwise broaden scope."""


class ResponseTooLarge(RelayError):
    """The API response exceeded the bounded diagnostic body limit."""


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    body: bytes


def receipt_id(mailbox: str, uidvalidity: int, uid: int) -> str:
    if not mailbox or uidvalidity <= 0 or uid <= 0:
        raise RelayError("invalid_receipt_identity")
    value = f"{mailbox}\0{uidvalidity}\0{uid}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _post(config: Config, payload: bytes) -> HTTPResponse:
    request = urllib.request.Request(
        config.endpoint,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Sales-Mail-Token": config.inbound_token,
        },
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=config.http_timeout) as response:
            return HTTPResponse(response.status, _bounded_read(response))
    except urllib.error.HTTPError as exc:
        try:
            body = _bounded_read(exc)
        except ResponseTooLarge:
            exc.close()
            raise
        except OSError:
            body = b""
        return HTTPResponse(exc.code, body)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TransientRelayError("relay_network_error") from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, msg, headers, new_url):
        raise RemoteEndpointError("remote_redirect_rejected")


def _bounded_read(response) -> bytes:
    headers = getattr(response, "headers", None)
    content_length = headers.get("Content-Length") if headers is not None else None
    if content_length is not None:
        try:
            if int(content_length) > MAX_RESPONSE_BYTES:
                raise ResponseTooLarge("relay_response_too_large")
        except ValueError:
            pass
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if not isinstance(body, bytes) or len(body) > MAX_RESPONSE_BYTES:
        raise ResponseTooLarge("relay_response_too_large")
    return body


def _payload(message: Message) -> tuple[str, str, bytes]:
    digest = hashlib.sha256(message.raw).hexdigest()
    if digest != message.raw_sha256:
        raise RelayError("local_raw_hash_mismatch")
    rid = receipt_id(message.mailbox, message.uidvalidity, message.uid)
    payload = json.dumps(
        {
            "mailbox": message.mailbox,
            "uidvalidity": message.uidvalidity,
            "uid": message.uid,
            "raw_sha256": digest,
            "raw_base64": base64.b64encode(message.raw).decode("ascii"),
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return rid, digest, payload


def _response_values(response: HTTPResponse) -> tuple[str | None, str | None]:
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(value, dict):
        return None, None
    return value.get("receipt_id"), value.get("raw_sha256")


def relay_once(
    queue: Queue,
    config: Config,
    *,
    post: Callable[[Config, bytes], HTTPResponse] = _post,
) -> dict[str, int]:
    queue.require_relay_ready(config.mailbox)
    counts = {"delivered": 0, "pending": 0, "review": 0, "halted": 0}
    for message in queue.pending():
        try:
            expected_id, expected_hash, payload = _payload(message)
        except RelayError as exc:
            queue.mark_review(message, "local_validation_failed", str(exc))
            counts["review"] += 1
            continue

        response: HTTPResponse | None = None
        transient = False
        terminal_review = False
        for _ in range(config.relay_attempts):
            try:
                response = post(config, payload)
            except ResponseTooLarge as exc:
                queue.mark_review(message, "relay_response_too_large", str(exc))
                counts["review"] += 1
                terminal_review = True
                break
            except RemoteEndpointError as exc:
                queue.halt_relay(str(exc))
                counts["halted"] += 1
                break
            except TransientRelayError as exc:
                queue.mark_attempt(message, type(exc).__name__)
                transient = True
                continue
            if response.status == 429 or response.status >= 500:
                queue.mark_attempt(message, f"http_{response.status}")
                transient = True
                continue
            break
        if queue.relay_halted:
            break
        if terminal_review:
            continue
        if transient and (response is None or response.status == 429 or response.status >= 500):
            counts["pending"] += 1
            continue
        if response is None:
            counts["pending"] += 1
            continue
        if response.status in (401, 403):
            queue.halt_relay(f"relay_http_{response.status}_config_error")
            counts["halted"] += 1
            break
        if response.status == 409:
            queue.mark_review(message, "receipt_conflict", "http_409")
            counts["review"] += 1
            continue
        if 300 <= response.status < 400:
            queue.mark_review(message, "relay_redirect_rejected", f"http_{response.status}")
            counts["review"] += 1
            continue
        if 400 <= response.status < 500:
            queue.mark_review(message, "relay_http_4xx", f"http_{response.status}")
            counts["review"] += 1
            continue
        if not 200 <= response.status < 300:
            queue.mark_attempt(message, f"http_{response.status}")
            counts["pending"] += 1
            continue
        received_id, received_hash = _response_values(response)
        if received_id != expected_id or received_hash != expected_hash:
            queue.mark_review(message, "receipt_mismatch", "response_identity_mismatch")
            counts["review"] += 1
            continue
        queue.mark_delivered(message, expected_id)
        counts["delivered"] += 1
    return counts
