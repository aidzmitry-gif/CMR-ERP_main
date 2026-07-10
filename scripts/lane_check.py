#!/usr/bin/env python3
"""scripts/lane_check.py — лёгкий eval-гейт полосы ПЕРЕД мержем (advisory по умолчанию).

Гоняет в порядке fast→slow: ruff → tsc --noEmit → pytest (по скоупу полосы). Печатает
[PASS]/[FAIL]/[SKIP] на чек + итоговую строку GATE. НЕ git-хук (tsc/pytest медленные) —
явная команда, которую полоса/координатор запускают перед интеграцией. НЕ модифицирует код.

  python scripts/lane_check.py                 весь дефолтный набор, advisory (всегда exit 0)
  python scripts/lane_check.py sales           pytest по скоупу полосы sales (+ ruff/tsc)
  python scripts/lane_check.py --peek sales    показать, ЧТО будет запущено, ничего не гоня
  python scripts/lane_check.py --strict        exit 1, если хоть один чек FAIL (для CI/гейта)
  python scripts/lane_check.py --skip-tsc      бэк-only полоса · --skip-pytest — фронт-only

Фронт-линт (eslint) в проекте НЕ установлен — верификация фронта только через tsc --noEmit.
Тесты — SQLite in-memory (Postgres не нужен), как в CLAUDE.md «Команды».
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable

# полоса → путь(и) тестов pytest. Нет в карте → весь tests/ (с предупреждением).
LANE_TESTS = {
    "sales": ["tests/", "modules/sales"],
    "crm": ["tests/"],
    "reference": ["tests/test_links.py", "tests/test_reference_registry.py", "tests/test_reference_categories.py"],
    "logistics": ["tests/test_links.py", "tests/test_logistics_tariffs.py", "tests/test_logistics_tender.py", "tests/unit/test_logistics_pricing.py"],
    "finance": ["tests/test_links.py"],
    "procurement": ["tests/test_landed_cost_alloc.py", "tests/test_links.py"],
    "wms": ["tests/test_links.py", "tests/test_erp.py"],
}


def _run(cmd: list[str], cwd: Path, env_extra: dict | None = None) -> int:
    import os
    env = {**os.environ, **(env_extra or {})}
    try:
        return subprocess.run(cmd, cwd=str(cwd), env=env).returncode
    except FileNotFoundError:
        return 127  # инструмент не найден → SKIP


def _line(status: str, name: str, detail: str = "") -> None:
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Eval-гейт полосы перед мержем")
    ap.add_argument("lane", nargs="?", default="", help="полоса (для скоупа pytest)")
    ap.add_argument("--strict", action="store_true", help="exit 1 при любом FAIL (CI/гейт)")
    ap.add_argument("--skip-pytest", action="store_true", help="фронт-only полоса")
    ap.add_argument("--skip-tsc", action="store_true", help="бэк-only полоса")
    ap.add_argument("--peek", action="store_true", help="показать план, не запускать")
    args = ap.parse_args(argv)

    tests = LANE_TESTS.get(args.lane.lower(), ["tests/"]) if not args.skip_pytest else []
    if args.lane and args.lane.lower() not in LANE_TESTS and not args.skip_pytest:
        print(f"(полоса '{args.lane}' не в карте тестов — гоню весь tests/)")

    if args.peek:
        print(f"python: {PY}")
        print(f"ruff:   {PY} -m ruff check .  (cwd={ROOT})")
        print(f"tsc:    npx tsc --noEmit       (cwd={FRONTEND})" if not args.skip_tsc else "tsc:    SKIP")
        print(f"pytest: {PY} -m pytest {' '.join(tests)} -q  (SQLite in-memory)" if tests else "pytest: SKIP")
        print("import: python -c 'import main'")
        return 0

    results: list[tuple[str, bool]] = []

    # 1) ruff (быстрый)
    rc = _run([PY, "-m", "ruff", "check", "."], ROOT)
    _line("SKIP" if rc == 127 else ("PASS" if rc == 0 else "FAIL"), "ruff")
    if rc not in (0, 127):
        results.append(("ruff", False))

    # 2) tsc --noEmit (фронт)
    if not args.skip_tsc and (FRONTEND / "tsconfig.json").exists():
        rc = _run(["npx", "tsc", "--noEmit"], FRONTEND)
        _line("SKIP" if rc == 127 else ("PASS" if rc == 0 else "FAIL"), "tsc --noEmit",
              "" if rc != 127 else "tsc/npx не найден")
        if rc not in (0, 127):
            results.append(("tsc", False))
    else:
        _line("SKIP", "tsc --noEmit", "пропущено")

    # 3) import main (дым импортов)
    rc = _run([PY, "-c", "import main"], ROOT, {"PYTHONPATH": ".", "AIOS_DATABASE_URL": "sqlite+aiosqlite:///:memory:"})
    _line("PASS" if rc == 0 else "FAIL", "import main")
    if rc != 0:
        results.append(("import", False))

    # 4) pytest по скоупу (SQLite in-memory)
    if tests:
        rc = _run([PY, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider"],
                  ROOT, {"PYTHONPATH": ".", "AIOS_DATABASE_URL": "sqlite+aiosqlite:///:memory:"})
        _line("SKIP" if rc == 127 else ("PASS" if rc == 0 else "FAIL"), "pytest", " ".join(tests))
        if rc not in (0, 127):
            results.append(("pytest", False))
    else:
        _line("SKIP", "pytest", "пропущено")

    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"\nGATE: FAIL ({', '.join(failed)})")
        return 1 if args.strict else 0
    print("\nGATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
