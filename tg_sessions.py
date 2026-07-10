#!/usr/bin/env python3
"""tg_sessions.py — движок «вариант B» для tg_bridge.py: продолжение твоих
Claude Code сессий с телефона (handoff), на подписке.

Идея: каждая сессия Claude Code — это файл-транскрипт
(~/.claude/projects/<slug>/<session-id>.jsonl) со всем контекстом. Команда
`claude -p --resume <session-id>` (БЕЗ --fork-session) продолжает ТУ ЖЕ сессию:
тот же id, тот же файл. Значит на компе `claude --resume <id>` подхватит всё, что
наработано из Telegram. Это передача эстафеты (по очереди), а не два пилота разом.

Модуль не зовёт Anthropic API — только CLI `claude` (нативный .exe), который
авторизован подпиской Claude Code. Промпт подаётся в stdin (без кавычек-ада),
вывод парсится из `--output-format json`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import spawn_workers as sw  # noqa: E402

# Режим разрешений для headless-продолжения. acceptEdits — авто-применять правки
# файлов, но НЕ запускать произвольные команды (безопаснее на твоём рабочем репо).
# Для полного автонома (pytest/git из телефона) выстави bypassPermissions.
B_PERMISSION_MODE = os.environ.get("TG_B_PERMISSION_MODE", "acceptEdits")
# Модель: "inherit" = не передавать --model, использовать модель/настройки сессии.
B_MODEL = os.environ.get("TG_B_MODEL", "inherit")
# Один ход может длиться минуты; верхняя граница, чтобы не висеть вечно.
B_TURN_TIMEOUT = float(os.environ.get("TG_B_TURN_TIMEOUT", "1200"))

# PreToolUse deny-гард подключается ТОЛЬКО к удалённым B-ходам (через --settings),
# а не глобально — чтобы твоя интерактивная работа не платила ~0.25с за каждый вызов
# инструмента. Поставь TG_B_GUARD=0, если гард для B не нужен.
GUARD_HOOK = SCRIPT_DIR / "claude_guard_hook.py"
GUARD_SETTINGS = sw.COORD_DIR / ".guard-settings.json"
B_GUARD = os.environ.get("TG_B_GUARD", "1") not in ("0", "false", "False")


def _ensure_guard_settings() -> str | None:
    """Записать (один раз) settings-файл с PreToolUse-гардом и вернуть путь."""
    if not (B_GUARD and GUARD_HOOK.is_file()):
        return None
    cmd = f'"{sys.executable}" "{GUARD_HOOK}"'
    cfg = {"hooks": {"PreToolUse": [{
        "matcher": "Bash|Edit|Write|MultiEdit|Read|NotebookEdit",
        "hooks": [{"type": "command", "command": cmd}],
    }]}}
    try:
        GUARD_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        GUARD_SETTINGS.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(GUARD_SETTINGS)
    except OSError:
        return None


# ─── поиск CLI (предпочитаем нативный .exe — запускается из subprocess напрямую) ─


def resolve_cli() -> str | None:
    override = os.environ.get("CLAUDE_CLI")
    if override and Path(override).is_file():
        return override
    ext_roots = [
        Path.home() / ".vscode" / "extensions",
        Path.home() / ".cursor" / "extensions",
        Path.home() / ".vscode-server" / "extensions",
    ]
    found: list[tuple[list[int], str]] = []
    for root in ext_roots:
        if not root.is_dir():
            continue
        for d in root.glob("anthropic.claude-code-*"):
            exe = d / "resources" / "native-binary" / "claude.exe"
            if exe.is_file():
                m = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", d.name)
                ver = [int(x) for x in m.groups()] if m else [0, 0, 0]
                found.append((ver, str(exe)))
    if found:
        found.sort(reverse=True)
        return found[0][1]
    return sw._find_claude_cli()   # fallback (может быть .CMD)


# ─── чтение транскриптов (список сессий) ─────────────────────────────────────────


def _extract_text(entry: dict) -> str:
    msg = entry.get("message", {})
    content = msg.get("content") if isinstance(msg, dict) else msg
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
    return ""


def _read_meta(p: Path) -> tuple[str, str, str]:
    """(cwd, первая реплика пользователя, последняя реплика ассистента)."""
    cwd = first_user = last_text = ""
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                try:
                    d = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not cwd and d.get("cwd"):
                    cwd = d["cwd"]
                t = d.get("type")
                if t == "user" and not first_user:
                    first_user = _extract_text(d)
                elif t == "assistant":
                    tx = _extract_text(d)
                    if tx:
                        last_text = tx
    except OSError:
        pass
    return cwd, first_user, last_text


def list_sessions(limit: int = 12) -> list[dict]:
    """Недавние сессии Claude Code: самые свежие сверху."""
    base = sw.CLAUDE_PROJECTS_DIR
    if not base.is_dir():
        return []
    files = sorted(base.glob("*/*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out: list[dict] = []
    for p in files:
        cwd, fu, lt = _read_meta(p)
        out.append({
            "id": p.stem,
            "cwd": cwd,
            "project": Path(cwd).name or p.parent.name,
            "first": (fu or "").replace("\n", " ")[:90],
            "last": (lt or "").replace("\n", " ")[:140],
            "mtime": p.stat().st_mtime,
        })
    return out


# ─── один ход: resume / новая сессия ────────────────────────────────────────────


def _parse_result(stdout: str) -> dict | None:
    stdout = (stdout or "").strip()
    if not stdout:
        return None
    try:
        d = json.loads(stdout)
        if isinstance(d, dict):
            return d
    except json.JSONDecodeError:
        pass
    for line in reversed(stdout.splitlines()):   # последний JSON-объект
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                d = json.loads(line)
                if isinstance(d, dict) and ("result" in d or d.get("type") == "result"):
                    return d
            except json.JSONDecodeError:
                continue
    return None


def run_turn(text: str, *, resume_id: str | None = None, cwd: str | None = None,
             new_session: bool = False, perm: str | None = None,
             model: str | None = None, timeout: float | None = None) -> dict:
    """Прогнать один ход через CLI на подписке. Возвращает dict:
    {ok, result, session_id, cost, error}. Промпт идёт в stdin."""
    cli = resolve_cli()
    if not cli:
        return {"ok": False, "error": "claude CLI не найден (set $CLAUDE_CLI)"}
    cwd = cwd or str(sw.REPO_ROOT)
    perm = perm or B_PERMISSION_MODE
    model = model or B_MODEL
    timeout = timeout or B_TURN_TIMEOUT

    args = ["-p", "--output-format", "json", "--permission-mode", perm,
            "--add-dir", cwd]
    sid = resume_id
    if new_session:
        sid = resume_id or str(uuid.uuid4())   # известный заранее id новой сессии
        args += ["--session-id", sid]
    elif resume_id:
        args += ["--resume", resume_id]
    if model and model != "inherit":
        args += ["--model", model]
    guard = _ensure_guard_settings()       # гард только для B (не глобально)
    if guard:
        args += ["--settings", guard]

    # Удалённый/headless контекст → строгий тир гарда (claude_guard_hook.py).
    env = dict(os.environ)
    env["CLAUDE_GUARD_STRICT"] = "1"
    try:
        proc = subprocess.run(
            [cli] + args, input=text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=cwd, timeout=timeout, check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"таймаут {int(timeout)}s", "session_id": sid}
    except OSError as e:
        return {"ok": False, "error": f"запуск CLI не удался: {e}", "session_id": sid}

    res = _parse_result(proc.stdout)
    if res is None:
        tail = (proc.stdout or proc.stderr or "").strip()[-1500:]
        return {"ok": False, "session_id": sid,
                "error": f"не разобрал ответ CLI:\n{tail or '(пусто)'}"}
    is_err = bool(res.get("is_error"))
    return {
        "ok": not is_err,
        "result": res.get("result", ""),
        "session_id": res.get("session_id", sid),
        "cost": res.get("total_cost_usd"),
        "duration": res.get("duration_ms"),
        "turns": res.get("num_turns"),
        "error": res.get("result", "") if is_err else None,
    }
