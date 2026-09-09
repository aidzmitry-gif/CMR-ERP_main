"""Cross-platform non-stale single-instance lock."""

from __future__ import annotations

import os
from pathlib import Path


class LockBusy(RuntimeError):
    """Another live worker holds the lock."""


class InstanceLock:
    """Hold an OS advisory lock for the lifetime of one worker operation.

    The lock file is deliberately left in place after release.  Its age is not
    evidence that a process is dead, so stale lock files are never deleted.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._fd: int | None = None

    def __enter__(self) -> "InstanceLock":
        if self.path.is_symlink():
            raise RuntimeError("lock_symlink_not_allowed")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT
        mode = 0o600 if os.name != "nt" else 0o666
        self._fd = os.open(self.path, flags, mode)
        if os.name != "nt" and self.path.stat().st_mode & 0o077:
            self._close_fd()
            raise RuntimeError("lock_requires_private_permissions")
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(self._fd, 0, os.SEEK_SET)
                os.write(self._fd, b"\0")
                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            self._close_fd()
            raise LockBusy("instance_lock_busy") from exc
        return self

    def _close_fd(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            self._close_fd()
