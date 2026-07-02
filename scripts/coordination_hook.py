#!/usr/bin/env python
"""Обмен информацией между сессиями на событиях git (commit / push).

Вызывается git-хуками из ``.githooks/`` (см. ``coordination/INFO-FLOW.md``).
Делает «нужные действия для обмена» автоматически, чтобы это не зависело от
дисциплины каждой сессии:

1. **Журнал** ``coordination/.activity.local.md`` (append-only, не трекается) —
   общий для всех worktree'ов флота на этой машине: «кто/что/когда сделал».
   Пишется в coordination/ ГЛАВНОГО worktree (через ``--git-common-dir``), поэтому
   виден и из linked-worktree воркеров.
2. **Флаги** — если коммит/пуш задел файл-хотспот, shared-kernel или добавил новое
   событие шины (`emit`/`subscribe`), печатает напоминание обновить
   ``coordination/DEPENDENCY-MAP.md`` (§2/§3/§5) и ``ACTIVE-SESSIONS.md``.

Контракт надёжности: скрипт НИКОГДА не валит git. Любая ошибка → тихий ``exit 0``.
Только stdlib. Кодировка — всегда UTF-8 (Windows + кириллица в subject'ах).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Windows-консоль = cp1251 → print() кириллицы/эмодзи (⛔/⚠) валит UnicodeEncodeError,
# который наш top-level except глотает в exit(0) → блок-гард молча не срабатывает (поймано
# при тесте amend-гарда). Принудительно UTF-8 с заменой, чтобы вывод НИКОГДА не падал.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # py3.7+
    except Exception:
        pass

# Файлы-хотспоты из DEPENDENCY-MAP §5 — касание = вероятный конфликт/контракт.
HOTSPOTS = {
    "config/settings.py",
    "config/modules.py",
    "core/services/__init__.py",
    "core/db/base.py",
    "core/domain/models.py",  # shared kernel (Sku/Counterparty/...)
    "core/runtime/access.py",
    "core/services/auth.py",
    "frontend/src/lib/api.ts",
    "tests/conftest.py",
}
SHARED_KERNEL = "core/domain/models.py"
MIGRATION_RE = re.compile(r"migrations/versions/.+\.py$")
# Новое межмодульное взаимодействие = добавлена строка с emit/subscribe ШИНЫ.
# Привязка к объекту шины (event_bus|core), иначе ловит любой .subscribe( (SSE-очередь/RxJS).
# ponytail: эвристика по тексту — может задеть закомменченный вызов шины; приемлемо для advisory.
EVENT_RE = re.compile(r"^\+(?!\+).*\b(?:event_bus|core)\.(?:emit|subscribe)\(", re.MULTILINE)
# Событие ищем ТОЛЬКО в коде — иначе доки/комменты с примером API дают ложный флаг.
CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx")
# Сдвиг указателя субмодуля в суперпроекте (git --raw): режим gitlink = 160000.
GITLINK_MODE = "160000"
RAW_RE = re.compile(r"^:(\d{6}) (\d{6}) ([0-9a-f]+) ([0-9a-f]+) ([A-Z])\t(.+)$")
LOG_NAME = ".activity.local.md"
LOG_HEADER = (
    "# Журнал активности флота (локальный, не трекается)\n"
    "# Пишется git-хуками автоматически. Сюда сессии смотрят «что сделано».\n"
    "# Канон обмена: coordination/INFO-FLOW.md\n\n"
)
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git «пустое дерево» — база diff для корневого коммита


def _git(*args: str) -> str:
    """Тихий git: возвращает stdout (UTF-8) или '' при любой ошибке."""
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,  # зависший git-child (index.lock у флота) не должен морозить commit/push
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # включая TimeoutExpired — хук остаётся неблокирующим
        return ""


def _alembic_heads() -> list[str]:
    """Головы alembic-цепочки = revision, на которые никто не ссылается down_revision'ом.
    Чистый python, БЕЗ запуска alembic (медленно/нужна БД). Скан по ФАЙЛАМ НА ДИСКЕ
    (linked-worktree-полосы пишут .py до stage — коллизия видна по диску). Каталог — от git toplevel."""
    top = _git("rev-parse", "--show-toplevel")
    migr = (Path(top) if top else Path.cwd()) / "migrations" / "versions"
    if not migr.is_dir():
        return []
    revs: set[str] = set()
    downs: set[str] = set()
    for f in migr.glob("*.py"):
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if m := re.search(r'^revision\s*=\s*["\']([^"\']+)', txt, re.M):
            revs.add(m.group(1))
        if d := re.search(r'^down_revision\s*=\s*["\']([^"\']+)', txt, re.M):
            downs.add(d.group(1))
    return sorted(revs - downs)


def _clean(s: str) -> str:
    """Убрать control/ANSI-байты из недоверенной строки (subject/ref/путь) перед
    записью в журнал и печатью — CR/ESC иначе портят строку лога в терминале."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", s)


