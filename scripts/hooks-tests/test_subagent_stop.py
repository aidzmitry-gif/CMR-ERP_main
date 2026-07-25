# -*- coding: utf-8 -*-
"""Уборка реестров .touched: кто чей файл удаляет.

Инвариант: реестр чистит его собственный писатель. Родитель на Stop гейтит всё (чтобы
ничего не проскочило мимо ruff), но удаляет только свой + заведомо протухшие сабагентские;
сабагент на SubagentStop работает ровно со своим.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
PY = PROJ / ".venv" / "Scripts" / "python.exe"
HOOK = PROJ / "claude_stop_hook.py"
SID = "abc12345"

GOOD = "x = 1\n"          # ruff-чистый


def run(agent_id, ledgers, stale=()):
    """Создаёт песочницу с реестрами, зовёт хук, возвращает (rc, оставшиеся реестры)."""
    td = tempfile.mkdtemp()
    try:
        fake = Path(td) / "proj"
        (fake / "coordination").mkdir(parents=True)
        shutil.copy2(HOOK, fake / HOOK.name)
        src = fake / "mod.py"
        src.write_text(GOOD, encoding="utf-8")
        for lg in ledgers:
            f = fake / "coordination" / lg
            f.write_text(str(src) + "\n", encoding="utf-8")
            if lg in stale:  # состарить на 9 часов (порог хука — 8)
                old = time.time() - 9 * 3600
                os.utime(f, (old, old))
        payload = {"hook_event_name": "SubagentStop" if agent_id else "Stop",
                   "session_id": SID}
        if agent_id:
            payload["agent_id"] = agent_id
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(fake)
        r = subprocess.run([str(PY), str(fake / HOOK.name)],
                           input=json.dumps(payload).encode("utf-8"),
                           capture_output=True, env=env, cwd=str(fake), timeout=180)
        left = sorted(p.name for p in (fake / "coordination").glob(".touched-*.txt"))
        return r.returncode, left
    finally:
        shutil.rmtree(td, ignore_errors=True)


CASES = [
    ("родитель: свой удаляет, живой сабагентский оставляет",
     None, [f".touched-{SID}.txt", f".touched-{SID}-agentA.txt"], (),
     [f".touched-{SID}-agentA.txt"]),
    ("родитель: протухший сабагентский подметает",
     None, [f".touched-{SID}.txt", f".touched-{SID}-old.txt"], (f".touched-{SID}-old.txt",),
     []),
    ("сабагент: удаляет ТОЛЬКО свой",
     "agentA", [f".touched-{SID}.txt", f".touched-{SID}-agentA.txt"], (),
     [f".touched-{SID}.txt"]),
    ("сабагент: чужой сабагентский не трогает",
     "agentA", [f".touched-{SID}-agentA.txt", f".touched-{SID}-agentB.txt"], (),
     [f".touched-{SID}-agentB.txt"]),
]

fails = 0
for desc, agent, ledgers, stale, want_left in CASES:
    rc, left = run(agent, ledgers, stale)
    ok = rc == 0 and left == sorted(want_left)
    if not ok:
        fails += 1
    print(f"{'OK  ' if ok else 'FAIL'} [rc={rc}] {desc}")
    if not ok:
        print(f"      осталось={left}, ожидали={sorted(want_left)}")

print(f"\n{'Все прошли' if not fails else f'ПРОВАЛОВ: {fails}'}")
sys.exit(1 if fails else 0)
