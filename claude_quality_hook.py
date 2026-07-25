#!/usr/bin/env python3
"""claude_quality_hook.py — PostToolUse: мгновенный лят-гейт качества на изменённый файл.

Срабатывает после Edit/Write. Делает две вещи:

  1) На .py-файл: ruff --fix (тихо чинит импорты/формат/isort), затем ruff check —
     если остались ошибки, печатает их в stderr и выходит кодом 2, чтобы Claude увидел
     и поправил СРАЗУ, не строя поверх битого кода.

  2) Любой код-файл (.py/.ts/.tsx) дописывает в реестр тронутого за ход:
     coordination/.touched-<session>.txt. По нему claude_stop_hook.py в конце хода
     гоняет ruff/tsc ТОЧЕЧНО — только по реально изменённому, не по всему грязному
     рабочему дереву. Реестр — по session_id, т.к. в одном дереве бывают параллельные
     сессии (см. coordination/ACTIVE-SESSIONS.md).
     Сабагенты наследуют sessionId родителя (их бывает до 20 одновременно, фоновые) —
     если их писать в один файл с родителем, Stop-хук родителя удалит реестр под
     работающим сабагентом. Поэтому файл сабагента — .touched-<session>-<agent>.txt
     (agent — ТОЛЬКО из payload agent_id/agentId); главный цикл (поля нет) пишет
     в прежний .touched-<session>.txt без суффикса.

TS/TSX здесь tsc НЕ запускаем (медленно на каждый правёж) — это делает Stop-хук.
Философия: fail-open. Любая ошибка/таймаут → exit 0 (хук не ломает работу). ruff
вызывается тем же python, что запустил хук (венв с ruff); конфиг — из pyproject.toml.

Регистрация — в .claude/settings.json, событие PostToolUse, matcher Edit|Write.
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
    """Каталог проекта. Хук ЛЕЖИТ в проекте, который обслуживает, поэтому его собственное
    расположение — источник истины. CLAUDE_PROJECT_DIR принимаем, только если он указывает на
    проект (есть coordination/) — это случай worktree воркера. Сессия, запущенная из
    каталога-родителя, отдаёт в этой переменной путь родителя: раньше хуки искали бы там
    coordination/ и не находили, а pushlog писал бы PUSH-LOG.md в чужой каталог."""
    here = Path(__file__).resolve().parent
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        p = Path(env)
        try:
            if p.resolve() == here or (p / "coordination").is_dir():
                return p
        except OSError:
            pass
    return here


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


def _agent_id(data: dict) -> str:
    """Идентификатор сабагента из payload; пусто = ГЛАВНЫЙ цикл (реестр без суффикса).

    ⚠ Фолбэк на имя файла транскрипта здесь был и оказался ловушкой: поле transcript_path
    приходит в payload ЛЮБОГО хука, включая главный цикл. Из-за него главный цикл писал в
    `.touched-<sid>-<стем>.txt`, а Stop-хук удаляет `.touched-<sid>.txt` — реестр не чистился
    ни разу за сессию, ruff-гейт перелинчивал всё тронутое с её начала, а audit-guard держал
    файлы «занятыми» все 8 часов. Сабагент опознаётся ТОЛЬКО по agent_id/agentId.
    """
    agent = data.get("agent_id") or data.get("agentId")
    if not agent:
        return ""
    return re.sub(r"[^a-zA-Z0-9]", "", str(agent))[:12]


def _record_touched(proj: Path, sid: str, agent: str, path: Path) -> None:
    try:
        # суффикс агента — чтобы сабагенты не делили один файл реестра с родителем
        # и друг с другом (см. заголовок файла)
        suffix = f"-{agent}" if agent else ""
        ledger = proj / "coordination" / f".touched-{sid}{suffix}.txt"
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

    # NotebookEdit сюда НЕ включён намеренно: хук гоняет ruff по CODE_EXT (.py/.ts/.tsx),
    # а .ipynb в проекте нет ни одного (проверено 25.07.2026) — ветка была бы мёртвой.
    # Появятся ноутбуки — добавить сюда, в CODE_EXT и в matcher settings.json разом.
    if (data.get("tool_name") or "") not in ("Edit", "Write"):
        return 0
    ti = data.get("tool_input") or {}
    fp = (ti.get("file_path") or "") if isinstance(ti, dict) else ""
    if not fp:
        return 0
    path = Path(fp)
    if path.suffix.lower() not in CODE_EXT or not path.exists():
        return 0

    proj = _project_dir()
    _record_touched(proj, _session_id(data), _agent_id(data), path)

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
            encoding="utf-8", errors="replace",  # иначе на Windows cp1251/cp866 ломает кириллицу
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
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # fail-open: необработанная ошибка не должна ронять ход
