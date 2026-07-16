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
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = [
    "sales", "leads", "procurement", "production", "wms", "logistics",
    "finance", "marketing", "service", "hr",
]
# Токен имени миграций модуля, если он не совпадает с именем пакета. Миграции лидов
# исторически названы префиксом `lead` (0087_leads_init, 0091-0101_lead_*), не `leads`.
MIGR_TOKENS = {"leads": "lead"}
ROUTE_RE = re.compile(r"@router\.(get|post|put|patch|delete)\b")
MIGR_DIR = ROOT / "migrations" / "versions"
FE_APP = ROOT / "frontend" / "src" / "app"
STATUS_FILE = ROOT / "coordination" / "STATUS.md"
MARK_START = "<!-- READINESS:AUTO — авто-блок scripts/readiness.py --write, не редактируй вручную -->"
MARK_END = "<!-- /READINESS:AUTO -->"
# Второй авто-блок STATUS.md — снимок координации флота (git + голова миграций). Был сиротой:
# маркеры в файле лежали с 2026-06-30, а писать их было НЕКОМУ → координатор две недели читал
# протухший HEAD/ahead/голову как свежие. Теперь рендерится здесь же, одной командой.
COORD_START = "<!-- COORD:AUTO — снимок координации флота, scripts/readiness.py --write -->"
COORD_END = "<!-- /COORD:AUTO -->"


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
    token = MIGR_TOKENS.get(name, name)
    return sum(1 for f in MIGR_DIR.glob("*.py") if token in f.name)


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
    "leads": ["crm/leads"],
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


def _git(*args: str) -> str:
    """Вывод git одной строкой; `""` если git недоступен/упал.

    Fail-open намеренно: скрипт гоняется и из хуков/крона, где git может быть недоступен
    (см. auto-retro). Пустая строка → в блоке честный `?`, а не враньё и не падение.

    ⚠️ `encoding="utf-8"` обязателен: на Windows `text=True` декодирует вывод git локалью
    (cp1251) → русские сообщения коммитов превращаются в кракозябры прямо в STATUS.md.
    """
    try:
        r = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
    except Exception:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _alembic_heads() -> list[str]:
    """Головы цепочки Alembic = ревизии, на которые никто не ссылается как `down_revision`.

    >1 головы = форк: `alembic upgrade head` падает в проде (PLATFORM #1-2 — деньги/безопасность),
    поэтому блок подсвечивает это красным. Та же логика, что у `next_migration.py::_scan/_head`
    (там она под локом-аллокатором; здесь — только чтение для снимка).
    """
    revs: set[str] = set()
    downs: set[str] = set()
    for f in sorted(MIGR_DIR.glob("*.py")) if MIGR_DIR.is_dir() else []:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        if m := re.search(r'^revision\s*=\s*["\']([^"\']+)', txt, re.M):
            revs.add(m.group(1))
        if d := re.search(r'^down_revision\s*=\s*["\']([^"\']+)', txt, re.M):
            downs.add(d.group(1))
    return sorted(revs - downs)


def _coord_block(stamp: str) -> str:
    """Снимок координации: git-состояние ветки + голова миграций.

    Хвосты REPORTS/PUSH-LOG/.activity сюда НЕ дублируются — их впрыскивает SessionStart-хук
    (`claude_awareness_hook.py`) прямо в контекст. Здесь только то, чего больше нигде нет.
    """
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    head = _git("log", "-1", "--oneline") or "?"
    dirty = len(_git("status", "--porcelain").splitlines())
    # `A...B --left-right --count` → "<позади> <впереди>" относительно origin.
    counts = _git("rev-list", "--left-right", "--count", f"origin/{branch}...HEAD").split()
    behind, ahead = (counts + ["?", "?"])[:2]
    heads = _alembic_heads()
    if not heads:
        head_line = "?"
    elif len(heads) == 1:
        head_line = f"**{heads[0]}**"
    else:
        head_line = f"🔴 **ФОРК: {len(heads)} головы** — {', '.join(heads)} (upgrade упадёт)"
    return "\n".join([
        COORD_START,
        f"### Координация флота (авто, {stamp})",
        "",
        f"- Ветка `{branch}` · HEAD `{head}`",
        f"- Против `origin/{branch}`: впереди **{ahead}** · позади **{behind}** · "
        f"незакоммичено файлов **{dirty}**",
        f"- Голова миграций (alembic): {head_line}",
        "",
        "> Доклады полос / пуши / активность здесь НЕ дублируются — их впрыскивает SessionStart-хук.",
        "> «Впереди» после cherry-pick-пуша может быть дублями старых хешей: что реально НЕ в origin —",
        "> `git cherry -v origin/<ветка>` (строки `+`).",
        COORD_END,
    ])


def _write_status(block: str, start: str, end: str) -> str:
    if not STATUS_FILE.is_file():
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(block + "\n", encoding="utf-8")
        return "создан"
    text = STATUS_FILE.read_text(encoding="utf-8")
    if start in text and end in text:
        pre = text[: text.index(start)]
        post = text[text.index(end) + len(end):]
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
        verb = _write_status(_auto_block(rows, total_migr, stamp), MARK_START, MARK_END)
        print(f"\nSTATUS.md: авто-блок {verb} ({stamp}); курируемые % не тронуты.")
        cverb = _write_status(_coord_block(stamp), COORD_START, COORD_END)
        print(f"STATUS.md: блок координации флота {cverb} ({stamp}).")
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
