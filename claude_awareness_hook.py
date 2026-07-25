#!/usr/bin/env python3
"""claude_awareness_hook.py — read-сторона координации флота.

Дополняет write-сторону (`claude_pushlog_hook.py` пишет пуши в PUSH-LOG.md). Здесь —
впрыск контекста координации в ДРУГИЕ сессии через `additionalContext`:

- **SessionStart** → при старте любого чата в контекст уезжает: хвост `.activity.local.md`
  (что флот делал), таблица «Хотспоты» из ACTIVE-SESSIONS.md (кто что держит) и хвост
  PUSH-LOG.md (свежие пуши). Чат при старте сразу знает состояние флота.
- **PreToolUse** на `git push`/`git commit` → перед пушем впрыскиваются свежие чужие пуши +
  занятые хотспоты → сессия координируется в момент пуша (не утащить чужое, не тронуть хотспот).

Философия: fail-open. Любая ошибка/таймаут → exit 0 без вывода (хук НИКОГДА не ломает работу
и не блокирует инструмент). Регистрация — в .claude/settings.json (владелец — координатор).

Обслуживает события: SessionStart (полная/сокращённая версия — см. `source`), PreToolUse
(git push/commit), DirectoryAdded (/add-dir на чужую worktree/субмодуль).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ACTIVITY_REL = "coordination/.activity.local.md"
PUSHLOG_REL = "coordination/PUSH-LOG.md"
SESSIONS_REL = "coordination/ACTIVE-SESSIONS.md"
REPORTS_REL = "coordination/REPORTS.md"

ACTIVITY_TAIL = 20  # строк журнала активности на SessionStart
PUSHLOG_TAIL_START = 12  # строк PUSH-LOG на SessionStart
PUSHLOG_TAIL_PUSH = 8  # строк PUSH-LOG перед push/commit


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
    try:  # utf-8-sig снимает BOM, не ломает кириллицу (Windows)
        return sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return ""


def _tail(proj: Path, rel: str, n: int) -> str:
    """Последние n непустых строк файла; пусто при любой ошибке (fail-open)."""
    try:
        txt = (proj / rel).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    lines = [ln for ln in txt.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    return "\n".join(lines[-n:])


def _hotspots(proj: Path) -> str:
    """Секция «## Хотспоты» из ACTIVE-SESSIONS.md (таблица «кто держит файл»)."""
    try:
        txt = (proj / SESSIONS_REL).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    lines = txt.splitlines()
    out: list[str] = []
    grabbing = False
    for ln in lines:
        if ln.startswith("## Хотспоты"):
            grabbing = True
            out.append(ln)
            continue
        if grabbing:
            if ln.startswith("## ") or ln.startswith("---"):
                break
            out.append(ln)
    return "\n".join(out).strip()


def _emit(event: str, context: str) -> int:
    """Отдать additionalContext в формате hookSpecificOutput; пусто → молчим."""
    if not context.strip():
        return 0
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": context}
    }, ensure_ascii=False))
    return 0


# source, для которых транскрипт УЖЕ несёт впрыск родителя (fork) или предыдущий снимок
# (compact/clear прогоняют readiness.py --write) — полный ACTIVITY/PUSH-LOG/REPORTS даст
# модели противоречивые «свежие пуши» с разным временем.
_SHORT_SOURCES = ("fork", "compact", "clear")


def _session_start(proj: Path, src: str = "startup") -> int:
    parts = [
        "🧭 КООРДИНАЦИЯ ФЛОТА (read-хук). Реестр правит ТОЛЬКО координатор — пингуй его. "
        "Снимок состояния — coordination/STATUS.md. Перед `КООРД: DONE` сверься с DoD — coordination/DoD.md. "
        "Доклад координатору — строкой в конце хода: "
        "`КООРД: <DONE|BLOCKED|NEEDS-MIG|NEEDS-ARB|INFO> <полоса> — <суть>` (Stop-хук соберёт в REPORTS.md)."
    ]
    if src == "fork":
        parts.append(
            "⚠️ Это форк (/fork): реестр .touched родителя НЕ унаследован — правки файлов, "
            "которые уже правил родитель, могут получить deny от claude_audit_guard_hook.py."
        )
    if src not in _SHORT_SOURCES:
        activity = _tail(proj, ACTIVITY_REL, ACTIVITY_TAIL)
        if activity:
            parts.append("### Что флот делал недавно (.activity.local.md):\n" + activity)
        pushlog = _tail(proj, PUSHLOG_REL, PUSHLOG_TAIL_START)
        if pushlog:
            parts.append("### Свежие пуши (PUSH-LOG.md):\n" + pushlog)
        reports = _tail(proj, REPORTS_REL, 8)
        if reports:
            parts.append("### Открытые доклады полос (REPORTS.md):\n" + reports)
    hot = _hotspots(proj)
    if hot:
        parts.append("### " + hot)
    return _emit("SessionStart", "\n\n".join(parts))


