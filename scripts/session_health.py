#!/usr/bin/env python3
"""session_health.py — здоровье окружения при старте сессии (SessionStart-хук).

Заменяет ежедневный Telegram-дайджест и ночную ретроспективу: задачи планировщика
CRM-tg-digest / CRM-daily-review отключены 2026-07-16 (решение владельца, «вариант 2»
аудита сессий — статус приходит в момент, когда он нужен: при открытии сессии,
а не сообщением в мессенджер, который никто не читает).

Проверяет и впрыскивает в контекст через additionalContext:
- dev-серверы: backend :8000, frontend :3210 (socket-проба, 0.4с);
- свежесть coordination/readiness.json и дат авто-блоков STATUS.md (READINESS/COORD:AUTO);
- возраст coordination/ACTIVE-SESSIONS.md;
- дату последней ретроспективы coordination/daily-review/ (архив, больше не пополняется).

Философия — fail-open, как у claude_awareness_hook.py: любая ошибка/таймаут → exit 0
без вывода; хук НИКОГДА не ломает старт сессии. Только stdlib, без сети (кроме localhost).

Проверить вручную: `& ".\\.venv\\Scripts\\python.exe" scripts/session_health.py`
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
from pathlib import Path

STALE_MARKS_DAYS = 3.0   # авто-метки старше — считаем протухшими
STALE_ACTIVE_DAYS = 1.0  # ACTIVE-SESSIONS.md старше — флот-обзор неактуален


def _project_dir() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else Path(__file__).resolve().parent.parent


def _port_open(port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


def _age_days(p: Path) -> float | None:
    try:
        return (time.time() - p.stat().st_mtime) / 86400.0
    except Exception:
        return None


def _fmt_age(days: float | None) -> str:
    if days is None:
        return "нет файла"
    if days < 1:
        return f"{days * 24:.0f}ч"
    return f"{days:.1f}д"


def main() -> int:
    proj = _project_dir()
    coord = proj / "coordination"
    lines: list[str] = []
    stale: list[str] = []

    be = _port_open(8000)
    fe = _port_open(3210)
    lines.append(
        f"dev-серверы: backend :8000 {'OK' if be else 'DOWN'} · frontend :3210 {'OK' if fe else 'DOWN'}"
        + ("" if be and fe else " (поднять: конфигурации из .claude/launch.json)")
    )

    rj_age = _age_days(coord / "readiness.json")
    marks = []
    try:
        txt = (coord / "STATUS.md").read_text(encoding="utf-8", errors="replace")
        marks = re.findall(r"авто,\s*(?:обновлено\s*)?(\d{4}-\d{2}-\d{2})", txt)
    except Exception:
        pass
    marks_s = "/".join(marks) if marks else "не найдены"
    lines.append(f"метки: readiness.json {_fmt_age(rj_age)} · авто-блоки STATUS.md: {marks_s}")
    if rj_age is not None and rj_age > STALE_MARKS_DAYS:
        stale.append(f"readiness.json не обновлялся {_fmt_age(rj_age)}")
    for d in marks:
        try:
            mark_age = (time.time() - time.mktime(time.strptime(d, "%Y-%m-%d"))) / 86400.0
            if mark_age > STALE_MARKS_DAYS:
                stale.append(f"авто-блок STATUS.md от {d}")
            break  # достаточно самой свежей метки
        except Exception:
            pass

    act_age = _age_days(coord / "ACTIVE-SESSIONS.md")
    lines.append(f"ACTIVE-SESSIONS.md: {_fmt_age(act_age)}")
    if act_age is not None and act_age > STALE_ACTIVE_DAYS:
        stale.append(f"ACTIVE-SESSIONS.md устарел ({_fmt_age(act_age)})")

    try:
        reviews = sorted((coord / "daily-review").glob("2*.md"))
        last_review = reviews[-1].stem if reviews else "нет"
    except Exception:
        last_review = "?"
    lines.append(
        f"последняя ретроспектива: {last_review} (архив; ночной cron и tg-дайджест отключены 2026-07-16, см. coordination/daily-automation.md)"
    )

    header = "[session-health] Состояние окружения на старте сессии:"
    footer = (
        "⚠ Протухло: " + "; ".join(stale) + ". Упомяни это пользователю одной строкой в первом ответе."
        if stale
        else "Все метки свежие; DOWN dev-серверов — норма, если сессия не про запуск приложения."
    )
    text = "\n".join([header, *("- " + s for s in lines), footer])

    print(json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}},
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    try:
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8")
            except Exception:
                pass
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: здоровье не должно ломать старт сессии
