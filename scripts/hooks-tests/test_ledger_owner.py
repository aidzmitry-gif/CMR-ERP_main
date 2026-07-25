# -*- coding: utf-8 -*-
"""Владение реестром .touched: свой и сабагентский — пропускаем, чужой — блокируем.

Регрессия, от которой защищаемся: слишком широкое правило («реестр начинается с sid»)
пропустило бы чужую сессию, чей id начинается с нашего; слишком узкое — заблокировало бы
правку файлов, которые трогал собственный сабагент.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
PY = PROJ / ".venv" / "Scripts" / "python.exe"
HOOK = PROJ / "claude_audit_guard_hook.py"

SID = "abc12345"
# (описание, имя реестра, ожидаем_блок)
CASES = [
    ("свой реестр", f".touched-{SID}.txt", False),
    ("реестр своего сабагента", f".touched-{SID}-agentX.txt", False),
    ("реестр своего сабагента (длинный id)", f".touched-{SID}-a1b2c3d4e5f6.txt", False),
    ("ЧУЖАЯ сессия с похожим префиксом", f".touched-{SID}9999.txt", True),
    ("ЧУЖАЯ сессия", ".touched-zzz99999.txt", True),
]

fails = 0
for desc, ledger_name, want_deny in CASES:
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "proj"
        (fake / "coordination").mkdir(parents=True)
        target = fake / "core" / "app.py"
        target.parent.mkdir(parents=True)
        target.write_text("x = 1\n", encoding="utf-8")
        (fake / "coordination" / ledger_name).write_text(str(target) + "\n", encoding="utf-8")
        shutil.copy2(HOOK, fake / HOOK.name)

        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(fake)
        env.pop("AIOS_ALLOW_FOREIGN_EDIT", None)
        payload = {"hook_event_name": "PreToolUse", "session_id": SID,
                   "tool_name": "Edit", "tool_input": {"file_path": str(target)}}
        r = subprocess.run([str(PY), str(fake / HOOK.name)],
                           input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           capture_output=True, env=env, cwd=str(fake), timeout=60)
        out = r.stdout.decode("utf-8", errors="replace")
        denied = '"permissionDecision": "deny"' in out or '"deny"' in out
        ok = denied == want_deny
        if not ok:
            fails += 1
        print(f"{'OK  ' if ok else 'FAIL'} {desc}: блок={denied}, ожидали={want_deny}")

print(f"\n{'Все прошли' if not fails else f'ПРОВАЛОВ: {fails}'}")
sys.exit(1 if fails else 0)