def _coord_dir() -> Path | None:
    """coordination/ ГЛАВНОГО worktree (общий для linked-worktree'ов флота)."""
    common = _git("rev-parse", "--git-common-dir") or ".git"
    main_root = Path(os.path.abspath(common)).parent
    for base in (main_root, Path.cwd()):
        if (base / "coordination").is_dir():
            return base / "coordination"
    return None


def _is_code_path(p: str) -> bool:
    """Кодовый файл, по которому ловим событие шины: .py/.ts/..., но НЕ доку и НЕ тесты
    (тесты не вводят межмодульных контрактов)."""
    if p == "/dev/null" or not p.endswith(CODE_EXT):
        return False
    base = p.rsplit("/", 1)[-1]
    if "/tests/" in f"/{p}" or base.startswith("test_") or base.endswith(
        ("_test.py", ".test.ts", ".test.tsx", ".test.js")
    ):
        return False
    return True


def _code_added_lines(diff: str) -> str:
    """Добавленные строки только из КОДОВЫХ файлов (без доков/тестов) из unified-diff.

    Чтобы пример вызова шины в доке/комменте/тесте не считался «новым событием».
    Префикс пути (`b/`, `w/`, … или его отсутствие при diff.noprefix) терпим.
    """
    out, in_code = [], False
    for line in diff.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            if len(p) > 1 and p[1] == "/" and p[0].isalpha():
                p = p[2:]  # снять одно-буквенный префикс diff (b/, w/, i/, …)
            in_code = _is_code_path(p)
        elif in_code and line.startswith("+") and not line.startswith("+++"):
            out.append(line)
    return "\n".join(out)


def _flags(files: list[str], diff: str) -> list[str]:
    """Поднять флаги обмена по списку файлов и diff'у."""
    norm = {f.replace("\\", "/") for f in files if f}
    flags: list[str] = []
    hot = sorted(norm & HOTSPOTS)
    if hot:
        flags.append("хотспот: " + ", ".join(hot))
    if SHARED_KERNEL in norm:
        flags.append("shared-kernel (ломает все модули — §3)")
    if any(MIGRATION_RE.search(f) for f in norm):
        flags.append("миграция (сверь единственный head — §5)")
    code = _code_added_lines(diff)
    if code and EVENT_RE.search(code):
        flags.append("новое событие шины (обнови граф §2)")
        if "coordination/DEPENDENCY-MAP.md" not in norm:
            flags.append("⚠ событие добавлено, но DEPENDENCY-MAP не тронут")
    return flags


def _append(coord: Path, line: str) -> None:
    log = coord / LOG_NAME
    try:
        # 'a' создаёт файл без усечения → нет TOCTOU-гонки заголовка между воркерами.
        with log.open("a", encoding="utf-8") as fh:  # ponytail: построчный append — гонки маловероятны при низкой конкуренции
            if fh.tell() == 0:
                fh.write(LOG_HEADER)
            fh.write(line + "\n")
    except Exception:
        pass


def _report(flags: list[str]) -> None:
    if flags:
        print("[coordination] флаги обмена — обнови coordination/ (DEPENDENCY-MAP §2/§3/§5, ACTIVE-SESSIONS):")
        for f in flags:
            print(f"  • {f}")


def _submodule_bumps(raw: str) -> list[tuple[str, str, str, str]]:
    """Из `git show/diff --raw` достать сдвиги указателей субмодулей (gitlink 160000)."""
    out = []
    for line in raw.splitlines():
        m = RAW_RE.match(line)
        if m and GITLINK_MODE in (m.group(1), m.group(2)):
            old, new, status, path = m.group(3), m.group(4), m.group(5), m.group(6)
            out.append((status, old, new, path.replace("\\", "/")))
    return out


