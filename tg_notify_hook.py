#!/usr/bin/env python3
"""tg_notify_hook.py — Claude Code hook → очередь событий для tg_bridge.py.

Вешается на событие Notification (срабатывает, когда интерактивная сессия ждёт
ввода/разрешения). Читает JSON хука из stdin и дописывает компактную запись в
coordination/.tg-events.jsonl. Бот (tg_bridge.py) пересылает её в топик «💬 VSCode».

Путь очереди резолвится от расположения ЭТОГО файла, поэтому хук работает и когда
срабатывает из сессий других проектов: события всё равно лягут в очередь этого репо.

Хук обязан отработать быстро и завершиться кодом 0 (не блокировать сессию).
Регистрация — ТОЛЬКО в проектном .claude/settings.json (проверено: в пользовательском
~/.claude/settings.json хук не прописан). См. coordination/TG-BRIDGE.md.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# utf-8 на stdout/stderr — на всякий случай, если хук что-то печатает в консоль Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

QUEUE = Path(__file__).resolve().parent / "coordination" / ".tg-events.jsonl"


def main() -> int:
    # stdin читаем БАЙТАМИ и декодируем как utf-8-sig: sys.stdin.read() берёт
    # кодек локали и на Windows падает UnicodeDecodeError на кириллице (как в
    # остальных хуках проекта) — теряли бы уведомление молча.
    raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace") if not sys.stdin.isatty() else ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {"raw": raw[:500]}

    # Сабагенты наследуют session_id родителя, а фоновые тоже умеют ждать ввод —
    # без agent/transcript несколько сессий одного чата неотличимы в очереди.
    transcript_path = data.get("transcript_path") or ""
    rec = {
        "ts": time.time(),
        "event": data.get("hook_event_name") or "Notification",
        "session": (data.get("session_id") or "")[:8],
        "agent": (data.get("agent_id") or data.get("agentId") or "")[:12],
        "transcript": Path(transcript_path).stem[:16] if transcript_path else "",
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
    try:
        raise SystemExit(main())
    except Exception:
        # правка 4: глобальный fail-open — баг хука не должен блокировать сессию
        raise SystemExit(0)
