#!/usr/bin/env python3
"""claude_pushlog_hook.py — PostToolUse(Bash): авто-журнал пушей для координации сессий.

Когда Claude выполняет `git push` (в любой ветке/worktree), хук дописывает строку в общий
журнал coordination/PUSH-LOG.md: дата, ветка, последний коммит (hash + subject), изменённые
файлы. Другие параллельные сессии читают этот журнал как ленту «кто что только что залил» —
дополняет coordination/ACTIVE-SESSIONS.md (полосы) и сам origin (код).

Зачем постфактум, а не блокировка: не мешает быстрым пушам, нет ложных срабатываний, не зависит
от того, «вспомнит» ли Claude отметиться. Журнал НЕ коммитится (как ACTIVE-SESSIONS) — общий
worktree, виден всем локально; коммит = append-конфликты.

Философия: fail-open. Любая ошибка/таймаут → exit 0 (хук никогда не ломает работу и не блокирует).
Регистрация — в .claude/settings.json, событие PostToolUse, matcher Bash|PowerShell.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

TIMEOUT = 15
LOG_REL = "coordination/PUSH-LOG.md"
MAX_FILES = 12  # не раздувать строку журнала


def _project_dir() -> Path:
    """Каталог проекта. Хук ЛЕЖИТ в проекте, который обслуживает, поэтому его собственное
    расположение — источник истины. CLAUDE_PROJECT_DIR принимаем, только если он указывает на
    проект (есть coordination/) — это случай worktree воркера. Сессия, запущенная из
    каталога-родителя, отдаёт в этой переменной путь родителя: раньше хуки искали бы там
    coordination/ и не находили, а pushlog писал бы PUSH-LOG.md в чужой каталог."""
    here = Path(__file__).resolve().parent
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        p = Path(env)
        try:
            if p.resolve() == here or (p / "coordination").is_dir():
                return p
        except OSError:
            pass
    return here


def _read_stdin() -> str:
    if sys.stdin.isatty():
        return ""
    try:  # utf-8-sig снимает BOM, не ломает кириллицу в путях (Windows)
        return sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return ""


def _session_id(data: dict) -> str:
    sid = re.sub(r"[^a-zA-Z0-9]", "", str(data.get("session_id") or ""))
    return sid[:8] or "nosess"


def _git(cwd: Path, *args: str) -> str:
    """git в переданном каталоге; пусто при любой ошибке (fail-open)."""
    try:
        r = subprocess.run(
            ["git", *args], cwd=str(cwd),
            capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _tool_cwd(data: dict, fallback: Path) -> Path:
    """Каталог, где реально выполнялась команда (worktree-сессии) — из payload PostToolUse.

    Иначе `git log -1 HEAD` в главном дереве вернёт ЧУЖОЙ коммит для worktree-пуша:
    журнал PUSH-LOG.md (лента координации флота) уедет неверной строкой.
    """
    cwd = data.get("cwd")
    if cwd:
        p = Path(str(cwd))
        if p.is_dir():
            return p
    return fallback


def _bash_command(data: dict) -> str:
    ti = data.get("tool_input")
    if isinstance(ti, dict):
        return str(ti.get("command") or "")
    return ""


def _push_succeeded(data: dict) -> bool:
    """PostToolUse выстреливает и при неуспехе — отсеиваем явные провалы по tool_response."""
    resp = data.get("tool_response")
    text = ""
    if isinstance(resp, dict):
        text = str(resp.get("stdout", "")) + str(resp.get("stderr", "")) + str(resp.get("output", ""))
    elif isinstance(resp, str):
        text = resp
    low = text.lower()
    if "rejected" in low or "failed to push" in low or "error:" in low:
        return False
    return True  # неясно → пишем (журнал лучше с лишней строкой, чем с пропуском)


def _resp_text(data: dict) -> str:
    resp = data.get("tool_response")
    if isinstance(resp, dict):
        return str(resp.get("stdout", "")) + str(resp.get("stderr", "")) + str(resp.get("output", ""))
    return resp if isinstance(resp, str) else ""


def _pushed_ref(text: str) -> tuple[str, str]:
    """Из вывода `git push` вытащить (sha запушенного коммита, целевая ветка).

    Точность для worktree-пушей: рабочий HEAD проекта может отставать, а вывод push
    содержит реальный диапазон ``old..new  HEAD -> ветка`` (или ``* [new branch] src -> ветка``).
    Возвращает ('', '') если не распарсилось — тогда падаем на локальный HEAD.
    """
    sha = branch = ""
    m = re.search(r"\b[0-9a-f]{6,40}\.\.([0-9a-f]{6,40})\b", text)  # fast-forward old..new
    if m:
        sha = m.group(1)
    m2 = re.search(r"->\s+(\S+)", text)  # "HEAD -> ветка" / "src -> dst"
    if m2:
        branch = m2.group(1).strip()
    return sha, branch


def main() -> int:
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    raw = _read_stdin()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0

    # PowerShell — штатный шелл проекта на Windows: команды в CLAUDE.md/PLAYBOOK записаны
    # именно в нём. Пока проверка была Bash-only, коммиты и пуши через PowerShell не попадали
    # ни в PUSH-LOG.md, ни во впрыск «свежие пуши» — дыра в самой координации флота.
    if (data.get("tool_name") or "") not in ("Bash", "PowerShell"):
        return 0
    cmd = _bash_command(data)
    if "git push" not in cmd:
        return 0
    if not _push_succeeded(data):
        return 0

    proj = _project_dir()
    # git-вызовы — в реальном cwd команды (worktree), путь к самому журналу — всегда проектный
    # (иначе PUSH-LOG.md расползётся по .claude/worktrees/*).
    git_cwd = _tool_cwd(data, proj)

    # Реальный запушенный коммит — из вывода push (точно даже при worktree-пуше, когда рабочий
    # HEAD отстаёт). Если sha не распарсился или недоступен локально → падаем на рабочий HEAD.
    pushed_sha, pushed_branch = _pushed_ref(_resp_text(data))
    ref = "HEAD"
    if pushed_sha and _git(git_cwd, "rev-parse", "--verify", "--quiet", pushed_sha + "^{commit}"):
        ref = pushed_sha  # коммит есть в локальном репо — логируем именно его

    # hash + subject + дата одним вызовом: раньше на тот же ref шло два отдельных `git log -1`,
    # различавшихся только --format (лишний спавн процесса на каждый пуш).
    # Дату берём из git — в хуке нет надёжного локального времени без побочек.
    head = _git(git_cwd, "log", "-1", "--format=%h\t%s\t%ci", ref)
    if not head:
        return 0  # нечего записать — не шумим
    files = _git(git_cwd, "show", "--name-only", "--format=", ref)
    branch = pushed_branch or _git(git_cwd, "rev-parse", "--abbrev-ref", "HEAD")

    h, _, rest = head.partition("\t")
    subj, _, iso = rest.rpartition("\t")  # subject может содержать \t — режем справа
    when = iso[:16] or "—"
    flist = [f for f in files.splitlines() if f.strip()]
    shown = ", ".join(flist[:MAX_FILES])
    if len(flist) > MAX_FILES:
        shown += f" … (+{len(flist) - MAX_FILES})"

    sid = _session_id(data)
    line = f"- `{when}` · сессия `{sid}` · ветка `{branch or '?'}` · **{h}** {subj}\n  файлы: {shown or '—'}\n"

    log = proj / LOG_REL
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        if not log.exists():
            log.write_text(
                "# Журнал пушей — лента координации сессий\n\n"
                "> Авто-заполняется хуком `claude_pushlog_hook.py` после каждого `git push`.\n"
                "> Другие параллельные сессии читают это как ленту «кто что залил». **НЕ коммитится.**\n"
                "> Полосы и резервы — в [ACTIVE-SESSIONS.md](ACTIVE-SESSIONS.md).\n\n",
                encoding="utf-8",
            )
        with log.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        return 0  # журнал вспомогательный — не мешаем
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # fail-open: хук никогда не должен ронять ход сессии