def _log_submodule_bumps(coord: Path, raw: str, ts: str) -> list[str]:
    """Записать продвижение каждого субмодуля; вернуть его ВНУТРЕННИЕ флаги.

    Хук суперпроекта НЕ срабатывает на коммит ВНУТРИ субмодуля (отдельный репо), но
    срабатывает на сдвиг указателя — канонический сигнал «субмодуль продвинулся»
    (INFO-FLOW план Б). Здесь заглядываем внутрь субмодуля по его object store, чтобы
    поймать новые события/хотспоты, которых в дельте указателя (old→new SHA) не видно.
    """
    zero = "0" * 40
    extra: list[str] = []
    for status, old, new, path in _submodule_bumps(raw):
        disp = _clean(path)
        if status == "D" or new == zero:
            _append(coord, f"- {ts} ·   └ submodule {disp}: указатель удалён")
            continue
        if old == zero:  # субмодуль добавлен — это не дельта, всю историю не считаем
            _append(coord, f"- {ts} ·   └ submodule {disp}: добавлен на {new[:7]}")
            continue
        rng = f"{old}..{new}"
        commits = [c for c in _git("-C", path, "log", "--oneline", "--no-color", "-n", "20", rng).splitlines() if c]
        diff = _git("-C", path, "diff", "--no-color", "-U0", rng)
        names = [f for f in _git("-C", path, "diff", "--name-only", rng).splitlines() if f]
        sflags = _flags(names, diff)
        tip = _clean(commits[0]) if commits else f"{old[:7]}→{new[:7]}"
        suffix = (" · ⚠ " + " | ".join(sflags)) if sflags else ""
        _append(coord, f"- {ts} ·   └ submodule {disp}: {len(commits)} нов. коммит(ов) · {tip}{suffix}")
        extra += [f"{disp} → {s}" for s in sflags]
    return extra


# Общие ветки флота: на них несколько сессий коммитят разом → HEAD дрейфует под тобой,
# поэтому amend/reset/rebase бьют по ЧУЖОМУ коммиту (реальная авария 2026-06-27).
SHARED_BRANCHES = {"main", "sales-2.0-redesign", "theme/dark-mode-cd"}


def pre_commit(coord: Path) -> int:
    """Гард ПЕРЕД коммитом. БЛОК (return 1) только на объективной аварии: staged-миграция при
    >1 alembic head (dual-head → падёт `alembic upgrade` в проде, деньги/безопасность). Обход
    (осознанно, напр. перед мержем-починкой цепочки): AIOS_ALLOW_MULTI_HEADS=1. Остальное —
    advisory (return 0): предупреждения о хотспотах/shared-kernel/миграции на общей ветке.
    """
    norm = {f.replace("\\", "/")
            for f in _git("diff", "--cached", "--name-only").splitlines() if f}
    # БЛОК: staged-миграция при нескольких головах цепочки = два head (на любой ветке).
    if any(MIGRATION_RE.search(f) for f in norm):
        heads = _alembic_heads()
        if len(heads) > 1 and os.environ.get("AIOS_ALLOW_MULTI_HEADS") != "1":
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            print(f"[coordination] ⛔ alembic multiple heads ({len(heads)}): {', '.join(heads)}. "
                  "Коммит миграции заблокирован — два head ломают `alembic upgrade` в проде. "
                  "Бери номер через scripts/next_migration.py (down_revision = ОДИН head), или "
                  "почини цепочку. Обход (осознанно): AIOS_ALLOW_MULTI_HEADS=1 git commit …")
            _append(coord, f"- {ts} · commit BLOCKED · migration guard: multiple heads ({', '.join(heads)})")
            return 1
    # ADVISORY: риски общей ветки (не блокируем — флага достаточно).
    branch = _clean(_git("rev-parse", "--abbrev-ref", "HEAD"))
    if branch not in SHARED_BRANCHES:
        return 0
    hot = sorted(norm & HOTSPOTS)
    if hot:
        print(f"[coordination] ⚠ общая ветка '{branch}': тронуты хотспоты: {', '.join(hot)}. "
              "Сверься с ACTIVE-SESSIONS «Хотспоты» — не держит ли их другая сессия.")
    if SHARED_KERNEL in norm:
        print("[coordination] ⚠ shared-kernel (core/domain/models.py) — ломает все модули "
              "(DEPENDENCY-MAP §3).")
    if any(MIGRATION_RE.search(f) for f in norm):
        print("[coordination] ⚠ миграция — впиши номер в ACTIVE-SESSIONS «Счётчик миграций», "
              "сверь единственный head (§5).")
    return 0


def prepare_commit_msg(coord: Path, source: str, sha: str) -> int:
    """Гард ПЕРЕД редактированием сообщения. git зовёт с source='commit' и sha при ``--amend`` —
    единственный надёжный сигнал amend в хуках. На ОБЩЕЙ ветке amend = блок (затрёт чужой коммит,
    авария 2026-06-27). Обход (свой коммит, точно знаешь что делаешь): ``AIOS_ALLOW_AMEND=1``.
    """
    if source != "commit" or not sha:  # не amend (обычный/merge/squash/template коммит)
        return 0
    if os.environ.get("AIOS_ALLOW_AMEND") == "1":
        return 0
    branch = _clean(_git("rev-parse", "--abbrev-ref", "HEAD"))
    if branch not in SHARED_BRANCHES:
        return 0
    print(f"[coordination] ⛔ amend на ОБЩЕЙ ветке '{branch}' заблокирован: HEAD мог сдвинуть "
          "другая сессия — заамендишь ЧУЖОЙ коммит (так и случилось 2026-06-27). "
          "Сделай НОВЫЙ коммит, или работай в своей ветке/worktree. "
          "Если уверен (HEAD точно твой): AIOS_ALLOW_AMEND=1 git commit --amend …")
    return 1


