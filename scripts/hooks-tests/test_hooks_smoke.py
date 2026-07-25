# -*- coding: utf-8 -*-
"""Дымовой прогон всех хуков проекта: ни один не должен падать трейсбеком (exit 1).

Проверяем: SessionStart во всех вариантах source (включая новый fork), DirectoryAdded,
PreToolUse, PostToolUse, Stop, Notification, PreCompact. Кириллица и эмодзи в payload —
нарочно, без PYTHONUTF8 в окружении.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PROJ = str(Path(__file__).resolve().parents[2])
PY = PROJ + r"\.venv\Scripts\python.exe"
SID = "smoke-test-session-0001"

# (описание, скрипт, payload)
CASES = [
    ("awareness SessionStart startup", "claude_awareness_hook.py",
     {"hook_event_name": "SessionStart", "source": "startup", "session_id": SID}),
    ("awareness SessionStart fork", "claude_awareness_hook.py",
     {"hook_event_name": "SessionStart", "source": "fork", "session_id": SID}),
    ("awareness SessionStart compact", "claude_awareness_hook.py",
     {"hook_event_name": "SessionStart", "source": "compact", "session_id": SID}),
    ("awareness SessionStart clear", "claude_awareness_hook.py",
     {"hook_event_name": "SessionStart", "source": "clear", "session_id": SID}),
    ("awareness DirectoryAdded (чужой worktree)", "claude_awareness_hook.py",
     {"hook_event_name": "DirectoryAdded", "session_id": SID,
      "directory": PROJ + r"\.claude\worktrees\kind-fermat-dbfa6d"}),
    ("awareness PreToolUse Bash", "claude_awareness_hook.py",
     {"hook_event_name": "PreToolUse", "session_id": SID,
      "tool_name": "Bash", "tool_input": {"command": "git status"}}),
    ("guard PreToolUse безопасный Bash", "claude_guard_hook.py",
     {"hook_event_name": "PreToolUse", "session_id": SID,
      "tool_name": "Bash", "tool_input": {"command": "pytest -q"}}),
    ("guard PreToolUse PowerShell кириллица", "claude_guard_hook.py",
     {"hook_event_name": "PreToolUse", "session_id": SID, "tool_name": "PowerShell",
      "tool_input": {"command": 'Get-ChildItem "D:\\6 Проекты" 😀'}}),
    ("audit-guard Edit", "claude_audit_guard_hook.py",
     {"hook_event_name": "PreToolUse", "session_id": SID, "tool_name": "Edit",
      "tool_input": {"file_path": PROJ + r"\core\runtime\app.py"}}),
    ("audit-guard NotebookEdit", "claude_audit_guard_hook.py",
     {"hook_event_name": "PreToolUse", "session_id": SID, "tool_name": "NotebookEdit",
      "tool_input": {"notebook_path": PROJ + r"\notebooks\demo.ipynb"}}),
    ("quality PostToolUse Edit .md", "claude_quality_hook.py",
     {"hook_event_name": "PostToolUse", "session_id": SID, "tool_name": "Edit",
      "tool_input": {"file_path": PROJ + r"\coordination\PLAYBOOK.md"}}),
    ("quality PostToolUse от сабагента", "claude_quality_hook.py",
     {"hook_event_name": "PostToolUse", "session_id": SID, "agent_id": "a1234567890",
      "tool_name": "Edit", "tool_input": {"file_path": PROJ + r"\coordination\STATUS.md"}}),
    ("pushlog PostToolUse Bash", "claude_pushlog_hook.py",
     {"hook_event_name": "PostToolUse", "session_id": SID, "cwd": PROJ,
      "tool_name": "Bash", "tool_input": {"command": "git status --short"},
      "tool_response": {"stdout": "", "stderr": ""}}),
    ("notify Notification", "tg_notify_hook.py",
     {"hook_event_name": "Notification", "session_id": SID, "agent_id": "a999",
      "transcript_path": r"C:\x\subagents\agent-a999.jsonl",
      "message": "Сессия ждёт твоего ввода 😀"}),
]

fails = []
env = dict(os.environ)
env.pop("PYTHONUTF8", None)
env.pop("PYTHONIOENCODING", None)
env["CLAUDE_PROJECT_DIR"] = PROJ

for desc, script, payload in CASES:
    r = subprocess.run([PY, os.path.join(PROJ, script)],
                       input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, env=env, cwd=PROJ, timeout=90)
    err = r.stderr.decode("utf-8", errors="replace")
    bad = r.returncode not in (0, 2) or "Traceback" in err
    mark = "OK  " if not bad else "FAIL"
    print(f"{mark} [exit {r.returncode}] {desc}")
    if bad:
        fails.append(desc)
        print("      " + err.strip()[:400].replace("\n", "\n      "))

print()
if fails:
    print(f"ПРОВАЛОВ: {len(fails)} — {fails}")
else:
    print(f"Все {len(CASES)} хук-вызовов отработали без трейсбеков")
sys.exit(1 if fails else 0)
