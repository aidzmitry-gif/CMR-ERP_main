# -*- coding: utf-8 -*-
"""Хуки должны работать одинаково, из какого бы каталога ни стартовала сессия.

Проверяем оба значения CLAUDE_PROJECT_DIR: проект и каталог-родитель. Во втором случае
раньше хуки искали coordination/ у родителя (там его нет), а pushlog писал бы туда PUSH-LOG.md.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PROJ = str(Path(__file__).resolve().parents[2])
PARENT = str(Path(__file__).resolve().parents[2].parent)
PY = PROJ + r"\.venv\Scripts\python.exe"

CASES = [
    ("guard: PowerShell читает .env", "claude_guard_hook.py",
     {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "PowerShell",
      "tool_input": {"command": "Get-Content .env"}}, 2),
    ("guard: безопасная команда", "claude_guard_hook.py",
     {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Bash",
      "tool_input": {"command": "git status"}}, 0),
    ("awareness: SessionStart", "claude_awareness_hook.py",
     {"hook_event_name": "SessionStart", "source": "startup", "session_id": "s1"}, 0),
    ("awareness: DirectoryAdded", "claude_awareness_hook.py",
     {"hook_event_name": "DirectoryAdded", "session_id": "s1",
      "directory": PROJ + r"\.claude\worktrees\kind-fermat-dbfa6d"}, 0),
    ("audit-guard: Edit", "claude_audit_guard_hook.py",
     {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Edit",
      "tool_input": {"file_path": PROJ + r"\core\runtime\app.py"}}, 0),
    ("session_health", "scripts/session_health.py",
     {"hook_event_name": "SessionStart", "source": "startup", "session_id": "s1"}, 0),
]

fails = 0
for cpd_name, cpd in (("проект", PROJ), ("родитель", PARENT)):
    print(f"\n--- CLAUDE_PROJECT_DIR = {cpd_name} ---")
    for desc, script, payload, want in CASES:
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = cpd
        env.pop("PYTHONUTF8", None)
        env.pop("PYTHONIOENCODING", None)
        r = subprocess.run([PY, os.path.join(PROJ, script)],
                           input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           capture_output=True, env=env, cwd=cpd, timeout=120)
        err = r.stderr.decode("utf-8", errors="replace")
        ok = r.returncode == want and "Traceback" not in err
        # содержательная проверка: впрыск должен упоминать координацию, а не быть пустым
        out = r.stdout.decode("utf-8", errors="replace")
        if ok and script == "claude_awareness_hook.py" and payload["hook_event_name"] == "SessionStart":
            ok = "КООРДИНАЦИЯ" in out or "Хотспоты" in out
            if not ok:
                err = "впрыск пустой — хук не нашёл coordination/"
        if not ok:
            fails += 1
        print(f"{'OK  ' if ok else 'FAIL'} [{r.returncode}/{want}] {desc}")
        if not ok and err:
            print("      " + err.strip()[:200])

# PUSH-LOG.md не должен появиться у родителя
stray = os.path.join(PARENT, "coordination")
print(f"\nкаталог coordination у родителя создан: {os.path.isdir(stray)} (должно быть False)")
if os.path.isdir(stray):
    fails += 1

print(f"\n{'Все прошли' if not fails else f'ПРОВАЛОВ: {fails}'}")
sys.exit(1 if fails else 0)
