#!/usr/bin/env python3
"""scripts/lane_worktree.py — изолированный worktree на полосу (чистая ветка от origin).

Зачем: на ОБЩЕЙ ветке `sales-2.0-redesign` несколько сессий коммитят разом → HEAD дрейфует,
amend опасен, push приходится cherry-pick'ить. Своя ветка/worktree на полосу убирает это:
HEAD не дрейфует, amend безопасен, push — обычный (ветка только твоя), интеграция — координатор.

  python scripts/lane_worktree.py <lane>            создать ../_wt_<lane> на ветке sales-2.0-<lane>
  python scripts/lane_worktree.py <lane> --dry-run  только показать, что будет сделано
  python scripts/lane_worktree.py <lane> --base origin/main   иная база (по умолч. origin/sales-2.0-redesign)

Создание worktree НЕ трогает общую ветку (безопасно). Сабмодули инициализируются в новом worktree.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Windows-консоль cp1251 → print() стрелок/эмодзи (→/✅/⚠) валит UnicodeEncodeError. UTF-8 с заменой.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = "origin/sales-2.0-redesign"


def _git(*args: str, check: bool = False) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    if check and r.returncode != 0:
        print(f"git {' '.join(args)} → код {r.returncode}\n{out}", file=sys.stderr)
        sys.exit(1)
    return r.returncode, out.strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Изолированный worktree на полосу")
    ap.add_argument("lane", help="имя полосы (logistics, finance, office, hr, marketing, …)")
    ap.add_argument("--base", default=DEFAULT_BASE, help=f"база ветки (по умолч. {DEFAULT_BASE})")
    ap.add_argument("--dry-run", action="store_true", help="только показать план")
    args = ap.parse_args(argv)

    lane = args.lane.strip().lower()
    branch = f"sales-2.0-{lane}"
    wt_path = ROOT.parent / f"_wt_{lane}"

    print(f"Полоса:    {lane}")
    print(f"Ветка:     {branch}  (база {args.base})")
    print(f"Worktree:  {wt_path}")

    # уже существует?
    _, wts = _git("worktree", "list")
    if str(wt_path) in wts or wt_path.exists():
        print(f"\n⚠️ {wt_path} уже существует. Открой её или удали: "
              f"git worktree remove \"{wt_path}\"")
        return 1
    _, branches = _git("branch", "--list", branch)
    if branches.strip():
        print(f"\n⚠️ Ветка {branch} уже есть. Используй её "
              f"(git worktree add \"{wt_path}\" {branch}) или удали.")
        return 1

    if args.dry_run:
        print("\n[dry-run] выполнил бы:")
        print("  git fetch origin")
        print(f"  git worktree add \"{wt_path}\" -b {branch} {args.base}")
        print(f"  git -C \"{wt_path}\" submodule update --init --recursive")
        return 0

    print("\n→ git fetch origin …")
    _git("fetch", "origin", check=True)
    print(f"→ git worktree add (ветка {branch} от {args.base}) …")
    _git("worktree", "add", str(wt_path), "-b", branch, args.base, check=True)
    print("→ submodule update --init --recursive …")
    _git("-C", str(wt_path), "submodule", "update", "--init", "--recursive")

    # ⚠ Gotcha worktree+submodule: локально-незапушенный коммит субмодуля недостижим в новом
    # worktree (отдельный object store) → gitlink mismatch. Детектим и показываем фикс.
    _, st = _git("-C", str(wt_path), "submodule", "status")
    mism = [ln.strip() for ln in st.splitlines() if ln[:1] in ("+", "-")]
    if mism:
        print("\n⚠️ Субмодули рассинхронены (локальный незапушенный коммит не достижим в worktree):")
        for ln in mism:
            print("   " + ln)
        print("   Фикс. <sub> = путь субмодуля, <sha> = gitlink (git ls-tree HEAD <sub>):")
        print(f'     git -C "{wt_path}/<sub>" fetch "{ROOT}/<sub>" <sha> && git -C "{wt_path}" submodule update --recursive <sub>')

    print("\n✅ Готово. Дальше:")
    print(f"  1. Открой Claude/терминал с cwd = {wt_path}")
    print(f"  2. Работай в своей ветке {branch} — HEAD не дрейфует, amend безопасен.")
    print(f"  3. Коммить мелко; push своей ветки: git push -u origin {branch} (по просьбе оператора).")
    print("  4. Интеграция в общую ветку — через координатора (он мержит/cherry-pick'ит).")
    print(f"  5. По завершении: git worktree remove \"{wt_path}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
