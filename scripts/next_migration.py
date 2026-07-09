#!/usr/bin/env python3
"""scripts/next_migration.py — АТОМАРНОЕ взятие номера миграции (анти-dual-head).

Проблема: «взять номер» = read head → вписать в markdown → создать файл — 3 шага без
атомарности. Две полосы читают один head → две миграции с одним down_revision → Alembic
multiple heads → `upgrade` падает в проде (приоритет #1-2, деньги/безопасность).

Решение: под файл-локом считаем реальный head (revision без ссылок) + уже зарезервированные
номера, выдаём следующий и СРАЗУ резервируем в `coordination/.migration-reservations.local`.
Параллельный вызов увидит резерв и возьмёт следующий — без коллизии.

  python scripts/next_migration.py --peek                 показать head/next, НЕ резервировать
  python scripts/next_migration.py <lane> "<описание>"    зарезервировать и напечатать (rev, down_revision)

Резерв — НЕ файл миграции; после написания `NNNN_*.py` резерв становится историей.
Истина — этот лок + реальные файлы; markdown-счётчик в ACTIVE-SESSIONS остаётся для ГЛАЗ (ведёт координатор).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
MIGR = ROOT / "migrations" / "versions"
LOCK = ROOT / "coordination" / ".migration.lock"
RESV = ROOT / "coordination" / ".migration-reservations.local"
NUM_RE = re.compile(r"^(\d{4})")


def _scan() -> tuple[set[str], set[str]]:
    revs, downs = set(), set()
    for f in MIGR.glob("*.py"):
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if m := re.search(r'^revision\s*=\s*["\']([^"\']+)', txt, re.M):
            revs.add(m.group(1))
        if d := re.search(r'^down_revision\s*=\s*["\']([^"\']+)', txt, re.M):
            downs.add(d.group(1))
    return revs, downs


def _nums(strings) -> list[int]:
    out = []
    for s in strings:
        if m := NUM_RE.match(str(s)):
            out.append(int(m.group(1)))
    return out


def _reservations() -> list[tuple[int, str]]:
    if not RESV.exists():
        return []
    res = []
    for ln in RESV.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = ln.split("\t")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            res.append((int(parts[0]), parts[1]))
    return res


def _head(revs: set[str], downs: set[str], reservations: list[tuple[int, str]]) -> str:
    """Tip цепочки: последний резерв ИЛИ alembic-head (revision без ссылок)."""
    if reservations:
        return f"{max(n for n, _ in reservations):04d}"
    heads = sorted(revs - downs)
    return heads[-1] if heads else "0000"


def _release_lock() -> None:
    for _ in range(5):
        try:
            LOCK.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.1)
        except OSError:
            return


def _acquire(timeout: float = 5.0) -> bool:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            try:  # снять протухший лок (>30с)
                if time.time() - LOCK.stat().st_mtime > 30:
                    _release_lock()
                    continue
            except OSError:
                pass
            time.sleep(0.05)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Атомарное взятие номера миграции")
    ap.add_argument("lane", nargs="?", help="полоса (для резерва)")
    ap.add_argument("desc", nargs="?", default="", help="описание миграции")
    ap.add_argument("--peek", action="store_true", help="показать head/next без резерва")
    args = ap.parse_args(argv)

    if not _acquire():
        print("next_migration: не взял лок (занят) — повтори через секунду", file=sys.stderr)
        return 1
    try:
        revs, downs = _scan()
        resv = _reservations()
        head = _head(revs, downs, resv)
        taken = _nums(revs) + [n for n, _ in resv]
        nxt = (max(taken) + 1) if taken else 1
        rev = f"{nxt:04d}"

        if args.peek or not args.lane:
            heads = sorted(revs - downs)
            print(f"alembic head(ы): {', '.join(heads) or '—'}")
            print(f"резервы: {', '.join(f'{n:04d}' for n, _ in resv) or '—'}")
            print(f"следующий свободный: {rev} (down_revision={head})")
            if not args.lane and not args.peek:
                print("\n(чтобы зарезервировать: next_migration.py <lane> \"<описание>\")")
            return 0

        when = datetime.now().strftime("%Y-%m-%d %H:%M")
        with RESV.open("a", encoding="utf-8") as f:
            f.write(f"{rev}\t{head}\t{args.lane}\t{args.desc}\t{when}\n")
        print(f"ЗАРЕЗЕРВИРОВАНО: revision={rev}  down_revision={head}  (полоса {args.lane})")
        print(f'Создай migrations/versions/{rev}_*.py с revision="{rev}", down_revision="{head}".')
        print("Пинг координатору вписать в ACTIVE-SESSIONS «Счётчик миграций» (он ведёт markdown).")
        return 0
    finally:
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
