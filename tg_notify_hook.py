#!/usr/bin/env python3
"""tg_notify_hook.py — Claude Code hook → очередь событий для tg_bridge.py.

Вешается на событие Notification (срабатывает, когда интерактивная сессия ждёт
ввода/разрешения). Читает JSON хука из stdin и дописывает компактную запись в
coordination/.tg-events.jsonl. Бот (tg_bridge.py) пересылает её в топик «💬 VSCode».

Путь очереди резолвится от расположения ЭТОГО файла, поэтому хук работает и когда
он прописан в пользовательском ~/.claude/settings.json и срабатывает из сессий
других проектов: события всё равно лягут в очередь этого репо.

Хук обязан отработать быстро и завершиться кодом 0 (не блокировать сессию).
Регистрация — в .claude/settings.json, см. coordination/TG-BRIDGE.md.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

QUEUE = Path(__file__).resolve().parent / "coordination" / ".tg-events.jsonl"


def main() -> int:
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {"raw": raw[:500]}

    rec = {
        "ts": time.time(),
        "event": data.get("hook_event_name") or "Notification",
        "session": (data.get("session_id") or "")[:8],
        "cwd": data.get("cwd") or "",
        "message": data.get("message") or "",
    }
    try:
        QUEUE.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # никогда не мешаем сессии
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
