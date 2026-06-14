#!/usr/bin/env python3
"""claude_quality_hook.py — PostToolUse: мгновенный лят-гейт качества на изменённый файл.

Срабатывает после Edit/Write/MultiEdit. Делает две вещи:

  1) На .py-файл: ruff --fix (тихо чинит импорты/формат/isort), затем ruff check —
     если остались ошибки, печатает их в stderr и выходит кодом 2, чтобы Claude увидел
     и поправил СРАЗУ, не строя поверх битого кода.

  2) Любой код-файл (.py/.ts/.tsx) дописывает в реестр тронутого за ход:
     coordination/.touched-<session>.txt. По нему claude_stop_hook.py в конце хода
     гоняет ruff/tsc ТОЧЕЧНО — только по реально изменённому, не по всему грязному
     рабочему дереву. Реестр — по session_id, т.к. в одном дереве бывают параллельные
     сессии (см. coordination/ACTIVE-SESSIONS.md).

TS/TSX здесь tsc НЕ запускаем (медленно на каждый правёж) — это делает Stop-хук.
Философия: fail-open. Любая ошибка/таймаут → exit 0 (хук не ломает работу). ruff
вызывается тем же python, что запустил хук (венв с ruff); конфиг — из pyproject.toml.

Регистрация — в .claude/settings.json, событие PostToolUse, matcher Edit|Write|MultiEdit.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

TIMEOUT = 30
CODE_EXT = {".py", ".ts", ".tsx"}


def _project_dir() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else Path(__file__).resolve().parent


def _read_stdin() -> str:
    if sys.stdin.isatty():
        return ""
    try:  # байты + utf-8-sig: снимает BOM и не ломает кириллицу в путях (Windows cp1252)
        return sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return ""


def _session_id(data: dict) -> str:
    sid = re.sub(r"[^a-zA-Z0-9]", "", str(data.get("session_id") or ""))
    return sid[:8] or "nosess"


def _record_touched(proj: Path, sid: str, path: Path) -> None:
    try:
        ledger = proj / "coordination" / f".touched-{sid}.txt"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as f:
            f.write(str(path) + "\n")
    except OSError:
        pass  # реестр — вспомогательный; никогда не мешаем


def main() -> int:
    try:  # сообщения на русском должны уйти как UTF-8, а не cp866
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    raw = _read_stdin()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0

    if (data.get("tool_name") or "") not in ("Edit", "Write", "MultiEdit"):
        return 0
    ti = data.get("tool_input") or {}
    fp = (ti.get("file_path") or "") if isinstance(ti, dict) else ""
    if not fp:
        return 0
    path = Path(fp)
    if path.suffix.lower() not in CODE_EXT or not path.exists():
        return 0

    proj = _project_dir()
    _record_touched(proj, _session_id(data), path)

    if path.suffix.lower() != ".py":
        return 0  # ts/tsx — только реестр, проверку типов делает Stop-хук

    ruff = [sys.executable, "-m", "ruff", "check", "--force-exclude"]
    try:
        subprocess.run(
            [*ruff, "--fix", "--quiet", str(path)],
            cwd=str(proj), capture_output=True, timeout=TIMEOUT,
        )
        rep = subprocess.run(
            [*ruff, "--quiet", str(path)],
            cwd=str(proj), capture_output=True, text=True, timeout=TIMEOUT,
        )
    except Exception:
        return 0  # ruff не запустился / завис — не мешаем

    if rep.returncode != 0 and (rep.stdout.strip() or rep.stderr.strip()):
        out = ((rep.stdout or "") + (rep.stderr or "")).strip()
        sys.stderr.write(
            "[quality] ruff нашёл проблемы в изменённом файле — поправь перед "
            "продолжением:\n" + out[:4000] + "\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
