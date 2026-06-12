"""Сканер готовности модулей — объективные метрики без ручного обхода.

Запуск:  python scripts/readiness.py
Печатает таблицу loc / роуты / миграции / тип фронта по каждому модулю.
Субъективный % выставляется вручную в coordination/STATUS.md (этот скрипт его НЕ трогает).

Цель — дать свежие цифры одной командой, чтобы не сканировать дерево вручную каждый раз.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = [
    "sales", "procurement", "production", "wms", "logistics",
    "finance", "marketing", "service", "hr",
]
ROUTE_RE = re.compile(r"@router\.(get|post|put|patch|delete)\b")
MIGR_DIR = ROOT / "migrations" / "versions"
FE_APP = ROOT / "frontend" / "src" / "app"


def py_loc(pkg: Path) -> int:
    total = 0
    for f in pkg.rglob("*.py"):
        if "migrations" in f.parts or "__pycache__" in f.parts:
            continue
        total += sum(1 for _ in f.open(encoding="utf-8", errors="ignore"))
    return total


def route_count(pkg: Path) -> int:
    n = 0
    for f in pkg.rglob("*.py"):
        if "__pycache__" in f.parts:
            continue
        n += len(ROUTE_RE.findall(f.read_text(encoding="utf-8", errors="ignore")))
    return n


def migration_count(name: str) -> int:
    if not MIGR_DIR.exists():
        return 0
    return sum(1 for f in MIGR_DIR.glob("*.py") if name in f.name)


def fe_ui(page_dirs: list[str]) -> str:
    for d in page_dirs:
        page = FE_APP / d / "page.tsx"
        if not page.exists():
            continue
        src = page.read_text(encoding="utf-8", errors="ignore")
        if "FunnelBoard" in src:
            return "FunnelBoard"
        if "ModuleBoard" in src:
            return "ModuleBoard"
        return f"bespoke ({sum(1 for _ in page.open(encoding='utf-8', errors='ignore'))} loc)"
    return "—"


# фронт-страница(ы) каждого модуля (первая существующая определяет тип)
FE_MAP = {
    "sales": ["crm/deals", "erp/sales"],
    "procurement": ["erp/procurement"],
    "production": ["erp/production"],
    "wms": ["erp/wms"],
    "logistics": ["erp/logistics"],
    "finance": ["erp/finance"],
    "marketing": ["erp/marketing"],
    "service": ["erp/service"],
    "hr": ["erp/hr"],
}


def main() -> None:
    print(f"{'module':<12} {'loc':>5} {'routes':>7} {'migr':>5}  ui")
    print("-" * 60)
    for m in MODULES:
        pkg = ROOT / "modules" / m
        if not pkg.exists():
            print(f"{m:<12} {'—':>5} {'—':>7} {'—':>5}  (нет пакета)")
            continue
        print(f"{m:<12} {py_loc(pkg):>5} {route_count(pkg):>7} "
              f"{migration_count(m):>5}  {fe_ui(FE_MAP.get(m, []))}")
    total_migr = len(list(MIGR_DIR.glob('*.py'))) if MIGR_DIR.exists() else 0
    print("-" * 60)
    print(f"всего миграций: {total_migr}")
    print("\n% готовности — см. coordination/STATUS.md (правится вручную при сдвиге блока).")


if __name__ == "__main__":
    main()