def on_commit(coord: Path) -> None:
    sha = _git("rev-parse", "--short", "HEAD")
    subject = _clean(_git("log", "-1", "--pretty=%s"))
    branch = _clean(_git("rev-parse", "--abbrev-ref", "HEAD"))
    files = [f for f in _git("show", "--name-only", "--pretty=format:", "HEAD").splitlines() if f]
    diff = _git("show", "HEAD", "-U0", "--no-color")
    flags = _flags(files, diff)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    suffix = (" · ⚠ " + " | ".join(flags)) if flags else ""
    _append(coord, f'- {ts} · commit · {branch} {sha} · "{subject}" · {len(files)} файл(ов){suffix}')
    print(f"[coordination] записано в журнал: commit {sha} ({len(files)} файл.)")
    raw = _git("show", "--raw", "--no-abbrev", "--no-color", "--format=", "HEAD")
    flags += _log_submodule_bumps(coord, raw, ts)  # сдвиг указателя субмодуля → заглянуть внутрь
    _report(flags)


def on_push(coord: Path, remote: str) -> int:
    """Лог пуша + БЛОК изоляции: прямой push в ОБЩУЮ ветку с >1 коммита утащит чужие
    незапушенные коммиты. Блок (return 1), обход AIOS_ALLOW_PUSH=1. Lane-ветки (не общие) —
    пушатся свободно. fail-open сохранён top-level except'ом в main."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    zero = "0" * 40
    all_files: set[str] = set()
    diffs: list[str] = []
    lines_logged = 0
    blocked: list[str] = []  # общие ветки, куда летит >1 коммита
    for line in sys.stdin:
        parts = line.split()
        if len(parts) < 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = parts[:4]
        if local_sha == zero:  # удаление ветки
            continue
        if remote_sha == zero:  # новая ветка: дельта = чего ещё нет ни на одном remote
            newrevs = [c for c in _git("rev-list", local_sha, "--not", "--remotes").splitlines() if c]
            n = len(newrevs)
            rng = f"{_git('rev-parse', newrevs[-1] + '^') or EMPTY_TREE}..{local_sha}" if newrevs else None
        else:  # обновление ветки: точный диапазон remote→local
            rng = f"{remote_sha}..{local_sha}"
            n = len([c for c in _git("log", "--pretty=%h", rng).splitlines() if c])
        if rng:
            for f in _git("diff", "--name-only", rng).splitlines():
                if f:
                    all_files.add(f)
            diffs.append(_git("diff", rng, "-U0", "--no-color"))
        dest = _clean(remote_ref.split("/")[-1])
        warn = " · ⚠ >1 коммита — пушь только свою полосу" if n > 1 else ""
        _append(coord, f"- {ts} · push → {remote}/{dest} · {n} коммит(ов){warn}")
        print(f"[coordination] push → {remote}/{dest}: {n} коммит(ов)")
        lines_logged += 1
        if dest in SHARED_BRANCHES and n > 1:
            blocked.append(f"{dest} ({n} коммитов)")
    if not lines_logged:
        return 0
    _report(_flags(sorted(all_files), "\n".join(diffs)))
    if blocked and os.environ.get("AIOS_ALLOW_PUSH") != "1":
        print(f"[coordination] ⛔ прямой push в общую ветку с >1 коммита: {', '.join(blocked)}. "
              "Утащишь чужие незапушенные коммиты. Пушь ТОЛЬКО свой — cherry-pick на чистую ветку "
              "от origin (scripts/lane_worktree.py). Обход (осознанно): AIOS_ALLOW_PUSH=1 git push …")
        _append(coord, f"- {ts} · push BLOCKED · isolation: >1 коммита в общую ветку ({', '.join(blocked)})")
        return 1
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    coord = _coord_dir()
    if coord is None:
        return 0
    if mode == "pre-commit":
        return pre_commit(coord)
    if mode == "prepare-commit-msg":
        # git зовёт: prepare-commit-msg <msg-file> [<source> [<sha>]]
        return prepare_commit_msg(coord, sys.argv[3] if len(sys.argv) > 3 else "",
                                  sys.argv[4] if len(sys.argv) > 4 else "")
    if mode == "post-commit":
        on_commit(coord)
    elif mode == "pre-push":
        return on_push(coord, sys.argv[2] if len(sys.argv) > 2 else "origin")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # хук НИКОГДА не валит git
