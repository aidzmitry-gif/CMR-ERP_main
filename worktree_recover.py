#!/usr/bin/env python3
"""worktree_recover.py — диагностика и восстановление застрявших git worktree (Windows).

deep-research: headless-флот на git worktree упирается в Windows-баги — worktree не
снимает lock / не удаляется, пока процесс держит файлы (GitHub #57767 / #41740). Этот
скрипт по умолчанию ТОЛЬКО показывает состояние; разрушительные действия — за явными
флагами.

  (без флагов)          git worktree list + пометки locked/prunable
  --prune               git worktree prune (снять админ-записи об удалённых каталогах)
  --unlock <name|all>   git worktree unlock для воркера (или всех залоченных)
  --remove <name>       убить процесс воркера (если есть pid) + git worktree remove --force
                        с ретраями (обходит файловый lock Windows)

Воркер ↔ worktree: ../crm-worker-<name>. Запуск:
  & ".\\.venv\\Scripts\\python.exe" worktree_recover.py [--prune] [--unlock <n>] [--remove <n>]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKTREE_PARENT = ROOT.parent
WORKTREE_PREFIX = "crm-worker-"
PID_DIR = ROOT / "coordination" / ".worker-pids"
REMOVE_RETRIES = 3


def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=60)


def _wt_path(name: str) -> Path:
    return WORKTREE_PARENT / f"{WORKTREE_PREFIX}{name}"


def _list() -> list[dict]:
    out = _git(["worktree", "list", "--porcelain"])
    trees: list[dict] = []
    cur: dict = {}
    for line in out.stdout.splitlines():
        if line.startswith("worktree "):
            if cur:
                trees.append(cur)
            cur = {"path": line[len("worktree "):].strip(), "branch": "", "locked": False,
                   "prunable": False}
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].strip().replace("refs/heads/", "")
        elif line.startswith("locked"):
            cur["locked"] = True
        elif line.startswith("prunable"):
            cur["prunable"] = True
    if cur:
        trees.append(cur)
    return trees


def _show() -> int:
    trees = _list()
    print(f"git worktree — {len(trees)} шт.:")
    for t in trees:
        flags = []
        if t["locked"]:
            flags.append("LOCKED")
        if t["prunable"]:
            flags.append("PRUNABLE")
        missing = not Path(t["path"]).is_dir()
        if missing:
            flags.append("НЕТ КАТАЛОГА")
        tag = ("  [" + ", ".join(flags) + "]") if flags else ""
        print(f"  {t['path']}  ({t['branch'] or 'detached'}){tag}")
    print("\nДействия: --prune | --unlock <name|all> | --remove <name>")
    return 0


def _kill_worker(name: str) -> None:
    pid_file = PID_DIR / f"{name}.pid"
    if not pid_file.is_file():
        return
    try:
        pid = int(pid_file.read_text(encoding="ascii", errors="ignore").strip())
    except (OSError, ValueError):
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, text=True)
    print(f"  процесс воркера {name} (pid {pid}) остановлен")


def _unlock(target: str) -> int:
    if target == "all":
        locked = [t for t in _list() if t["locked"]]
        if not locked:
            print("залоченных worktree нет")
            return 0
        for t in locked:
            r = _git(["worktree", "unlock", t["path"]])
            print(f"  unlock {t['path']}: {'ok' if r.returncode == 0 else r.stderr.strip()}")
        return 0
    wt = _wt_path(target)
    r = _git(["worktree", "unlock", str(wt)])
    print(f"unlock {wt}: {'ok ✓' if r.returncode == 0 else r.stderr.strip()}")
    return 0 if r.returncode == 0 else 1


def _remove(name: str) -> int:
    wt = _wt_path(name)
    _kill_worker(name)
    _git(["worktree", "unlock", str(wt)])  # снять lock, если есть (ошибку игнорируем)
    last = ""
    for attempt in range(1, REMOVE_RETRIES + 1):
        r = _git(["worktree", "remove", "--force", str(wt)])
        if r.returncode == 0:
            print(f"✓ worktree удалён: {wt}")
            _git(["worktree", "prune"])
            return 0
        last = (r.stderr or r.stdout).strip()
        print(f"  попытка {attempt}/{REMOVE_RETRIES} не удалась: {last}", file=sys.stderr)
        time.sleep(1.5)
    print(f"✗ не удалось удалить {wt}: {last}\n"
          f"  закрой окно воркера (stop {name}) и повтори, либо `git worktree prune` "
          f"после ручного удаления каталога.", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    _utf8()
    ap = argparse.ArgumentParser(description="Восстановление застрявших git worktree")
    ap.add_argument("--prune", action="store_true", help="git worktree prune")
    ap.add_argument("--unlock", metavar="NAME|all", help="снять lock с воркера или со всех")
    ap.add_argument("--remove", metavar="NAME", help="убить воркера + remove --force с ретраями")
    args = ap.parse_args(argv)

    if args.prune:
        r = _git(["worktree", "prune", "-v"])
        print((r.stdout or "prune: нечего чистить").strip())
        return 0
    if args.unlock:
        return _unlock(args.unlock)
    if args.remove:
        return _remove(args.remove)
    return _show()


if __name__ == "__main__":
    raise SystemExit(main())
