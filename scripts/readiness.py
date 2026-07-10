"""Сканер готовности модулей — объективные метрики без ручного обхода.

Запуск:
  python scripts/readiness.py            печатает таблицу loc / роуты / миграции / тип фронта
  python scripts/readiness.py --write    то же + обновляет АВТО-БЛОК в coordination/STATUS.md

`--write` НЕ трогает курируемую таблицу с субъективными %: он лишь вставляет/заменяет
фенсед-блок между маркерами `<!-- READINESS:AUTO -->` … `<!-- /READINESS:AUTO -->`
(в первый раз — дописывает в конец файла). Субъективную оценку по-прежнему правишь руками,
сверяясь со свежими объективными числами в авто-блоке.

Цель — дать свежие цифры одной командой, чтобы не сканировать дерево вручную каждый раз.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = [
    "sales", "procurement", "production", "wms", "logistics",
    "finance", "marketing", "service", "hr",
]
ROUTE_RE = re.compile(r"@router\.(get|post|put|patch|delete)\b")
MIGR_DIR = ROOT / "migrations" / "versions"
FE_APP = ROOT / "frontend" / "src" / "app"
STATUS_FILE = ROOT / "coordination" / "STATUS.md"
MARK_START = "<!-- READINESS:AUTO — авто-блок scripts/readiness.py --write, не редактируй вручную -->"
MARK_END = "<!-- /READINESS:AUTO -->"


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


def _rows() -> list[tuple]:
    rows: list[tuple] = []
    for m in MODULES:
        pkg = ROOT / "modules" / m
        if not pkg.exists():
            rows.append((m, "—", "—", "—", "(нет пакета)"))
        else:
            rows.append((m, py_loc(pkg), route_count(pkg),
                         migration_count(m), fe_ui(FE_MAP.get(m, []))))
    return rows


def _auto_block(rows: list[tuple], total_migr: int, stamp: str) -> str:
    lines = [
        MARK_START,
        f"### Объективные метрики (авто, обновлено {stamp})",
        "",
        "Свежие цифры из кода: loc (без миграций) · роуты · миграции модуля · тип фронта.",
        "Таблица с **%** выше — курируемая вручную; сверяй её с этими числами.",
        "",
        "| пакет | loc | роуты | мигр | ui |",
        "|---|---:|---:|---:|---|",
    ]
    lines += [f"| `{m}` | {loc} | {routes} | {migr} | {ui} |"
              for m, loc, routes, migr, ui in rows]
    lines += [f"| **всего миграций** | | | **{total_migr}** | |", "", MARK_END]
    return "\n".join(lines)


def _write_status(block: str) -> str:
    if not STATUS_FILE.is_file():
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(block + "\n", encoding="utf-8")
        return "создан"
    text = STATUS_FILE.read_text(encoding="utf-8")
    if MARK_START in text and MARK_END in text:
        pre = text[: text.index(MARK_START)]
        post = text[text.index(MARK_END) + len(MARK_END):]
        new, verb = pre + block + post, "обновлён"
    else:
        new, verb = text.rstrip() + "\n\n" + block + "\n", "дописан"
    STATUS_FILE.write_text(new, encoding="utf-8")
    return verb


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Сканер готовности модулей")
    ap.add_argument("--write", action="store_true",
                    help="обновить авто-блок в coordination/STATUS.md (курируемое не трогает)")
    args = ap.parse_args(argv)

    rows = _rows()
    total_migr = len(list(MIGR_DIR.glob("*.py"))) if MIGR_DIR.exists() else 0

    print(f"{'module':<12} {'loc':>5} {'routes':>7} {'migr':>5}  ui")
    print("-" * 60)
    for m, loc, routes, migr, ui in rows:
        print(f"{m:<12} {str(loc):>5} {str(routes):>7} {str(migr):>5}  {ui}")
    print("-" * 60)
    print(f"всего миграций: {total_migr}")

    if args.write:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        verb = _write_status(_auto_block(rows, total_migr, stamp))
        print(f"\nSTATUS.md: авто-блок {verb} ({stamp}); курируемые % не тронуты.")
        try:  # заодно освежаем HTML-кокпит; fail-open — битый рендер не рушит readiness
            import fleet_dashboard  # noqa: PLC0415  — тот же scripts/-каталог
            fleet_dashboard.main()
        except Exception as exc:  # pragma: no cover
            print(f"(fleet-dashboard пропущен: {exc})")
    else:
        print("\n% готовности — см. coordination/STATUS.md (правится вручную). "
              "Свежий авто-блок: readiness.py --write.")


if __name__ == "__main__":
    main()