def _pre_tool(proj: Path, data: dict) -> int:
    # PowerShell — штатный шелл проекта на Windows (см. claude_pushlog_hook.py)
    if (data.get("tool_name") or "") not in ("Bash", "PowerShell"):
        return 0
    ti = data.get("tool_input")
    cmd = str(ti.get("command") or "") if isinstance(ti, dict) else ""
    if "git push" not in cmd and "git commit" not in cmd:
        return 0
    parts = ["🧭 Перед push/commit — сверься с флотом (правило: пушь ТОЛЬКО свой коммит cherry-pick'ом на чистый origin-tip)."]
    pushlog = _tail(proj, PUSHLOG_REL, PUSHLOG_TAIL_PUSH)
    if pushlog:
        parts.append("### Свежие чужие пуши (PUSH-LOG.md):\n" + pushlog)
    hot = _hotspots(proj)
    if hot:
        parts.append("### " + hot)
    return _emit("PreToolUse", "\n\n".join(parts))


def _submodule_paths(proj: Path) -> list[str]:
    """Пути субмодулей из .gitmodules (для DirectoryAdded-предупреждения); пусто при ошибке."""
    try:
        txt = (proj / ".gitmodules").read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    paths = []
    for ln in txt.splitlines():
        ln = ln.strip()
        if ln.startswith("path"):
            _, _, val = ln.partition("=")
            val = val.strip()
            if val:
                paths.append(val)
    return paths


# Ключ пути в data неизвестен (событие новое, CC 2.1.219) — пробуем несколько вероятных.
_DIR_ADDED_KEYS = ("directory", "path", "added_directory", "directory_path", "dir", "cwd")


def _dir_added(proj: Path, data: dict) -> int:
    """DirectoryAdded (/add-dir на чужую worktree/субмодуль) — хотспоты + предупреждение."""
    path_raw = ""
    for key in _DIR_ADDED_KEYS:
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            path_raw = val.strip()
            break
    parts: list[str] = []
    if path_raw:
        norm = path_raw.replace("\\", "/").rstrip("/")
        is_worktree = ".claude/worktrees" in norm
        is_submodule = any(
            norm == sp.rstrip("/") or norm.endswith("/" + sp.rstrip("/"))
            for sp in _submodule_paths(proj)
        )
        if is_worktree or is_submodule:
            parts.append(
                f"⚠️ Добавлен каталог `{path_raw}` — это дерево ДРУГОЙ полосы (worktree/субмодуль). "
                "Правки координировать через coordination/ACTIVE-SESSIONS.md."
            )
    hot = _hotspots(proj)
    if hot:
        parts.append("### " + hot)
    return _emit("DirectoryAdded", "\n\n".join(parts))


def main() -> int:
    try:  # Windows-консоль по умолчанию cp1251 — иначе эмодзи/часть символов падают
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    raw = _read_stdin()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0

    proj = _project_dir()
    event = data.get("hook_event_name") or ""
    try:
        if event == "SessionStart":
            src = data.get("source") or "startup"
            return _session_start(proj, src)
        if event == "PreToolUse":
            return _pre_tool(proj, data)
        if event == "DirectoryAdded":
            return _dir_added(proj, data)
    except Exception:
        return 0  # fail-open: read-хук никогда не мешает работе
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open на точке входа (аналогично scripts/session_health.py); SystemExit не перехватывается
