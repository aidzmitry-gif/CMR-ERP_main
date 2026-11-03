"""Private SQLite queue and cursor state for sales-mail intake."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import MAILBOX, MAX_BATCH, MAX_BYTES


class QueueError(RuntimeError):
    """Base queue error."""


class QueueNamespaceMismatch(QueueError):
    """The durable queue belongs to another mailbox namespace."""


class AlreadyInitialized(QueueError):
    """Initialization would reset an existing cursor."""


class QueueHalted(QueueError):
    """Collection or relay is halted pending explicit review."""


@dataclass(frozen=True)
class Message:
    mailbox: str
    uidvalidity: int
    uid: int
    raw: bytes
    raw_sha256: str
    size: int
    state: str
    reason: str
    receipt_id: str | None
    attempts: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_private_file(path: Path) -> None:
    if path.is_symlink():
        raise QueueError("queue_symlink_not_allowed")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # Windows ACLs are administered outside this stdlib worker.  Passing a
        # POSIX 0600 mode to os.open there can create an ACL that the service
        # account cannot later clean up; enforce mode bits only on POSIX.
        mode = 0o600 if os.name != "nt" else 0o666
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        os.close(fd)
    if not path.is_file():
        raise QueueError("queue_not_a_file")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise QueueError("queue_requires_private_permissions")


class Queue:
    """SQLite-backed queue with monotonic UID cursor and durable halt state."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        _ensure_private_file(self.path)
        try:
            # Keep sqlite's normal deferred transaction mode.  All mutating
            # methods use ``with self.db`` so stage+cursor and init metadata
            # commit or roll back together after a process fault.
            self.db = sqlite3.connect(self.path, timeout=0)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys = ON")
            self.db.execute("PRAGMA journal_mode = DELETE")
            self.db.execute("PRAGMA synchronous = FULL")
            self._create_schema()
        except sqlite3.Error as exc:
            raise QueueError("queue_open_failed") from exc

    def __enter__(self) -> "Queue":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "db", None) is not None:
            self.db.close()

    def _create_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                mailbox TEXT NOT NULL,
                uidvalidity INTEGER NOT NULL,
                uid INTEGER NOT NULL,
                raw BLOB,
                raw_sha256 TEXT,
                size INTEGER NOT NULL,
                state TEXT NOT NULL,
                reason TEXT NOT NULL,
                receipt_id TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (mailbox, uidvalidity, uid)
            );
            CREATE INDEX IF NOT EXISTS messages_pending
                ON messages (state, uidvalidity, uid);
            """
        )

    def _get(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else None

    def _set(self, key: str, value: object) -> None:
        self.db.execute(
            "INSERT INTO metadata(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    @property
    def mailbox(self) -> str | None:
        return self._get("mailbox")

    @property
    def initialized(self) -> bool:
        return self._get("uidvalidity") is not None

    @property
    def uidvalidity(self) -> int | None:
        value = self._get("uidvalidity")
        return int(value) if value is not None else None

    @property
    def last_uid(self) -> int:
        value = self._get("last_uid")
        return int(value) if value is not None else 0

    @property
    def halted(self) -> bool:
        return self._get("halt_reason") is not None or self._get("relay_halt_reason") is not None

    @property
    def collection_halted(self) -> bool:
        return self._get("halt_reason") is not None

    @property
    def relay_halted(self) -> bool:
        return self._get("relay_halt_reason") is not None

    def ensure_namespace(self, mailbox: str) -> None:
        if mailbox != MAILBOX:
            raise QueueNamespaceMismatch("unexpected_mailbox")
        existing = self.mailbox
        if existing is not None and existing != mailbox:
            raise QueueNamespaceMismatch("queue_mailbox_mismatch")
        if existing is None:
            with self.db:
                self._set("mailbox", mailbox)

    def initialize(self, mailbox: str, uidvalidity: int, uidnext: int) -> dict[str, object]:
        self.ensure_namespace(mailbox)
        if self.initialized:
            raise AlreadyInitialized("already_initialized_do_not_reset")
        if not isinstance(uidvalidity, int) or uidvalidity <= 0:
            raise QueueError("invalid_uidvalidity")
        if not isinstance(uidnext, int) or uidnext <= 0:
            raise QueueError("invalid_uidnext")
        with self.db:
            self._set("uidvalidity", uidvalidity)
            self._set("last_uid", uidnext - 1)
        return {"initialized": True, "history_imported": False}

    def require_ready(self, mailbox: str) -> None:
        self.ensure_namespace(mailbox)
        if not self.initialized:
            raise QueueError("initialize_required_no_history_import")
        if self.collection_halted or self.relay_halted:
            raise QueueHalted("queue_halted_review_required")

    def require_collection_ready(self, mailbox: str) -> None:
        self.ensure_namespace(mailbox)
        if not self.initialized:
            raise QueueError("initialize_required_no_history_import")
        if self.collection_halted:
            raise QueueHalted("collection_halted_review_required")

    def require_relay_ready(self, mailbox: str) -> None:
        self.ensure_namespace(mailbox)
        if not self.initialized:
            raise QueueError("initialize_required_no_history_import")
        if self.collection_halted or self.relay_halted:
            raise QueueHalted("relay_halted_review_required")

    def halt_uidvalidity(self, observed: int, new_value: int) -> None:
        with self.db:
            self._set("halt_reason", "uidvalidity_changed_review_required")
            self._set("halt_observed_uidvalidity", observed)
            self._set("halt_new_uidvalidity", new_value)
            self._set("halted_at", _now())

    def halt_relay(self, reason: str) -> None:
        with self.db:
            self._set("relay_halt_reason", reason)
            self._set("relay_halted_at", _now())

    def status(self) -> dict[str, Any]:
        counts = {
            row["state"]: int(row["count"])
            for row in self.db.execute("SELECT state, COUNT(*) AS count FROM messages GROUP BY state")
        }
        return {
            "counts": counts,
            "last_uid": self.last_uid,
            "initialized": self.initialized,
            "collection_halted": self.collection_halted,
            "relay_halted": self.relay_halted,
        }

    def _advance(self, uid: int) -> None:
        if uid > self.last_uid:
            self._set("last_uid", uid)

    def advance_empty_search(self, upper: int) -> None:
        with self.db:
            self._advance(upper)

    def stage_oversize(
        self,
        uid: int,
        size: int,
        *,
        raw_sha256: str | None = None,
        reason: str = "oversized_original_in_mailbox",
    ) -> None:
        now = _now()
        with self.db:
            self.db.execute(
                """INSERT INTO messages(
                       mailbox,uidvalidity,uid,raw,raw_sha256,size,state,reason,
                       created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(mailbox,uidvalidity,uid) DO NOTHING""",
                (
                    self.mailbox,
                    self.uidvalidity,
                    uid,
                    None,
                    raw_sha256,
                    size,
                    "review",
                    reason,
                    now,
                    now,
                ),
            )
            self._advance(uid)

    def stage_raw(self, uid: int, raw: bytes, *, review_reason: str | None = None) -> str:
        if len(raw) > MAX_BYTES:
            raise QueueError("unexpected_message_size")
        digest = hashlib.sha256(raw).hexdigest()
        state = "review" if review_reason else "pending"
        reason = review_reason or "ready_for_relay"
        now = _now()
        with self.db:
            prior = self.db.execute(
                "SELECT raw_sha256,state FROM messages WHERE mailbox=? AND uidvalidity=? AND uid=?",
                (self.mailbox, self.uidvalidity, uid),
            ).fetchone()
            if prior is None:
                self.db.execute(
                    """INSERT INTO messages(
                           mailbox,uidvalidity,uid,raw,raw_sha256,size,state,reason,
                           created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        self.mailbox,
                        self.uidvalidity,
                        uid,
                        raw,
                        digest,
                        len(raw),
                        state,
                        reason,
                        now,
                        now,
                    ),
                )
            elif prior["raw_sha256"] != digest:
                self.db.execute(
                    """UPDATE messages SET state='review', reason=?, last_error=?, updated_at=?
                       WHERE mailbox=? AND uidvalidity=? AND uid=?""",
                    (
                        "raw_changed_for_identity",
                        f"observed_raw_sha256={digest}",
                        now,
                        self.mailbox,
                        self.uidvalidity,
                        uid,
                    ),
                )
            self._advance(uid)
        return digest

    def pending(self, limit: int = MAX_BATCH) -> Iterator[Message]:
        """Yield pending messages without materializing raw BLOBs as a batch.

        The first query is bounded metadata only.  Raw bytes are fetched for
        one identity immediately before it is yielded, so a queue of 50
        32-MiB messages cannot consume roughly 1.6 GiB just to enumerate work.
        """

        rows = self.db.execute(
            """SELECT mailbox,uidvalidity,uid,raw_sha256,size,state,reason,receipt_id,attempts
               FROM messages WHERE state='pending' ORDER BY uidvalidity,uid LIMIT ?""",
            (min(max(limit, 1), MAX_BATCH),),
        ).fetchall()
        for row in rows:
            raw_row = self.db.execute(
                """SELECT raw FROM messages
                   WHERE mailbox=? AND uidvalidity=? AND uid=?""",
                (row["mailbox"], row["uidvalidity"], row["uid"]),
            ).fetchone()
            yield Message(
                mailbox=row["mailbox"],
                uidvalidity=int(row["uidvalidity"]),
                uid=int(row["uid"]),
                raw=bytes(raw_row["raw"] or b"") if raw_row else b"",
                raw_sha256=str(row["raw_sha256"] or ""),
                size=int(row["size"]),
                state=row["state"],
                reason=row["reason"],
                receipt_id=row["receipt_id"],
                attempts=int(row["attempts"]),
            )

    def mark_attempt(self, message: Message, error: str) -> None:
        with self.db:
            self.db.execute(
                """UPDATE messages SET attempts=attempts+1,last_error=?,updated_at=?
                   WHERE mailbox=? AND uidvalidity=? AND uid=? AND state='pending'""",
                (
                    error[:200],
                    _now(),
                    message.mailbox,
                    message.uidvalidity,
                    message.uid,
                ),
            )

    def mark_delivered(self, message: Message, receipt_id: str) -> None:
        with self.db:
            self.db.execute(
                """UPDATE messages SET state='delivered',receipt_id=?,updated_at=?
                   WHERE mailbox=? AND uidvalidity=? AND uid=? AND state='pending'""",
                (
                    receipt_id,
                    _now(),
                    message.mailbox,
                    message.uidvalidity,
                    message.uid,
                ),
            )

    def mark_review(self, message: Message, reason: str, detail: str = "") -> None:
        with self.db:
            self.db.execute(
                """UPDATE messages SET state='review',reason=?,last_error=?,updated_at=?
                   WHERE mailbox=? AND uidvalidity=? AND uid=? AND state='pending'""",
                (
                    reason,
                    detail[:200],
                    _now(),
                    message.mailbox,
                    message.uidvalidity,
                    message.uid,
                ),
            )
