#!/usr/bin/env python3
"""fleet_dashboard.py — единый экран состояния флота воркеров (ТОЛЬКО чтение).

Сводит в ОДНУ таблицу то, что иначе разбросано по coordination/.workers-state.json,
*-status.md, git и гейтам приёмки — закрывает дыру наблюдаемости (для headless-флота
first-party паттерна нет; см. deep-research / automation-roadmap). Ничего не меняет.

Колонки на воркера:
  • age    — сколько прошло с spawned_at (coordination/.workers-state.json);
  • ahead  — коммитов впереди main (ветка = имя воркера);
  • gate   — acceptance_gate: ЗЕЛЁНЫЙ / k/n / — (coordination/acceptance/<name>.json);
  • state  — STATE-баннер из status-файла (worktree или coordination/<name>-status.md);
  • last   — время + тема последнего коммита ветки.

Запуск:  & ".\\.venv\\Scripts\\python.exe" fleet_dashboard.py [--no-ci]
Вывод:   таблица в консоль + coordination/FLEET.md.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COORD = ROOT / "coordination"
ACC = COORD / "acceptance"
STATE_FILE = COORD / ".workers-state.json"
WORKTREE_PARENT = ROOT.parent
WORKTREE_PREFIX = "crm-worker-"
BASE = "main"
STATE_RX = re.compile(r"STATE:\s*([A-Za-z][A-Za-z-]+)")


def _git(args: list[str]) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _state() -> dict[str, dict]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _workers(state: dict) -> list[str]:
    names = set(state)
    if ACC.is_dir():
        names |= {p.stem for p in ACC.glob("*.json")}
    return sorted(names)


def _branch_exists(name: str) -> bool:
    return bool(_git(["rev-parse", "--verify", "--quiet", name]))


def _ahead(name: str) -> str:
    if not _branch_exists(name):
        return "—"
    return _git(["rev-list", "--count", f"{BASE}..{name}"]) or "0"


def _last_commit(name: str) -> str:
    if not _branch_exists(name):
        return "—"
    out = _git(["log", "-1", "--format=%cr · %s", name])
    return (out[:46] + "…") if len(out) > 47 else out or "—"


def _gate(name: str) -> str:
    path = ACC / f"{name}.json"
    if not path.is_file():
        return "—"
    try:
        checks = json.loads(path.read_text(encoding="utf-8-sig")).get("checks", [])
    except (OSError, json.JSONDecodeError):
        return "ПОВРЕЖДЁН"
    if not checks:
        return "пуст"
    done = 0
    for c in checks:
        passed = bool(c.get("passes")) and (bool(c.get("cmd")) or bool(str(c.get("evidence", "")).strip()))
        done += int(passed)
    return "ЗЕЛЁНЫЙ" if done == len(checks) else f"{done}/{len(checks)}"


def _state_banner(name: str) -> str:
    candidates = [
        WORKTREE_PARENT / f"{WORKTREE_PREFIX}{name}" / "coordination" / f"{name}-status.md",
        COORD / f"{name}-status.md",
    ]
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        found = STATE_RX.findall(text)
        if found:
            return found[-1].upper()
    return "—"


def _age(spawned_at: str) -> str:
    if not spawned_at:
        return "—"
    try:
        then = datetime.fromisoformat(spawned_at)
    except ValueError:
        return "—"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    secs = max(0, int((datetime.now(timezone.utc) - then).total_seconds()))
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def _ci_line(enabled: bool) -> str:
    if not enabled:
        return ""
    from shutil import which
    if not which("gh"):
        return "CI(main): gh не установлен"
    try:
        r = subprocess.run(
            ["gh", "run", "list", "-L", "1", "--json", "status,conclusion,workflowName"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=20,
        )
        runs = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []
    except Exception:
        return "CI(main): n/a"
    if not runs:
        return "CI(main): прогонов нет (ветки локальные?)"
    run = runs[0]
    return f"CI(main): {run.get('conclusion') or run.get('status')} ({run.get('workflowName')})"


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    no_ci = "--no-ci" in (argv if argv is not None else sys.argv[1:])
    state = _state()
    workers = _workers(state)
    rows = []
    for name in workers:
        rows.append((
            name,
            _age(state.get(name, {}).get("spawned_at", "")),
            _ahead(name),
            _gate(name),
            _state_banner(name),
            _last_commit(name),
        ))

    ci = _ci_line(not no_ci)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    header = f"ФЛОТ — {stamp} · {len(rows)} воркер(ов)" + (f"   {ci}" if ci else "")

    cols = ["worker", "age", "ahead", "gate", "state", "last commit"]
    widths = [max(len(cols[i]), *(len(str(r[i])) for r in rows)) if rows else len(cols[i])
              for i in range(len(cols))]

    def fmt(vals: tuple | list) -> str:
        return "  ".join(str(v).ljust(widths[i]) for i, v in enumerate(vals))

    lines = [header, "", fmt(cols), "  ".join("-" * w for w in widths)]
    lines += [fmt(r) for r in rows] or ["  (воркеров не найдено)"]
    out = "\n".join(lines)
    print(out)

    # markdown-зеркало для coordination/FLEET.md
    md = [f"# Флот воркеров — {stamp}", "", (ci or "")[:200], "",
          "| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    md += ["| " + " | ".join(str(v) for v in r) + " |" for r in rows]
    try:
        (COORD / "FLEET.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
