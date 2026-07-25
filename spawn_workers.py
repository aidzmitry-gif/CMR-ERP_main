#!/usr/bin/env python3
"""spawn_workers.py — Windows orchestrator for parallel Claude Code workers.

Rewritten for Windows 11 + PowerShell + this project (CRM ERP / AI-First OS)
from a macOS original (job_ghost_stalker, Terminal.app + osascript + GNU screen).

PATTERN (worktree-orchestrator):
  The orchestrator splits one big task into small scoped sub-tasks. For each
  worker it creates a git worktree + branch, primes a first-message (the
  karpathy-guidelines / worker-engineering-standards contract + the worker's
  scope), and launches `claude` in its own Windows Terminal window. It then
  observes progress by reading the worker's JSONL transcript (cross-platform,
  under ~/.claude/projects/<slug>/) and finally integrates each finished
  branch back into the base branch.

COMMANDS
  spawn <name>...        create worktree (if missing) + launch worker window(s)
  status [<name>...]     status table across workers (git state + transcript)
  tail <name> [-n 20]    recent assistant/tool entries from a worker transcript
  integrate <name>       merge worker branch -> base branch + smoke + report
  cleanup [<name>...]    retire fully-merged workers (remove worktree + branch)
  health                 preflight: claude CLI, git, venv, base branch, dirs
  list                   known workers (first-msg present)

CONVENTION
  first-message:  coordination/first-msgs/<name>.md   (the task — you write it)
  scope (opt):    coordination/<name>-scope.md         (LOOP CONTRACT etc.)
  worktree:       ../crm-worker-<name>/                 (auto-created from base)
  branch:         <name>
  status file:    coordination/<name>-status.md         (worker writes it)
  state:          coordination/.workers-state.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ─── config / paths ──────────────────────────────────────────────────────────


# This script lives in the repo root. Resolve from __file__ (NOT via
# `git rev-parse --show-toplevel`): on a Russian-locale Windows, git emits
# UTF-8 paths that subprocess decodes with cp1251, mojibaking the Cyrillic
# "Сlaude ... проект" path -> an invalid REPO_ROOT.
REPO_ROOT = Path(__file__).resolve().parent
WORKTREE_PARENT = REPO_ROOT.parent
WORKTREE_PREFIX = "crm-worker-"
BASE_BRANCH = os.environ.get("WORKER_BASE_BRANCH", "main")

COORD_DIR = REPO_ROOT / "coordination"
FIRST_MSG_DIR = COORD_DIR / "first-msgs"
PROMPT_DIR = COORD_DIR / ".worker-prompts"
LAUNCHER_DIR = COORD_DIR / ".worker-launchers"
PID_DIR = COORD_DIR / ".worker-pids"
LOG_DIR = COORD_DIR / ".worker-logs"
REPORTS_DIR = COORD_DIR / "integration-reports"
WORKERS_STATE_FILE = COORD_DIR / ".workers-state.json"
STANDARDS_DOC = COORD_DIR / "worker-engineering-standards.md"
EMPTY_MCP_FILE = COORD_DIR / ".empty-mcp.json"

# Fleet memory (Crawl tier): a single curated pitfalls list injected into every
# worker prompt so workers don't re-hit sharp edges past workers already paid for.
# Plain file, no ranking — the orchestrator curates it after `integrate` (DISTILL).
MEMORY_DIR = COORD_DIR / "memory"
PITFALLS_FILE = MEMORY_DIR / "pitfalls.md"

VENV_PY = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Permission mode for unattended workers. Workers run HEADLESS (claude --print).
#
# Раньше здесь стоял "bypassPermissions" из опасения, что headless-воркер «повиснет» на
# запросе разрешения. ПРОВЕРЕНО на живых прогонах 25.07.2026 (CC 2.1.219): в `auto` воркер
# НЕ виснет и НЕ падает — вызов отклоняется, агент получает отказ, доводит остальную работу
# и словами докладывает, чего ему не хватило. Проверены обе формы: запись файла за пределами
# рабочего каталога и сетевая команда (`curl`). Это ровно требуемое поведение: решение об
# опасном шаге принимает оператор, а не воркер.
#
# Слои защиты теперь такие: `auto` ловит неизвестное (в т.ч. то, о чём гард не знает),
# claude_guard_hook.py режет катастрофу и текстом отправляет воркера доложить координатору.
# Цена — часть задач вернётся не сделанной, а с «нужно разрешение»; это осознанный размен.
# Вернуть прежнее поведение: --perm bypassPermissions или $WORKER_PERMISSION_MODE.
DEFAULT_PERMISSION_MODE = os.environ.get("WORKER_PERMISSION_MODE", "auto")

# Soft cap on concurrently-live workers (every concurrent claude draws the same
# account quota). Overridable with --max-concurrent / --allow-over-cap.
DEFAULT_MAX_CONCURRENT = int(os.environ.get("WORKER_MAX_CONCURRENT", "5"))

# Денежный предохранитель на ОДНОГО headless-воркера (--max-budget-usd). Без него
# расход под bypassPermissions ничем не ограничен, а с CC 2.1.219 воркер сам может
# спавнить вложенных сабагентов (глубина до 3). "0"/"off" — выключить флаг вовсе.
# Override: --budget-usd / $WORKER_BUDGET_USD, per-worker — `budget: / max_usd:` в scope.
#
# ⚠️ Лимит НЕ спасает работу: по достижении потолка воркер обрывается на полуслове —
# деньги потрачены, результата нет. Поэтому потолок ставится ВЫШЕ типовой задачи, а не
# «поэкономнее». Замер по 29 прошлым воркерам (scripts/session_costs.py, 25.07.2026):
# медиана $4.5, 90-й перцентиль $27.6, максимум $117.8 (тот был на Opus 4.8 — $15/$75).
# На нынешнем дефолте Sonnet 5 самый дорогой воркер стоил $17. Стоявшие здесь "3"
# обрывали бы примерно каждого второго. 20 закрывает практически всех и при этом
# режет разгон вроде того $117 на четверти пути.
DEFAULT_WORKER_BUDGET_USD = os.environ.get("WORKER_BUDGET_USD", "20")

# Model for workers. Workers do scoped, well-specified implementation work
# (write a screen, a migration by the `sales` exemplar, tests) — Sonnet 5 handles
# this at a fraction of Opus 5's token cost. Keep the orchestrator (this driver +
# the lead session you run by hand) on Opus 5 where the planning judgement lives.
# Override per-run with --model, or globally with $WORKER_MODEL. Use "inherit"
# to drop the flag and let the worker use whatever default the CLI/account resolves —
# see the model=="inherit" warning in cmd_spawn. NB: Opus 5 is the default *Opus*
# (the `opus` alias resolves to it); it is NOT documented as the overall CLI default.
DEFAULT_WORKER_MODEL = os.environ.get("WORKER_MODEL", "sonnet")

# Effort — ось, ОРТОГОНАЛЬНАЯ модели (coordination/MODEL-TIERING.md). У Sonnet 5 и
# Opus 5 дефолт CLI-эффорта = high, поэтому механический воркер без явного effort
# молча работает в самом дорогом режиме. "medium" — разумный дефолт для скоуп-фичи.
# Override: $WORKER_EFFORT, per-worker — `effort:` в scope (см. _effort_for_worker).
DEFAULT_WORKER_EFFORT = os.environ.get("WORKER_EFFORT", "medium")
_VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}

# How long to wait for a worker's JSONL transcript to appear after launch.
TRANSCRIPT_TIMEOUT_SEC = 75.0
# Cap how many transcripts we scan when discovering a worker session (FALLBACK-скан;
# основной путь к транскрипту — детерминированный, см. _find_worker_transcript).
MAX_TRANSCRIPTS_TO_SCAN = 80

# Опциональный машиночитаемый вывод воркера. По умолчанию ВЫКЛ: окно воркера смотрит
# человек, а stream-json — это поток JSON-строк, нечитаемый глазами. Включённый режим
# добавляет --output-format stream-json --forward-subagent-text (текст ВЛОЖЕННЫХ
# сабагентов пробрасывается наверх с CC 2.1.219; оба флага работают ТОЛЬКО с --print)
# и складывает поток в LOG_DIR/<name>.jsonl — единственный способ увидеть, что делали
# сабагенты воркера. Включить: env WORKER_STREAM_JSON=1 перед spawn/respond.
WORKER_STREAM_JSON = os.environ.get("WORKER_STREAM_JSON", "0") in ("1", "true", "True")


# ─── claude CLI discovery ──────────────────────────────────────────────────────


def _find_claude_cli() -> str | None:
    """Locate the Claude Code CLI. Order:
      1. $CLAUDE_CLI env override
      2. `claude` on PATH
      3. bundled native-binary inside the VSCode / Cursor extension (highest
         version wins — the path embeds the version, so we glob + sort)
    """
    override = os.environ.get("CLAUDE_CLI")
    if override and Path(override).is_file():
        return override
    from shutil import which
    on_path = which("claude")
    if on_path:
        return on_path
    ext_roots = [
        Path.home() / ".vscode" / "extensions",
        Path.home() / ".cursor" / "extensions",
        Path.home() / ".vscode-server" / "extensions",
    ]
    found: list[tuple[list[int], Path]] = []
    for root in ext_roots:
        if not root.is_dir():
            continue
        for d in root.glob("anthropic.claude-code-*"):
            exe = d / "resources" / "native-binary" / "claude.exe"
            if exe.is_file():
                m = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", d.name)
                ver = [int(x) for x in m.groups()] if m else [0, 0, 0]
                found.append((ver, exe))
    if found:
        found.sort(reverse=True)
        return str(found[0][1])
    return None


# ─── tiny utilities ─────────────────────────────────────────────────────────────


def _norm(p: str | Path) -> str:
    """Case/sep-insensitive path key for comparing cwd fields on Windows."""
    return os.path.normcase(os.path.normpath(str(p)))


def _worktree_path(name: str) -> Path:
    return WORKTREE_PARENT / f"{WORKTREE_PREFIX}{name}"


def _first_msg_path(name: str) -> Path:
    return FIRST_MSG_DIR / f"{name}.md"


def _scope_path(name: str) -> Path:
    return COORD_DIR / f"{name}-scope.md"


def _status_path_in_worktree(name: str, wt: Path) -> Path:
    return wt / "coordination" / f"{name}-status.md"


def _scope_text(name: str) -> str:
    """Текст scope-файла воркера; пусто, если файла нет.

    Четыре парсера полей LOOP CONTRACT (model/budget/effort/mcp) раньше несли по своей копии
    `try: read_text except OSError: return default` — объединено здесь. Валидация у полей
    осознанно разная и остаётся у каждого своя.

    Без кэша намеренно: файл маленький, а `lru_cache` по имени воркера отдавал бы устаревший
    текст, если scope успели поправить в том же процессе (на этом сразу споткнулись тесты).
    """
    try:
        return _scope_path(name).read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def _model_for_worker(name: str, default: str) -> str:
    """Per-worker модель из scope LOOP CONTRACT (`model: haiku|sonnet|opus|inherit`).
    Механическая работа → haiku, основной код → sonnet, архитектура → opus (cost-гайд
    Anthropic). Фолбэк — дефолт спавна (--model / $WORKER_MODEL)."""
    text = _scope_text(name)
    # `(?:#.*)?$` — канонический шаблон LOOP CONTRACT в worker-engineering-standards.md
    # кладёт ХВОСТОВОЙ комментарий после значения (`model: sonnet   # тир: ...`). Без этого
    # допуска scope, скопированный из шаблона дословно, молча проваливался в дефолт — то есть
    # тиринг и денежный предохранитель не работали ни у одного воркера, написанного по образцу.
    for m in re.finditer(r"(?im)^\s*model:\s*([A-Za-z0-9._-]+)\s*(?:#.*)?$", text):
        val = m.group(1).strip().lower()
        # Fable — флагман $10/$50 ВНЕ тиринга воркеров (canon MODEL-TIERING.md):
        # отклонить и упасть на дефолт, а не уронить воркера ошибкой.
        if val == "fable" or val.startswith("fable-") or val.startswith("claude-fable"):
            print(f"[spawn:{name}] scope просит model: {val} — Fable воркерам не положен "
                  f"($10/$50, канон MODEL-TIERING.md), отклонено. Использую дефолт '{default}'.",
                  file=sys.stderr)
            continue
        if val in {"inherit", "haiku", "sonnet", "opus"} or val.startswith("claude-"):
            return val
    return default


def _budget_for_worker(name: str, default: str) -> str:
    """Per-worker денежный предохранитель из scope LOOP CONTRACT (блок
    `budget: / max_usd: <N>`), по образцу _model_for_worker. Фолбэк — дефолт
    спавна (--budget-usd / $WORKER_BUDGET_USD)."""
    m = re.search(r"(?im)^[ \t]*budget:[ \t]*$\n((?:^[ \t]+\S.*$\n?)*)", _scope_text(name))
    if m:
        mm = re.search(r"(?im)^\s*max_usd:\s*([0-9]+(?:\.[0-9]+)?)\s*(?:#.*)?$", m.group(1))
        if mm:
            return mm.group(1)
    return default


def _effort_for_worker(name: str, default: str) -> str:
    """Per-worker effort из scope LOOP CONTRACT (`effort: low|medium|high|xhigh|max`),
    по образцу _model_for_worker. Фолбэк — дефолт спавна ($WORKER_EFFORT)."""
    for m in re.finditer(r"(?im)^\s*effort:\s*([A-Za-z]+)\s*(?:#.*)?$", _scope_text(name)):
        val = m.group(1).strip().lower()
        if val in _VALID_EFFORTS:
            return val
    return default


def _mcp_config_for_worker(name: str) -> Path:
    """По умолчанию воркер стартует с ПУСТЫМ MCP (grep-first дефолт Anthropic, без
    оверхеда MCP-определений). Если scope содержит `mcp: serena` И есть конфиг
    coordination/mcp-serena.json — отдаём его (семантическая навигация по символам)."""
    if re.search(r"(?im)^\s*mcp:\s*serena\s*$", _scope_text(name)):
        serena = COORD_DIR / "mcp-serena.json"
        if serena.is_file():
            return serena
        print(f"[spawn:{name}] scope просит mcp: serena, но {serena} нет — "
              f"запускаю с пустым MCP.", file=sys.stderr)
    return EMPTY_MCP_FILE


# ── PreToolUse deny-гард для воркеров ────────────────────────────────────────────
# Воркеры идут под bypassPermissions (headless — ответить на запрос некому). Чтобы это
# не было «голым», в их сессию через --settings подключается claude_guard_hook.py — тот
# же deny-гард, что у B-сессий: режет катастрофу (rm -rf по корню, curl|sh, чтение
# .env/секретов, tailscale ssh/prod-IP, git push --force) ДО выполнения, при любом режиме.
# STRICT-тир (как у удалённых B). Отключить целиком: env WORKER_GUARD=0.
GUARD_HOOK = REPO_ROOT / "claude_guard_hook.py"
GUARD_SETTINGS = COORD_DIR / ".guard-settings.json"
WORKER_GUARD = os.environ.get("WORKER_GUARD", "1") not in ("0", "false", "False")


def _guard_enabled() -> bool:
    return WORKER_GUARD and GUARD_HOOK.is_file()


_GUARD_MATCHER_FALLBACK = "Bash|PowerShell|Edit|Write|MultiEdit|Read|NotebookEdit"


def _guard_matcher() -> str:
    """Список инструментов для PreToolUse-гарда — из самого гарда, а не копией.

    Строка жила четырьмя копиями (.claude/settings.json, settings.json.example, здесь и
    tg_sessions.py). Когда в покрытие добавили PowerShell, копия в tg_sessions отстала, и
    удалённые B-сессии исполняли PowerShell вообще без гарда. Фолбэк на случай, если модуль
    гарда не импортируется: лучше повесить гард по устаревшему списку, чем не повесить вовсе.
    """
    try:
        import claude_guard_hook
        return str(claude_guard_hook.GUARD_MATCHER)
    except Exception:
        return _GUARD_MATCHER_FALLBACK


def _ensure_guard_settings() -> str | None:
    """Записать settings-файл с PreToolUse-гардом (АБСОЛЮТНЫЕ пути к main-venv-python и
    хуку — чтобы работало из любого worktree) и вернуть путь. None, если гард выключен."""
    if not _guard_enabled():
        return None
    cmd = f'"{sys.executable}" "{GUARD_HOOK}"'
    cfg = {"hooks": {"PreToolUse": [{
        "matcher": _guard_matcher(),
        "hooks": [{"type": "command", "command": cmd}],
    }]}}
    try:
        GUARD_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        GUARD_SETTINGS.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(GUARD_SETTINGS)
    except OSError:
        return None


def _human_age(ts: float) -> str:
    delta = max(0.0, time.time() - ts)
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


def _parse_ts(raw: str) -> float:
    if not raw:
        return 0.0
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


# ─── state persistence ───────────────────────────────────────────────────────


def _load_state() -> dict[str, dict]:
    if not WORKERS_STATE_FILE.exists():
        return {}
    try:
        return json.loads(WORKERS_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, dict]) -> None:
    WORKERS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKERS_STATE_FILE.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def _set_worker_state(name: str, **fields) -> None:
    state = _load_state()
    state.setdefault(name, {}).update(fields)
    _save_state(state)


def _get_worker_state(name: str) -> dict:
    return _load_state().get(name, {})


def _clear_worker_state(name: str) -> None:
    state = _load_state()
    if name in state:
        del state[name]
        _save_state(state)


# ─── git ──────────────────────────────────────────────────────────────────────


def _git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git"] + args,
        cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _git_run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )


def _list_available() -> list[str]:
    if not FIRST_MSG_DIR.is_dir():
        return []
    return [f.stem for f in sorted(FIRST_MSG_DIR.glob("*.md"))]


def _ensure_worktree(name: str) -> Path:
    """Create the worker's worktree + branch from BASE_BRANCH if missing."""
    wt = _worktree_path(name)
    if wt.is_dir():
        return wt
    # branch exists already? attach a worktree to it; else create branch.
    branch_exists = bool(_git(["rev-parse", "--verify", "--quiet", name], cwd=REPO_ROOT))
    if branch_exists:
        args = ["worktree", "add", str(wt), name]
    else:
        args = ["worktree", "add", "-b", name, str(wt), BASE_BRANCH]
    proc = _git_run(args, cwd=REPO_ROOT)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git worktree add failed for {name}: "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    print(f"[spawn:{name}] worktree created: {wt} (branch {name} from {BASE_BRANCH})")
    return wt


# ─── worker scaffolding (copied into worktree at spawn) ─────────────────────────


def _copy_into_worktree(src: Path, wt: Path, rel_dest: str) -> None:
    if not src.is_file():
        return
    dest = wt / rel_dest
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
            dest.write_bytes(src.read_bytes())
    except OSError as e:
        print(f"[spawn] warn: could not copy {src.name}: {e}", file=sys.stderr)


def _write_skeleton_status(name: str, wt: Path) -> None:
    """Write a recoverable skeleton status BEFORE claude starts, so a worker
    that dies early still leaves a record. Never clobbers an existing file."""
    status = _status_path_in_worktree(name, wt)
    if status.exists():
        return
    spawned_at = datetime.now(timezone.utc).isoformat()
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(
        f"# {name} — Status\n\n"
        f"STATE: SPAWNED (no work yet)\n\n"
        f"## Worktree\nPath: {wt}\nBranch: {name}\nSpawned at: {spawned_at}\n\n"
        f"## To fill in (worker overwrites this)\n"
        f"- [ ] Karpathy 5-step loop iterations\n"
        f"- [ ] Six-layer commit body\n"
        f"- [ ] Acceptance-gate matrix\n"
        f"- [ ] End with the STATE banner (COMPLETE / BLOCKED / NEEDS-ORCHESTRATOR-ANSWER)\n",
        encoding="utf-8",
    )
    print(f"[spawn:{name}] skeleton status written.")


def _commit_scaffold(name: str, wt: Path) -> None:
    """Commit the orchestrator-owned scaffolding (scope + skeleton status +
    standards) on the worker branch so `cleanup` never blocks on untracked
    files. Stages ONLY explicit files — never `git add -A` (.env has secrets)."""
    rel = [
        f"coordination/{name}-scope.md",
        f"coordination/{name}-status.md",
        "coordination/worker-engineering-standards.md",
    ]
    present = [r for r in rel if (wt / r).is_file()]
    if not present:
        return
    _git(["add", "--"] + present, cwd=wt)
    staged = _git(["diff", "--cached", "--name-only"], cwd=wt)
    if not staged.strip():
        return
    proc = _git_run(
        ["commit", "-q", "-m", f"chore(worker): scaffold scope + status for {name}"],
        cwd=wt,
    )
    if proc.returncode == 0:
        print(f"[spawn:{name}] scaffold committed ({len(staged.splitlines())} file(s)).")


def _prime_trust(wt: Path) -> None:
    """Pre-accept the folder-trust dialog for the worktree in ~/.claude.json so
    the worker doesn't hang on the 'Do you trust this folder?' modal at launch.
    Best-effort, atomic write — never blocks spawn."""
    cfg_path = Path.home() / ".claude.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return
    projects = cfg.setdefault("projects", {})
    key = str(wt.resolve())
    entry = projects.setdefault(key, {})
    if entry.get("hasTrustDialogAccepted") is True:
        return  # already primed
    entry["hasTrustDialogAccepted"] = True
    entry.setdefault("enabledMcpjsonServers", [])
    entry.setdefault("disabledMcpjsonServers", [])
    try:
        tmp = cfg_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cfg_path)
        print(f"[spawn] trust primed for {wt.name}")
    except OSError as e:
        print(f"[spawn] warn: could not prime trust: {e}", file=sys.stderr)


# ─── worker contract preamble (prepended to every first-message) ────────────────

_PREAMBLE = """\
=== WORKER ENGINEERING STANDARDS (ОБЯЗАТЕЛЬНО — ПРОЧТИ ПЕРВЫМ) ===

Ты — воркер под оркестратором. ДО любой работы:
1. Прочитай coordination/worker-engineering-standards.md — твой контракт.
2. Прочитай свой скоуп: coordination/<your-name>-scope.md
3. Прочитай CLAUDE.md (корень) — конвенции проекта.

KARPATHY 5-STEP — ЭТО ЦИКЛ: Think → Test → Validate → Wire → Review →
(если хоть один пункт acceptance-gate КРАСНЫЙ) ВЕРНИСЬ к падающему шагу.
Документируй каждую итерацию в status-файле.

ПРИНЦИПЫ KARPATHY (жёстко):
- Think Before Coding — назови допущения; неясно → пиши NEEDS-ORCHESTRATOR-ANSWER.
- Simplicity First — минимум кода, без спекулятивных абстракций.
- Surgical Changes — трогай только нужное; каждая строка диффа = из ТЗ.
- Goal-Driven Execution — критерии успеха заранее; доказательство до «готово».

ЛЕЧИ БОЛЕЗНЬ, НЕ СИМПТОМ: каждый клейм трассирует SYMPTOM → DISEASE → ROOT CAUSE.
Тело коммита — six-layer. Аудит до фикса.

НЕ пиши `STATE: COMPLETE`, пока:
- все acceptance-gate ЗЕЛЁНЫЕ;
- `pytest` возвращает 0; импорты резолвятся;
- six-layer в теле коммита; STR-роли (если нетривиально).

Запрещено: single-pass без цикла; спекулятивные рефакторы; симптом-фиксы без
трассировки корня; `except Exception: pass`; `git add -A`; деструктивные операции;
нетривиальный фикс без тестов; тело коммита без six-layer.

Ты в собственном окне. Работай автономно. Никогда не вызывай AskUserQuestion —
вместо этого пиши NEEDS-ORCHESTRATOR-ANSWER в status-файл.

ПАМЯТЬ ФЛОТА: если по ходу наткнулся на НЕОЧЕВИДНЫЕ грабли, которые стоили тебе
итераций и пригодятся другим воркерам — добавь в status-файл секцию
`## PITFALLS-DISCOVERED` с записями `СИМПТОМ → причина → ЛЕЧЕНИЕ` (по одной на строку,
маркером `-`). Только переиспользуемое, НЕ привязанное к твоей конкретной задаче.
Нечего добавить — секцию не пиши. (Оркестратор соберёт их в общий список при интеграции.)

Status-файл заканчивается баннером STATE: COMPLETE / BLOCKED / NEEDS-ORCHESTRATOR-ANSWER.

"""

# Task header — separated from _PREAMBLE so fleet memory (_memory_block) can be
# injected between the standards contract and the worker's actual task.
_TASK_HEADER = "=== ТВОЯ ЗАДАЧА ===\n\n"


def _memory_block() -> str:
    """Crawl-tier fleet memory: the curated pitfalls list, wrapped for the prompt.
    Injected into every worker prompt (RETRIEVE) so workers skip sharp edges past
    workers already paid for. Returns '' if the file is absent/empty — graceful
    no-op, so removing the file simply turns the feature off."""
    try:
        body = PITFALLS_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not body:
        return ""
    return (
        "=== ИЗВЕСТНЫЕ ГРАБЛИ ПРОЕКТА (PITFALLS — учти ПЕРЕД работой) ===\n\n"
        f"{body}\n\n"
    )


# ─── spawn ──────────────────────────────────────────────────────────────────────


def _validate_first_msg(name: str) -> str:
    msg_path = _first_msg_path(name)
    if not msg_path.is_file():
        raise FileNotFoundError(
            f"First-message missing: {msg_path}\n"
            f"Create it with the worker's task (see coordination/README.md)."
        )
    raw = msg_path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"First-message file is empty: {msg_path}")
    return raw


def _active_worker_count() -> int:
    """Workers in state that were spawned and still have a live worktree."""
    state = _load_state()
    n = 0
    for name, s in state.items():
        if s.get("spawned_at") and _worktree_path(name).is_dir():
            n += 1
    return n


def _psq(s: object) -> str:
    """Single-quote a PowerShell literal; escape embedded single quotes by doubling."""
    return "'" + str(s).replace("'", "''") + "'"


def _claude_cmdline(name: str, claude_cli: str, perm: str, model: str, budget: str,
                    effort: str, session_id: str | None = None,
                    resume: bool = False) -> str:
    """ЕДИНЫЙ генератор строки запуска claude (PowerShell-инвокация без пайпов).
    Один источник правды по флагам для spawn и respond --resume: раньше respond
    переспавнивал воркера через cmd_spawn целиком, и любой флаг, добавленный в
    лаунчер, надо было держать в голове дважды. Собираем список токенов и join'им —
    так физически невозможны двойные пробелы и пустые флаги."""
    parts = [f"& {_psq(claude_cli)}", "--print", "--verbose", "--permission-mode", perm]
    # Детерминированный id сессии: при спавне мы его НАЗНАЧАЕМ (--session-id), при
    # ответе — ПОДНИМАЕМ ту же сессию (--resume), сохраняя контекст и не переплачивая
    # за повторную отправку преамбулы/pitfalls/задачи.
    if session_id:
        parts += ["--resume" if resume else "--session-id", _psq(session_id)]
    # PreToolUse deny-гард в сессию воркера (--settings) + строгий тир. Хардненинг под
    # bypassPermissions: катастрофа режется до выполнения. Отключить — env WORKER_GUARD=0.
    guard = _ensure_guard_settings()
    if guard:
        parts += ["--settings", _psq(guard)]
    # "inherit" => no --model flag => worker uses the account default model.
    if model != "inherit":
        parts += ["--model", _psq(model)]
    # Денежный предохранитель на воркера. "0"/"off" — не ставить флаг вовсе.
    if str(budget).strip().lower() not in ("", "0", "off"):
        parts += ["--max-budget-usd", _psq(budget)]
    # Effort — ось, ортогональная модели (см. DEFAULT_WORKER_EFFORT).
    if effort:
        parts += ["--effort", _psq(effort)]
    # Опциональный машиночитаемый поток (см. WORKER_STREAM_JSON). --forward-subagent-text
    # без stream-json CLI не принимает, поэтому флаги ставятся только парой.
    if WORKER_STREAM_JSON:
        parts += ["--output-format", "stream-json", "--forward-subagent-text"]
    # Per-worker MCP: пусто по умолчанию; serena — только если scope это запросил.
    parts += ["--strict-mcp-config", "--mcp-config", _psq(_mcp_config_for_worker(name))]
    parts += ["--add-dir", _psq(REPO_ROOT)]
    return " ".join(parts)


def _write_launcher(name: str, wt: Path, message: str, claude_cli: str,
                    perm: str, model: str, budget: str, effort: str,
                    session_id: str | None = None, resume: bool = False) -> Path:
    """Write the per-worker prompt + PowerShell launcher. The launcher reads
    the (multi-line) prompt from a file and passes it as a single argv to
    claude — avoids all wt.exe / shell quoting hell.
    resume=True -> та же функция поднимает УЖЕ существующую сессию (--resume),
    а `message` играет роль не первого промпта, а очередной реплики оркестратора."""
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    LAUNCHER_DIR.mkdir(parents=True, exist_ok=True)
    PID_DIR.mkdir(parents=True, exist_ok=True)
    if not EMPTY_MCP_FILE.exists():
        EMPTY_MCP_FILE.write_text('{"mcpServers": {}}\n', encoding="utf-8")

    # Промпт resume'а держим в отдельном файле: перезапись <name>.txt стёрла бы
    # исходный промпт спавна, по которому потом разбирают, что воркеру вообще прислали.
    prompt_file = PROMPT_DIR / (f"{name}.resume.txt" if resume else f"{name}.txt")
    prompt_file.write_text(message, encoding="utf-8")
    launcher = LAUNCHER_DIR / f"{name}.ps1"
    pid_file = PID_DIR / f"{name}.pid"

    # Локальный алиас модульного _psq (тот же цитатник PowerShell, что и в _claude_cmdline) —
    # чтобы не тащить подчёркивание в каждую из шести подстановок шаблона ниже.
    psq = _psq
    strict_line = "$env:CLAUDE_GUARD_STRICT = '1'\n" if _guard_enabled() else ""
    # Кап на вложенность/параллелизм сабагентов ВНУТРИ воркера. Внешний --max-concurrent
    # считает окна-процессы, а не сабагентов; без этого 5 окон × дерево глубины 3 =
    # непредсказуемый расход. DEPTH=1 по смыслу апстрима = «вложенность запрещена» (дефолт
    # платформы — 3). Override: $WORKER_SUBAGENT_DEPTH и $WORKER_MAX_SUBAGENTS.
    subagent_depth = os.environ.get("WORKER_SUBAGENT_DEPTH", "1")
    subagent_width = os.environ.get("WORKER_MAX_SUBAGENTS", "4")
    subagent_lines = (
        f"$env:CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH = {psq(subagent_depth)}\n"
        f"$env:CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS = {psq(subagent_width)}\n"
    )

    # Промпт подаём claude через STDIN (пайп файла), НЕ позиционным argv.
    # Большая многострочная строка в `-- $prompt` рвалась PowerShell'ом по переносам →
    # claude получал только первую строку (заголовок стандартов), тело терялось →
    # воркер вставал «прислали пустоту». Пайп файла в stdin переносит любой размер целиком.
    invoke = (f"Get-Content -Raw -Encoding UTF8 -LiteralPath {psq(prompt_file)} | "
              + _claude_cmdline(name, claude_cli, perm, model, budget, effort,
                                session_id=session_id, resume=resume))
    if WORKER_STREAM_JSON:
        # stream-json пишем в LOG_DIR/<name>.jsonl. Пишем через StreamWriter, а НЕ через
        # Out-File/Tee-Object: в Windows PowerShell 5.1 они кладут BOM (а Tee — вообще
        # UTF-16LE), и первая строка перестаёт парситься как JSON. `$_` в конце блока
        # прокидывает строку дальше в консоль — окно не выглядит зависшим.
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / f"{name}.jsonl"
        run_lines = (
            f"$log = New-Object IO.StreamWriter({psq(log_file)}, $false, "
            f"(New-Object Text.UTF8Encoding($false)))\n"
            f"Write-Host '(WORKER_STREAM_JSON=1 -> {log_file.name})' -ForegroundColor DarkGray\n"
            f"try {{ {invoke} | ForEach-Object {{ $log.WriteLine($_); $log.Flush(); $_ }} }}\n"
            f"finally {{ $log.Dispose() }}\n"
        )
    else:
        run_lines = invoke + "\n"

    # NOTES on encoding (hard-won — Russian-locale Windows):
    #   * The .ps1 is written utf-8-SIG (BOM). Windows PowerShell 5.1 reads
    #     -File as cp1251 WITHOUT a BOM, mojibaking the Cyrillic paths inside
    #     -> Set-Location fails -> $ErrorActionPreference=Stop aborts -> claude
    #     never starts. The BOM makes PS read it as UTF-8.
    #   * The prompt is read with -Encoding UTF8 (it's UTF-8 without BOM).
    #   * Worker runs HEADLESS + autonomous: `claude --print --verbose`.
    #     Interactive mode only PRE-FILLS the positional prompt and waits for
    #     Enter (verified: the process launches but writes no transcript and
    #     edits nothing) — so it cannot self-start. --print runs the full
    #     agentic loop to completion without any keypress.
    #   * --verbose streams the turns into the window so you can watch; the
    #     authoritative progress channel is still the JSONL transcript
    #     (status / tail read it).
    #   * Console set to UTF-8 so the Cyrillic prompt round-trips to claude.
    #   * The launcher records its OWN $PID to a pid-file so `stop`/`cleanup`
    #     can kill the process tree and close the window after completion.
    launcher.write_text(
        "# auto-generated by spawn_workers.py — worker launcher (headless auto)\n"
        "$ErrorActionPreference = 'Stop'\n"
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n"
        "$OutputEncoding = [Text.Encoding]::UTF8\n"
        f"$Host.UI.RawUI.WindowTitle = 'worker:{name}'\n"
        f"$PID | Out-File -Encoding ascii -LiteralPath {psq(str(pid_file))}\n"
        f"Set-Location -LiteralPath {psq(str(wt))}\n"
        f"Write-Host '=== worker:{name} — claude (auto mode) starting ===' -ForegroundColor Cyan\n"
        f"{strict_line}"
        f"{subagent_lines}"
        f"{run_lines}"
        "Write-Host ''\n"
        f"Write-Host '=== worker:{name} — claude finished ===' -ForegroundColor Yellow\n"
        # Окно воркера больше НЕ нужно после завершения claude → закрываем СРАЗУ (просьба оператора
        # 2026-07-02). Транскрипт .jsonl + worktree остаются на диске → tail/status/интеграция работают
        # после закрытия. Оставить окно открытым для отладки: env WORKER_KEEP_WINDOW=1 перед spawn.
        "if ($env:WORKER_KEEP_WINDOW -eq '1') {\n"
        "  Write-Host '(WORKER_KEEP_WINDOW=1 — окно оставлено открытым)' -ForegroundColor DarkGray\n"
        "} else {\n"
        "  Write-Host '(окно закрывается — worktree и транскрипт сохранены) ...' -ForegroundColor DarkGray\n"
        "  Start-Sleep -Seconds 2\n"
        "  Stop-Process -Id $PID -Force\n"
        "}\n",
        encoding="utf-8-sig",
    )
    return launcher


def _launch_window(name: str, launcher: Path) -> str:
    """Open a visible Windows Terminal window running the launcher. Falls back
    to a new PowerShell console if wt.exe is unavailable. Returns spawn method."""
    ps_args = [
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(launcher),
    ]
    from shutil import which
    if which("wt.exe") or which("wt"):
        wt = which("wt.exe") or which("wt")
        subprocess.Popen(
            [wt, "new-tab", "--title", f"worker:{name}", "powershell"] + ps_args,
            cwd=str(REPO_ROOT),
        )
        return "windows-terminal"
    # Fallback: standalone console window.
    CREATE_NEW_CONSOLE = 0x00000010
    subprocess.Popen(
        ["powershell"] + ps_args,
        creationflags=CREATE_NEW_CONSOLE,
    )
    return "new-console"


def cmd_spawn(names: list[str], dry_run: bool, max_concurrent: int,
              allow_over_cap: bool, perm: str, model: str,
              budget: str = DEFAULT_WORKER_BUDGET_USD) -> int:
    claude_cli = _find_claude_cli()
    if not claude_cli:
        print("[spawn] claude CLI not found. Set $CLAUDE_CLI or install Claude Code.",
              file=sys.stderr)
        return 1

    # SECURITY: bypassPermissions lets the headless worker run ANY command on
    # this host (read .env / secrets, reach the network, push to remotes) — the
    # git worktree is NOT a sandbox. Never let this be silent. It's the default
    # because headless workers can't answer permission prompts; downgrade with
    # --perm if you don't need unattended Bash/git.
    if perm == "bypassPermissions":
        if _guard_enabled():
            note = ("deny-гард claude_guard_hook.py режет катастрофу (rm -rf по корню, "
                    "curl|sh, чтение секретов, prod-IP, push --force), но worktree — НЕ песочница")
        else:
            note = "команды НЕ блокируются (WORKER_GUARD=0); worktree — НЕ песочница"
        print(f"⚠️  SECURITY: воркеры под --permission-mode bypassPermissions: {note}. "
              "Это НЕ дефолт с 25.07.2026 — дефолт `auto` (воркер докладывает вместо "
              "самовольного запуска). Вернуть штатное: убрать --perm/$WORKER_PERMISSION_MODE.",
              file=sys.stderr)

    # model=="inherit" тихо снимает --model -> воркер берёт то, что зарезолвит CLI/аккаунт
    # (настройка сессии, settings.json, дефолт версии). Это НЕ обязательно Sonnet: в проектном
    # .claude/settings.json стоит "model": "opus", а алиас opus резолвится в Opus 5 ($5/$25
    # против $3/$15 у Sonnet 5). Несколько воркеров под inherit = непредсказуемая цена прогона.
    if model == "inherit":
        print("⚠️  model=inherit → модель воркера не зафиксирована: её выберет CLI/аккаунт "
              "(в этом проекте settings.json пиннит 'opus' → Opus 5, $5/$25 против $3/$15 "
              "у Sonnet 5). Укажи --model явно, если нужна предсказуемая цена прогона.",
              file=sys.stderr)

    # Soft concurrency cap (quota guard).
    if not dry_run and not allow_over_cap:
        current = _active_worker_count()
        free = max(0, max_concurrent - current)
        if len(names) > free:
            deferred = names[free:]
            names = names[:free]
            print(
                f"[spawn] CAP: {current} active + {len(names) + len(deferred)} queued "
                f"exceeds --max-concurrent={max_concurrent}. Spawning {len(names)}, "
                f"deferring {len(deferred)}: {', '.join(deferred) or '—'}. "
                f"Use --allow-over-cap to override.",
                file=sys.stderr,
            )
            if not names:
                return 1

    rc = 0
    for name in names:
        try:
            raw = _validate_first_msg(name)
            mem = _memory_block()
            message = _PREAMBLE + mem + _TASK_HEADER + raw
            # Id сессии назначаем МЫ, а не CLI: тогда транскрипт лежит по вычислимому пути
            # ~/.claude/projects/<slug(worktree)>/<session-id>.jsonl (см. _find_worker_transcript)
            # и его же можно поднять через --resume в respond — без скана чужих транскриптов.
            session_id = str(uuid.uuid4())
            if dry_run:
                wt = _worktree_path(name)
                exists = "exists" if wt.is_dir() else f"would create from {BASE_BRANCH}"
                wm = _model_for_worker(name, model)
                wb = _budget_for_worker(name, budget)
                we = _effort_for_worker(name, DEFAULT_WORKER_EFFORT)
                print(f"[dry-run:spawn:{name}] worktree {wt} ({exists}); "
                      f"prompt {len(message)} chars (pitfalls {len(mem)}); "
                      f"perm={perm}; model={wm}; budget=${wb}; effort={we}; "
                      f"mcp={_mcp_config_for_worker(name).name}; "
                      f"guard={'on' if _guard_enabled() else 'off'}; cli={claude_cli}")
                print(f"[dry-run:spawn:{name}] launch: "
                      + _claude_cmdline(name, claude_cli, perm, wm, wb, we,
                                        session_id=session_id))
                continue
            if mem:
                print(f"[spawn:{name}] memory: pitfalls injected ({len(mem)} chars) "
                      f"from coordination/memory/pitfalls.md")
            wt = _ensure_worktree(name)
            _copy_into_worktree(STANDARDS_DOC, wt, "coordination/worker-engineering-standards.md")
            _copy_into_worktree(_scope_path(name), wt, f"coordination/{name}-scope.md")
            _write_skeleton_status(name, wt)
            _commit_scaffold(name, wt)
            _prime_trust(wt)
            worker_model = _model_for_worker(name, model)
            worker_budget = _budget_for_worker(name, budget)
            worker_effort = _effort_for_worker(name, DEFAULT_WORKER_EFFORT)
            launcher = _write_launcher(name, wt, message, claude_cli, perm, worker_model,
                                       worker_budget, worker_effort, session_id=session_id)
            method = _launch_window(name, launcher)
            _set_worker_state(
                name,
                worktree=str(wt),
                spawned_at=datetime.now(timezone.utc).isoformat(),
                spawn_method=method,
                prompt_chars=len(message),
                launcher=str(launcher),
                pid_file=str(PID_DIR / f"{name}.pid"),
                # Ключ и к транскрипту, и к --resume в respond. Переспавн выдаёт НОВЫЙ id
                # (старую сессию продолжать уже нечем) — поле перезаписывается осознанно.
                session_id=session_id,
            )
            print(f"[spawn:{name}] launched ({method}). Watch its window, or run "
                  f"`status`/`tail {name}`.")
            _await_transcript(name, wt)
        except Exception as e:
            print(f"[spawn:{name}] error: {e}", file=sys.stderr)
            rc = 1
    return rc


def _await_transcript(name: str, wt: Path) -> None:
    """Poll for the worker's JSONL transcript to confirm claude actually
    attached and accepted the first message. Non-fatal on timeout."""
    deadline = time.time() + TRANSCRIPT_TIMEOUT_SEC
    print(f"[spawn:{name}] waiting for transcript (timeout {int(TRANSCRIPT_TIMEOUT_SEC)}s)...")
    while time.time() < deadline:
        if _find_worker_transcript(name) is not None:
            elapsed = int(time.time() - (deadline - TRANSCRIPT_TIMEOUT_SEC))
            print(f"[spawn:{name}] ✓ transcript found after {elapsed}s — worker live.")
            return
        time.sleep(2.0)
    print(f"[spawn:{name}] WARN: no transcript in {int(TRANSCRIPT_TIMEOUT_SEC)}s. "
          f"Worker may still be booting or stuck on a modal — check its window.",
          file=sys.stderr)


# ─── stop (kill process tree + close window) ────────────────────────────────────


def _stop_worker(name: str) -> bool:
    """Kill the worker's process tree (powershell launcher + child claude) and
    close its window. Reads the PID the launcher recorded. Returns True if a
    live process was killed."""
    pid_file = PID_DIR / f"{name}.pid"
    pid = None
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text(encoding="ascii", errors="ignore").strip())
        except (OSError, ValueError):
            pid = None
    killed = False
    if pid:
        # taskkill /T kills the whole tree (closes the window), /F forces it.
        proc = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                              capture_output=True, text=True, check=False)
        killed = proc.returncode == 0
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass
    return killed


def cmd_stop(name: str) -> int:
    if _stop_worker(name):
        print(f"[stop:{name}] worker process killed + window closed.")
    else:
        print(f"[stop:{name}] no live worker process (already exited?). pid-file cleared.")
    _set_worker_state(name, stopped_at=datetime.now(timezone.utc).isoformat())
    return 0


# ─── respond (answer a NEEDS-ORCHESTRATOR-ANSWER worker) ───────────────────────


def _archive_answer(name: str, answer: str, ts: str) -> Path | None:
    """Аудит-копия ответа оркестратора в coordination/orchestrator-answers/."""
    try:
        ans_dir = COORD_DIR / "orchestrator-answers"
        ans_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = ans_dir / f"{stamp}_{name}.md"
        path.write_text(f"# Answer to {name} @ {ts}\n\n{answer}\n", encoding="utf-8")
        return path
    except OSError:
        return None


def cmd_respond(name: str, answer: str, dry_run: bool, perm: str, model: str) -> int:
    """Answer a worker that wrote NEEDS-ORCHESTRATOR-ANSWER. Headless workers exit
    when they need a decision, so 'answering' = поднять ТУ ЖЕ сессию воркера через
    `claude --resume <session-id>` и подать ответ очередной репликой: контекст сессии
    (что уже прочитано/сделано) сохраняется, а преамбула + pitfalls + задача НЕ
    отправляются и НЕ оплачиваются второй раз.
    Фолбэк для воркеров, спавненных до появления session_id в состоянии, — прежнее
    поведение: дописать ответ в first-msg и переспавнить с нуля."""
    msg_path = _first_msg_path(name)
    if not msg_path.is_file():
        print(f"[respond:{name}] no first-message at {msg_path}", file=sys.stderr)
        return 1
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    tail = (f"Продолжи с того места, где остановился: прочитай свой "
            f"coordination/{name}-status.md, учти ответ выше и доведи задачу до "
            f"STATE: COMPLETE.\n")
    st = _get_worker_state(name)
    session_id = st.get("session_id")
    wt = _worktree_path(name)
    if session_id and not wt.is_dir():
        print(f"[respond:{name}] session_id есть, но worktree {wt} отсутствует — "
              f"resume невозможен, переспавниваю.", file=sys.stderr)
        session_id = None

    if session_id:
        claude_cli = _find_claude_cli()
        if not claude_cli:
            print("[respond] claude CLI not found. Set $CLAUDE_CLI or install Claude Code.",
                  file=sys.stderr)
            return 1
        prompt = f"Ответ оркестратора ({ts}):\n\n{answer}\n\n{tail}"
        if dry_run:
            print(f"[dry-run:respond:{name}] would resume session {session_id} "
                  f"with a {len(prompt)}-char reply (first-msg НЕ трогаем).")
            print(f"[dry-run:respond:{name}] launch: "
                  + _claude_cmdline(name, claude_cli, perm,
                                    _model_for_worker(name, model),
                                    _budget_for_worker(name, DEFAULT_WORKER_BUDGET_USD),
                                    _effort_for_worker(name, DEFAULT_WORKER_EFFORT),
                                    session_id=session_id, resume=True))
            return 0
        # Старый процесс/окно надо погасить: сессию нельзя вести из двух claude сразу.
        _stop_worker(name)
        audit = _archive_answer(name, answer, ts)
        launcher = _write_launcher(
            name, wt, prompt, claude_cli, perm,
            _model_for_worker(name, model),
            _budget_for_worker(name, DEFAULT_WORKER_BUDGET_USD),
            _effort_for_worker(name, DEFAULT_WORKER_EFFORT),
            session_id=session_id, resume=True)
        method = _launch_window(name, launcher)
        # ЖУРНАЛ ответа при resume ведём в состоянии воркера + аудит-файле, а НЕ в first-msg:
        # first-msg — это промпт СПАВНА, и дописанный туда ответ уехал бы в контекст ещё раз
        # при любом будущем переспавне (ровно та переплата, которую resume и убирает).
        _set_worker_state(
            name,
            resumed_at=datetime.now(timezone.utc).isoformat(),
            resume_count=int(st.get("resume_count", 0)) + 1,
            answers=list(st.get("answers", [])) + [
                {"at": ts, "chars": len(answer), "audit": str(audit) if audit else None}],
            spawn_method=method,
            launcher=str(launcher),
        )
        print(f"[respond:{name}] resumed session {session_id} ({method}) — "
              f"контекст сохранён, промпт спавна не переотправлялся.")
        return 0

    # ── фолбэк: воркер без session_id (спавнен до этой правки) ──
    print(f"[respond:{name}] в состоянии нет session_id — resume невозможен, "
          f"полный переспавн (промпт спавна оплачивается заново).", file=sys.stderr)
    block = f"\n\n## Ответ оркестратора ({ts})\n{answer}\n\n{tail}"
    if dry_run:
        print(f"[dry-run:respond:{name}] would append {len(block)} chars to "
              f"{msg_path.name} and re-spawn.")
        return 0
    # Stop any lingering process/window first, then append + re-spawn.
    _stop_worker(name)
    with msg_path.open("a", encoding="utf-8") as f:
        f.write(block)
    _archive_answer(name, answer, ts)
    print(f"[respond:{name}] answer appended; re-spawning worker...")
    return cmd_spawn([name], dry_run=False, max_concurrent=DEFAULT_MAX_CONCURRENT,
                     allow_over_cap=True, perm=perm, model=model)


# ─── transcript discovery + summary ─────────────────────────────────────────────


def _find_worker_transcript(name: str) -> Path | None:
    """Путь к JSONL воркера. Сначала — ДЕТЕРМИНИРОВАННО: мы сами назначили сессии uuid при
    спавне (--session-id), а CLI кладёт транскрипт файлом `<session-id>.jsonl`. Имя файла
    уникально, поэтому ищем ОДНИМ glob по каталогам проектов — без вычисления имени каталога.

    Правило слага каталога (как CLI превращает путь в имя папки) не документировано; выводить
    его реверс-инжинирингом значило бы построить «детерминированный» путь на самом хрупком
    звене: смена правила молча вернула бы нас к сканированию десятков чужих транскриптов.

    Фолбэк-скан ниже — только для воркеров, спавненных до появления session_id: матчим по полю
    `cwd` (== worktree) или по уникальному scope-маркеру в первом user-сообщении."""
    session_id = _get_worker_state(name).get("session_id")
    if session_id:
        direct = next(CLAUDE_PROJECTS_DIR.glob(f"*/{session_id}.jsonl"), None)
        if direct is not None:
            return direct
    wt_key = _norm(_worktree_path(name))
    scope_marker = f"coordination/{name}-scope.md"
    if not CLAUDE_PROJECTS_DIR.is_dir():
        return None
    candidates = sorted(
        CLAUDE_PROJECTS_DIR.glob("*/*.jsonl"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )[:MAX_TRANSCRIPTS_TO_SCAN]
    for p in candidates:
        try:
            with p.open("r", encoding="utf-8", errors="replace") as f:
                first_user = ""
                for i, raw in enumerate(f):
                    if i > 60:
                        break
                    try:
                        d = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    cwd = d.get("cwd") or ""
                    if cwd and _norm(cwd) == wt_key:
                        return p
                    if d.get("type") == "user" and not first_user:
                        msg = d.get("message", {})
                        content = msg.get("content") if isinstance(msg, dict) else msg
                        if isinstance(content, str):
                            first_user = content
                        elif isinstance(content, list):
                            first_user = " ".join(
                                b.get("text", "") for b in content
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                        if scope_marker in first_user:
                            return p
        except OSError:
            continue
    return None


@dataclass
class TranscriptSummary:
    total_lines: int
    last_activity_ts: float
    recent_excerpt: str
    recent_tools: list[str]


def _summarize_transcript(path: Path, max_tools: int = 5) -> TranscriptSummary:
    last_ts = 0.0
    excerpt = ""
    tools: list[str] = []
    total = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                total += 1
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_ts(d.get("timestamp") or "")
                if ts:
                    last_ts = max(last_ts, ts)
                if d.get("type") == "assistant":
                    msg = d.get("message", {})
                    content = msg.get("content") if isinstance(msg, dict) else None
                    if isinstance(content, list):
                        for blk in content:
                            if not isinstance(blk, dict):
                                continue
                            if blk.get("type") == "text":
                                excerpt = (blk.get("text", "") or "")[:200]
                            elif blk.get("type") == "tool_use":
                                tools.append(blk.get("name", "?"))
                                if len(tools) > max_tools:
                                    tools.pop(0)
    except OSError:
        pass
    return TranscriptSummary(total, last_ts, excerpt.replace("\n", " ").strip(), tools)


# ─── git state + classification ─────────────────────────────────────────────────


@dataclass
class WorkerGitState:
    branch: str
    commits_ahead: int
    last_commit_sha: str
    last_commit_age_sec: float
    uncommitted_count: int
    has_status_file: bool
    status_state: str | None


_STATE_KEYWORDS = (
    "needs-orchestrator-answer", "needs orchestrator answer",
    "complete", "verified", "blocked", "spawned",
)


def _parse_status_state(text: str) -> str | None:
    if not text:
        return None
    head = text[:2000]
    # Loud banner first (canonical): a line "STATE: X".
    m = re.search(r"STATE:\s*([A-Z\-]+)", head)
    if m:
        return m.group(1).upper()
    for line in head.splitlines()[:40]:
        low = line.lower()
        if "state" not in low and "status" not in low:
            continue
        for kw in _STATE_KEYWORDS:
            if kw in low:
                return kw.upper().replace(" ", "-")
    return None


def _read_status_text(name: str, wt: Path, branch: str) -> str:
    # branch tree -> working tree -> main checkout coordination/
    txt = _git(["show", f"{branch}:coordination/{name}-status.md"], cwd=wt)
    if txt:
        return txt
    for cand in (_status_path_in_worktree(name, wt),
                 COORD_DIR / f"{name}-status.md"):
        if cand.is_file():
            try:
                return cand.read_text(encoding="utf-8")
            except OSError:
                pass
    return ""


def _worker_git_state(name: str) -> WorkerGitState | None:
    wt = _worktree_path(name)
    if not wt.is_dir():
        return None
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt) or name
    ahead = _git(["rev-list", "--count", f"{BASE_BRANCH}..{branch}"], cwd=wt)
    last_log = _git(["log", "-1", "--format=%h%x09%ct", branch], cwd=wt)
    if last_log and "\t" in last_log:
        sha, ts = last_log.split("\t", 1)
        last_sha, last_ts = sha, float(ts) if ts.strip().isdigit() else 0.0
    else:
        last_sha, last_ts = "", 0.0
    uncommitted = _git(["status", "--short"], cwd=wt)
    uc = len([ln for ln in uncommitted.splitlines() if ln.strip()])
    status_text = _read_status_text(name, wt, branch)
    return WorkerGitState(
        branch=branch,
        commits_ahead=int(ahead) if ahead.isdigit() else 0,
        last_commit_sha=last_sha,
        last_commit_age_sec=(time.time() - last_ts) if last_ts else 0.0,
        uncommitted_count=uc,
        has_status_file=bool(status_text),
        status_state=_parse_status_state(status_text),
    )


def _classify(g: WorkerGitState | None, s: TranscriptSummary | None) -> str:
    if not g:
        return "💀 DEAD"
    st = (g.status_state or "").upper()
    if "COMPLETE" in st or "VERIFIED" in st:
        return "✅ COMPLETE"
    if "NEEDS-ORCHESTRATOR-ANSWER" in st or "NEEDS-ANSWER" in st:
        return "🟠 NEEDS-ANSWER"
    if "BLOCKED" in st:
        return "❌ BLOCKED"
    if not s or not s.last_activity_ts:
        return "❓ NO-TRANSCRIPT"
    age = time.time() - s.last_activity_ts
    if age <= 300:
        return "🟢 LIVE"
    if age <= 1800:
        return "🟡 IDLE"
    return "🔴 STALE"


def _status_row(name: str) -> dict:
    g = _worker_git_state(name)
    t = _find_worker_transcript(name)
    s = _summarize_transcript(t) if t else None
    return {"name": name, "git": g, "summary": s, "state": _classify(g, s)}


# ─── status / tail ──────────────────────────────────────────────────────────────


def cmd_status(names: list[str]) -> int:
    names = names or _list_available()
    if not names:
        print("(no workers configured — create coordination/first-msgs/<name>.md)")
        return 0
    cols = [("Name", 28), ("State", 16), ("Activity", 11),
            ("Ahead", 6), ("Uncommitted", 12), ("Recent tools", 24)]
    header = "  ".join(c.ljust(w) for c, w in cols)
    print(header)
    print("-" * len(header))
    counts: dict[str, int] = {}
    # Один _status_row на воркера (каждый сканит до 80 JSONL-транскриптов) — раньше
    # звали дважды на воркера ради "done" ниже, на 10 воркерах = 20 полных сканов каталога.
    rows = [_status_row(name) for name in names]
    for r in rows:
        name = r["name"]
        g, s, state = r["git"], r["summary"], r["state"]
        counts[state] = counts.get(state, 0) + 1
        activity = _human_age(s.last_activity_ts) if (s and s.last_activity_ts) else "—"
        ahead = f"+{g.commits_ahead}" if g else "—"
        unc = str(g.uncommitted_count) if g else "—"
        tools = ",".join(s.recent_tools[-3:]) if s and s.recent_tools else "—"
        print(f"{name[:28]:<28}  {state:<16}  {activity:<11}  "
              f"{ahead:<6}  {unc:<12}  {tools[:24]:<24}")
    print("-" * len(header))
    print("Total: " + str(len(names)) + "  |  "
          + "  ".join(f"{k}:{v}" for k, v in sorted(counts.items())))
    # LOUD reminder: COMPLETE workers not yet integrated.
    done = [r["name"] for r in rows if "COMPLETE" in r["state"]
            and _worktree_path(r["name"]).is_dir()]
    if done:
        print("\n⚠️  COMPLETE и не интегрированы: " + ", ".join(done))
        print("    integrate: python spawn_workers.py integrate <name>")
    return 0


def cmd_tail(name: str, n: int) -> int:
    t = _find_worker_transcript(name)
    if not t:
        print(f"(no transcript for '{name}' — is its window running claude?)")
        return 1
    print(f"=== tail: {name} ({t.name}) ===")
    keep: list[str] = []
    try:
        with t.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") not in ("assistant", "user"):
                    continue
                age = _human_age(_parse_ts(d.get("timestamp") or "")) or "?"
                msg = d.get("message", {})
                if d["type"] == "user":
                    content = msg.get("content") if isinstance(msg, dict) else msg
                    text = content if isinstance(content, str) else " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ) if isinstance(content, list) else ""
                    text = text.strip().replace("\n", " ")[:200]
                    if text:
                        keep.append(f"[{age}] USER: {text}")
                else:
                    content = msg.get("content", []) if isinstance(msg, dict) else []
                    for blk in content if isinstance(content, list) else []:
                        if not isinstance(blk, dict):
                            continue
                        if blk.get("type") == "text":
                            tx = (blk.get("text", "") or "").strip().replace("\n", " ")[:200]
                            if tx:
                                keep.append(f"[{age}] CLAUDE: {tx}")
                        elif blk.get("type") == "tool_use":
                            inp = blk.get("input", {})
                            hint = ""
                            if isinstance(inp, dict):
                                for k in ("file_path", "command", "pattern", "description"):
                                    if isinstance(inp.get(k), str):
                                        hint = f" {k}={inp[k][:100]}"
                                        break
                            keep.append(f"[{age}] TOOL: {blk.get('name', '?')}{hint}")
    except OSError as e:
        print(f"(read error: {e})")
        return 1
    for line in keep[-n:]:
        print(line)
    return 0


# ─── fleet memory: DISTILL (auto-harvest worker-discovered pitfalls) ────────────

PITFALLS_SIZE_WARN = 9000  # injected into EVERY prompt — warn past this to prune.


def _extract_pitfalls_section(status_text: str) -> list[str]:
    """Pull entries from a worker's `## PITFALLS-DISCOVERED` status section.
    Each `-`/`*`/`N.` bullet (with its continuation lines) becomes one entry.
    Returns [] if the section is absent."""
    if not status_text:
        return []
    out: list[str] = []
    cur = ""
    in_sec = False
    for ln in status_text.splitlines():
        stripped = ln.strip()
        if stripped.startswith("#"):  # any header toggles section membership
            if cur.strip():
                out.append(cur.strip())
                cur = ""
            in_sec = "pitfalls-discovered" in stripped.lower().replace(" ", "-")
            continue
        if not in_sec:
            continue
        if re.match(r"[-*]\s+|\d+[.)]\s+", stripped):  # new bullet
            if cur.strip():
                out.append(cur.strip())
            cur = re.sub(r"^[-*]\s+|^\d+[.)]\s+", "", stripped)
        elif stripped:  # continuation of the current bullet
            cur = (cur + " " + stripped).strip()
    if cur.strip():
        out.append(cur.strip())
    return [e for e in out if len(e) > 8]


def _pitfall_sig(s: str) -> str:
    """Dedup signature: lowercased alphanumerics (RU+EN), first 60 chars."""
    return re.sub(r"[^0-9a-zа-яё]+", "", s.lower())[:60]


def _harvest_pitfalls(name: str, status_text: str) -> int:
    """Append worker-discovered pitfalls to the fleet memory file, deduped against
    what's already there. Best-effort — never raises into integrate. Returns the
    number of NEW entries written."""
    entries = _extract_pitfalls_section(status_text)
    if not entries:
        return 0
    try:
        existing = PITFALLS_FILE.read_text(encoding="utf-8") if PITFALLS_FILE.is_file() else ""
    except OSError:
        existing = ""
    existing_sigs = {_pitfall_sig(line) for line in existing.splitlines() if line.strip()}
    new: list[str] = []
    for e in entries:
        sig = _pitfall_sig(e)
        if sig and sig not in existing_sigs:
            new.append(e)
            existing_sigs.add(sig)
    if not new:
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    block = (f"\n## Авто-добавлено воркером {name} ({stamp})\n\n"
             + "".join(f"- {e}\n" for e in new))
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        with PITFALLS_FILE.open("a", encoding="utf-8") as f:
            f.write(block)
    except OSError as e:
        print(f"[integrate:{name}] warn: could not write pitfalls: {e}", file=sys.stderr)
        return 0
    return len(new)


def cmd_pitfalls_distill(prune: bool, dry_run: bool) -> int:
    """Анализ и КОНСЕРВАТИВНАЯ чистка pitfalls.md (вшивается в каждый промпт). По
    умолчанию — только отчёт (размер, записи, дубли). С --prune-dupes удаляет ТОЛЬКО
    записи-дубли внутри авто-блоков (## Авто-добавлено …); курируемые секции и
    преамбулу не трогает."""
    if not PITFALLS_FILE.is_file():
        print("pitfalls.md не найден", file=sys.stderr)
        return 1
    lines = PITFALLS_FILE.read_text(encoding="utf-8").splitlines()
    seen: dict[str, int] = {}
    total = 0
    dup_lines: list[int] = []
    dup_preview: list[str] = []
    in_auto = False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("## "):
            in_auto = "авто-добавлено" in s.lower()
            continue
        m = re.match(r"(?:[-*]\s+|\d+[.)]\s+)(.+)", s)
        if not m:
            continue
        sig = _pitfall_sig(m.group(1))
        if not sig:
            continue
        total += 1
        if sig in seen:
            if in_auto:
                dup_lines.append(i)
                dup_preview.append(m.group(1).strip())
        else:
            seen[sig] = i
    size = sum(len(ln.encode("utf-8")) + 1 for ln in lines)
    print(f"pitfalls.md: {size} байт · {total} записей · {len(seen)} уникальных · "
          f"{len(dup_lines)} дублей в авто-блоках")
    if size > PITFALLS_SIZE_WARN:
        print(f"  ⚠ > {PITFALLS_SIZE_WARN} байт — вшивается в КАЖДЫЙ промпт воркера")
    for e in dup_preview[:15]:
        print(f"  dup: {e[:80]}")
    if not dup_lines:
        print("  дублей-кандидатов нет.")
        return 0
    if not prune:
        print("  → --prune-dupes удалит эти дубли (курируемые секции не трогаются)")
        return 0
    drop = set(dup_lines)
    kept = [ln for i, ln in enumerate(lines) if i not in drop]
    if dry_run:
        print(f"  [dry-run] удалил бы {len(drop)} строк-дублей")
        return 0
    PITFALLS_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"  ✓ удалено {len(drop)} дублей из авто-блоков. Закоммить при желании.")
    return 0


# ─── integrate ──────────────────────────────────────────────────────────────────


def _auto_commit_status(name: str, wt: Path) -> None:
    rel = f"coordination/{name}-status.md"
    if not (wt / rel).is_file():
        return
    if _git(["ls-files", "--error-unmatch", rel], cwd=wt):
        return  # already tracked
    if not _git(["status", "--short", rel], cwd=wt).strip():
        return
    _git(["add", "--", rel], cwd=wt)
    _git_run(["commit", "-q", "-m",
              f"docs(coordination): commit forgotten status for {name}"], cwd=wt)
    print(f"[integrate:{name}] auto-committed forgotten status file.")


def _run_smoke() -> tuple[bool, str]:
    """Boot-smoke: import the app entrypoint on in-memory SQLite (per CLAUDE.md
    dev recipe). Best-effort signal that merged code still imports."""
    if not VENV_PY.is_file():
        return True, f"(skipped — {VENV_PY} not found)"
    env = dict(os.environ)
    env["AIOS_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [str(VENV_PY), "-c", "import main; print('imports ok')"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, check=False,
    )
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out


def cmd_integrate(name: str, dry_run: bool) -> int:
    wt = _worktree_path(name)
    if not wt.is_dir():
        print(f"no worktree {wt}", file=sys.stderr)
        return 1
    branch = name
    _auto_commit_status(name, wt)
    g = _worker_git_state(name)
    if g and g.uncommitted_count:
        print(f"⚠ worker {name} has {g.uncommitted_count} uncommitted file(s); "
              f"refuse to integrate.", file=sys.stderr)
        print(_git(["status", "--short"], cwd=wt), file=sys.stderr)
        return 1
    if g and g.status_state:
        st = g.status_state.upper()
        if "BLOCKED" in st or "NEEDS" in st:
            print(f"⚠ worker {name} status is '{g.status_state}' — refuse to integrate.",
                  file=sys.stderr)
            return 1
        if "COMPLETE" not in st and "VERIFIED" not in st:
            print(f"⚠ worker {name} status '{g.status_state}' not COMPLETE — refuse.",
                  file=sys.stderr)
            return 1
    cur = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT)
    if cur != BASE_BRANCH:
        print(f"⚠ main checkout on '{cur}', not '{BASE_BRANCH}'. Checkout {BASE_BRANCH} first.",
              file=sys.stderr)
        return 1
    unique = [s for s in _git(
        ["log", "--reverse", "--format=%H", f"{BASE_BRANCH}..{branch}"], cwd=REPO_ROOT
    ).splitlines() if s.strip()]
    if dry_run:
        print(f"[dry-run:integrate:{name}] would merge {len(unique)} commit(s) into "
              f"{BASE_BRANCH}, run smoke, write report.")
        return 0
    if not unique:
        print(f"[integrate:{name}] no commits ahead of {BASE_BRANCH} — nothing to merge.",
              file=sys.stderr)
        return 1

    # ACCEPTANCE GATE (durable machine-checkable JSON). If the worker has a gate
    # file, it must be GREEN before we touch main. acceptance_gate.py RE-RUNS the
    # objective checks (ruff/tsc/pytest), so a worker's optimistic passes:true
    # cannot survive a failing command — the guard against hallucinated "done".
    # Workers without a gate file are not blocked (backward-compatible).
    gate_file = COORD_DIR / "acceptance" / f"{name}.json"
    if gate_file.is_file():
        gate = subprocess.run(
            [sys.executable, str(REPO_ROOT / "acceptance_gate.py"), "check", name],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace",  # вывод гейта русский и его тут же печатают
        )
        if gate.stdout:
            print(gate.stdout.rstrip())
        if gate.returncode != 0:
            if gate.stderr:
                print(gate.stderr.rstrip(), file=sys.stderr)
            print(f"⚠ worker {name}: acceptance gate RED — refuse to integrate.",
                  file=sys.stderr)
            return 1
        print(f"[integrate:{name}] acceptance gate GREEN ✓")
    else:
        print(f"[integrate:{name}] no acceptance gate "
              f"(coordination/acceptance/{name}.json); skipping machine gate. "
              f"Seed one with acceptance_gate.py init to enforce objective checks.",
              file=sys.stderr)

    method = "merge"
    proc = _git_run(["merge", "--no-ff", branch, "-m",
                     f"Merge worker {name} -> {BASE_BRANCH} (orchestrator)"], cwd=REPO_ROOT)
    if proc.returncode != 0:
        _git_run(["merge", "--abort"], cwd=REPO_ROOT)
        print(f"[integrate:{name}] merge conflicted — falling back to cherry-pick...")
        method = "cherry-pick"
        cp = _git_run(["cherry-pick"] + unique, cwd=REPO_ROOT)
        if cp.returncode != 0:
            _git_run(["cherry-pick", "--abort"], cwd=REPO_ROOT)
            print(f"[integrate:{name}] cherry-pick also conflicted. Manual resolution "
                  f"needed.\n{cp.stderr}", file=sys.stderr)
            return 1
        print(f"[integrate:{name}] cherry-picked {len(unique)} commit(s).")
    else:
        print(f"[integrate:{name}] merged {len(unique)} commit(s).")

    smoke_ok, smoke_out = _run_smoke()
    print(f"[integrate:{name}] smoke: {'OK ✓' if smoke_ok else 'FAILED ✗'}")
    if not smoke_ok:
        print(smoke_out, file=sys.stderr)
        print("  (to undo: git reset --hard HEAD~1)", file=sys.stderr)

    # DISTILL (auto): harvest worker-discovered pitfalls into fleet memory + commit.
    harvested = _harvest_pitfalls(name, _read_status_text(name, wt, branch))
    if harvested:
        rel = "coordination/memory/pitfalls.md"
        _git(["add", "--", rel], cwd=REPO_ROOT)
        _git_run(["commit", "-q", "-m",
                  f"chore(memory): harvest {harvested} pitfall(s) from {name}"], cwd=REPO_ROOT)
        print(f"[integrate:{name}] memory: +{harvested} pitfall(s) harvested -> {rel}")
        try:
            size = PITFALLS_FILE.stat().st_size
        except OSError:
            size = 0
        if size > PITFALLS_SIZE_WARN:
            print(f"[integrate:{name}] ⚠ pitfalls.md is {size} bytes (injected into EVERY "
                  f"prompt) — consider pruning stale entries.", file=sys.stderr)

    _clear_worker_state(name)
    _write_report(name, wt, branch, unique, method, smoke_ok, smoke_out)
    print(f"[integrate:{name}] done. Close the worker window; then "
          f"`cleanup {name}` to remove the worktree.")
    return 0 if smoke_ok else 1


def _complete_workers() -> list[str]:
    """Воркеры с живым worktree и статусом COMPLETE/VERIFIED — кандидаты на интеграцию."""
    out: list[str] = []
    for n in _list_available():
        if not _worktree_path(n).is_dir():
            continue
        g = _worker_git_state(n)
        st = (g.status_state or "").upper() if g else ""
        if "COMPLETE" in st or "VERIFIED" in st:
            out.append(n)
    return out


def cmd_integrate_all(dry_run: bool) -> int:
    """Батч-интеграция всех COMPLETE-воркеров по очереди. Каждый проходит тот же
    acceptance-гейт + smoke, что и одиночный integrate — красные не сливаются."""
    workers = _complete_workers()
    if not workers:
        print("[integrate --all-complete] нет воркеров в COMPLETE.", file=sys.stderr)
        return 1
    print(f"[integrate --all-complete] кандидаты ({len(workers)}): {', '.join(workers)}")
    ok: list[str] = []
    failed: list[str] = []
    for n in workers:
        print(f"\n===== integrate {n} =====")
        rc = cmd_integrate(n, dry_run)
        (ok if rc == 0 else failed).append(n)
    print(f"\n[integrate --all-complete] итог: {len(ok)} ok, {len(failed)} fail "
          f"(из {len(workers)}).")
    if ok:
        print(f"  ok:   {', '.join(ok)}")
    if failed:
        print(f"  fail: {', '.join(failed)}")
    return 0 if not failed else 1


def _write_report(name: str, wt: Path, branch: str, unique: list[str],
                  method: str, smoke_ok: bool, smoke_out: str) -> None:
    files = sorted({f.strip() for f in _git(
        ["show", "--format=", "--name-only"] + unique, cwd=wt).splitlines() if f.strip()
    }) if unique else []
    subjects = _git(["log", "--format=- %h %s",
                     f"{BASE_BRANCH}..{branch}"], cwd=wt) if unique else "(none)"
    report = (
        f"=== WORKER REPORT: {name} ===\n"
        f"Branch:       {branch}\n"
        f"Integration:  {method} ({len(unique)} commit(s))\n"
        f"Smoke:        {'imports ok ✓' if smoke_ok else 'FAILED — ' + smoke_out[:200]}\n"
        f"Files:        {len(files)}\n"
        + "".join(f"  - {f}\n" for f in files[:30])
        + f"\nCommits:\n{subjects}\n=== END REPORT ==="
    )
    print("\n" + report)
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (REPORTS_DIR / f"{ts}_{name}.md").write_text(report + "\n", encoding="utf-8")
    except OSError:
        pass


# ─── cleanup ────────────────────────────────────────────────────────────────────


def _fully_merged(branch: str) -> bool:
    return not _git(["log", "--format=%H", f"{BASE_BRANCH}..{branch}"], cwd=REPO_ROOT).strip()


def cmd_cleanup(names: list[str], dry_run: bool) -> int:
    available = _list_available()
    if not names:
        names = [n for n in available
                 if _worktree_path(n).is_dir() and _fully_merged(n)
                 and (_worker_git_state(n) or WorkerGitState("", 0, "", 0, 0, False, None)).status_state
                 and "COMPLETE" in ((_worker_git_state(n).status_state or "").upper())]
    if not names:
        print("(nothing to clean — auto-pick needs COMPLETE status + fully-merged branch)")
        return 0
    print(f"cleanup will retire: {', '.join(names)}")
    cleaned, skipped = [], []
    for name in names:
        wt = _worktree_path(name)
        if not _fully_merged(name):
            print(f"[cleanup:{name}] SKIP: branch has commits not in {BASE_BRANCH}. "
                  f"Run integrate first.", file=sys.stderr)
            skipped.append(name)
            continue
        if dry_run:
            print(f"  [dry-run] stop worker + git worktree remove {wt} && git branch -d {name}")
            continue
        # Close the worker's window / kill any lingering process first.
        if _stop_worker(name):
            print(f"[cleanup:{name}] worker process stopped + window closed.")
        if wt.is_dir():
            rm = _git_run(["worktree", "remove", "--force", str(wt)], cwd=REPO_ROOT)
            if rm.returncode != 0:
                print(f"[cleanup:{name}] worktree remove failed: {rm.stderr.strip()}",
                      file=sys.stderr)
                skipped.append(name)
                continue
            print(f"[cleanup:{name}] worktree removed.")
        br = _git_run(["branch", "-d", name], cwd=REPO_ROOT)
        if br.returncode == 0:
            print(f"[cleanup:{name}] branch deleted.")
        else:
            print(f"[cleanup:{name}] branch delete warn: {br.stderr.strip()}", file=sys.stderr)
        _clear_worker_state(name)
        cleaned.append(name)
    if not dry_run:
        print(f"\ncleaned: {', '.join(cleaned) or '—'}  |  skipped: {', '.join(skipped) or '—'}")
    return 0 if not skipped else 1


# ─── health ─────────────────────────────────────────────────────────────────────


def cmd_health() -> int:
    checks: list[tuple[str, bool, str]] = []
    cli = _find_claude_cli()
    checks.append(("claude CLI", bool(cli), cli or "NOT FOUND — set $CLAUDE_CLI"))
    # Версия резолвнутого бинаря: на машине есть ВТОРОЙ, устаревший claude.exe
    # (C:/Users/aidzm/.local/bin/claude.exe, 2.1.173) — если PATH подхватит его вместо
    # актуального, manual/--forward-subagent-text на вложенных сабагентах не заработают.
    cli_version = ""
    version_ok = False
    if cli:
        try:
            vproc = subprocess.run([cli, "--version"], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", check=False, timeout=10)
            cli_version = (vproc.stdout or vproc.stderr).strip()
            # bool(cli_version) недостаточно: except ниже тоже кладёт непустую строку,
            # и реальный сбой получения версии показывался бы зелёной галочкой.
            version_ok = vproc.returncode == 0 and bool(cli_version)
        except (OSError, subprocess.TimeoutExpired) as e:
            cli_version = f"err: {e}"
    checks.append(("claude --version", version_ok,
                   f"{cli_version} (режим manual — с 2.1.200; проброс текста ВЛОЖЕННЫХ "
                   f"сабагентов через --forward-subagent-text — с 2.1.219)"
                   if version_ok else (cli_version or "не удалось получить версию")))
    gw = _git_run(["worktree", "list"], cwd=REPO_ROOT)
    checks.append(("git worktree", gw.returncode == 0,
                   f"{len(gw.stdout.splitlines())} worktree(s)" if gw.returncode == 0 else gw.stderr.strip()))
    checks.append((".venv python", VENV_PY.is_file(),
                   str(VENV_PY) if VENV_PY.is_file() else "MISSING — smoke will skip"))
    cur = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT)
    checks.append((f"on {BASE_BRANCH}", cur == BASE_BRANCH,
                   f"on '{cur}'" if cur == BASE_BRANCH else f"on '{cur}' — integrate refuses"))
    checks.append(("first-msgs dir", FIRST_MSG_DIR.is_dir(),
                   str(FIRST_MSG_DIR) if FIRST_MSG_DIR.is_dir() else "MISSING"))
    checks.append(("standards doc", STANDARDS_DOC.is_file(),
                   str(STANDARDS_DOC) if STANDARDS_DOC.is_file() else "MISSING"))
    from shutil import which
    wt_ok = bool(which("wt.exe") or which("wt"))
    checks.append(("wt.exe (Windows Terminal)", wt_ok,
                   "found" if wt_ok else "not found — will use plain console windows"))
    try:
        WORKERS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        st = _load_state()
        checks.append(("state file", True, f"{len(st)} entries" if st else "empty"))
    except Exception as e:
        checks.append(("state file", False, f"err: {e}"))

    print("=== spawn_workers HEALTH (Windows) ===")
    all_ok = True
    for label, ok, detail in checks:
        # wt.exe + .venv + version-lookup are non-fatal
        fatal = label not in ("wt.exe (Windows Terminal)", ".venv python", f"on {BASE_BRANCH}",
                              "claude --version")
        print(f"  {'✓' if ok else '✗'}  {label:30s}  {detail}")
        if not ok and fatal:
            all_ok = False
    print()
    print("READY." if all_ok else "NOT READY — fix the ✗ items above.")
    return 0 if all_ok else 1


# ─── CLI ────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    # Russian-locale Windows consoles default to cp1251, which can't encode the
    # status emoji/checkmarks. Emit UTF-8 (Windows Terminal renders it fine).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    p = argparse.ArgumentParser(prog="spawn_workers",
                                description="Windows orchestrator for parallel Claude workers.")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("spawn", help="create worktree(s) + launch worker window(s)")
    sp.add_argument("names", nargs="*")
    sp.add_argument("--all", action="store_true", help="spawn every worker with a first-msg")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--perm", default=DEFAULT_PERMISSION_MODE,
                    # CC 2.1.200 переименовал режим "default" в "manual". Старое имя
                    # ПРОДОЛЖАЕТ приниматься CLI как алиас (проверено на 2.1.219: оно просто
                    # не показывается в --help), поэтому оставляем его в choices ради обратной
                    # совместимости со старыми скриптами и текстами — но нормализуем в manual,
                    # чтобы в лаунчер и в логи уходило одно каноническое имя.
                    choices=["auto", "acceptEdits", "bypassPermissions", "manual", "default",
                             "dontAsk", "plan"],
                    help=f"claude --permission-mode (default {DEFAULT_PERMISSION_MODE})")
    sp.add_argument("--model", default=DEFAULT_WORKER_MODEL,
                    help=f"claude --model for workers (default {DEFAULT_WORKER_MODEL}; "
                         f"use 'inherit' for the account default)")
    sp.add_argument("--budget-usd", default=DEFAULT_WORKER_BUDGET_USD, dest="budget_usd",
                    help=f"claude --max-budget-usd per worker (default {DEFAULT_WORKER_BUDGET_USD}; "
                         f"'0'/'off' disables the flag)")
    sp.add_argument("--max-concurrent", type=int, default=DEFAULT_MAX_CONCURRENT)
    sp.add_argument("--allow-over-cap", action="store_true")

    st = sub.add_parser("status", help="status table across workers")
    st.add_argument("names", nargs="*")

    tl = sub.add_parser("tail", help="recent transcript entries for one worker")
    tl.add_argument("name")
    tl.add_argument("-n", type=int, default=20)

    ig = sub.add_parser("integrate", help=f"merge worker branch -> {BASE_BRANCH} + smoke + report")
    ig.add_argument("name", nargs="?")
    ig.add_argument("--all-complete", action="store_true",
                    help="integrate every COMPLETE worker (each gated) instead of one name")
    ig.add_argument("--dry-run", action="store_true")

    pd = sub.add_parser("pitfalls-distill",
                        help="отчёт по pitfalls.md + чистка дублей в авто-блоках")
    pd.add_argument("--prune-dupes", action="store_true",
                    help="удалить дубли из авто-блоков (курируемое не трогает)")
    pd.add_argument("--dry-run", action="store_true")

    cl = sub.add_parser("cleanup", help="retire fully-merged workers (stop+close window, remove worktree + branch)")
    cl.add_argument("names", nargs="*")
    cl.add_argument("--dry-run", action="store_true")

    so = sub.add_parser("stop", help="kill a worker's process tree + close its window (keeps worktree+branch)")
    so.add_argument("name")

    rs = sub.add_parser("respond", help="answer a NEEDS-ORCHESTRATOR-ANSWER worker: resume its session (fallback: re-spawn)")
    rs.add_argument("name")
    rs.add_argument("answer", help="the orchestrator's answer/clarification text")
    rs.add_argument("--dry-run", action="store_true")
    rs.add_argument("--perm", default=DEFAULT_PERMISSION_MODE,
                    choices=["auto", "acceptEdits", "bypassPermissions", "manual", "dontAsk", "plan"])
    rs.add_argument("--model", default=DEFAULT_WORKER_MODEL,
                    help=f"claude --model for the resumed/re-spawned worker "
                         f"(default {DEFAULT_WORKER_MODEL})")

    sub.add_parser("health", help="preflight check")
    sub.add_parser("list", help="list known workers")

    args = p.parse_args(argv)
    if args.cmd is None:
        p.print_help()
        return 1
    # "default" -> "manual": CLI принимает оба, но каноническое имя с CC 2.1.200 — manual.
    # Нормализуем в одной точке, чтобы в лаунчер, логи и state уходило одно значение.
    if getattr(args, "perm", None) == "default":
        args.perm = "manual"
    if args.cmd == "list":
        for n in _list_available():
            print(n)
        return 0
    if args.cmd == "health":
        return cmd_health()
    if args.cmd == "status":
        return cmd_status(args.names)
    if args.cmd == "tail":
        return cmd_tail(args.name, args.n)
    if args.cmd == "integrate":
        if args.all_complete:
            return cmd_integrate_all(args.dry_run)
        if not args.name:
            print("integrate: укажи <name> или --all-complete", file=sys.stderr)
            return 1
        return cmd_integrate(args.name, args.dry_run)
    if args.cmd == "pitfalls-distill":
        return cmd_pitfalls_distill(args.prune_dupes, args.dry_run)
    if args.cmd == "cleanup":
        return cmd_cleanup(args.names, args.dry_run)
    if args.cmd == "stop":
        return cmd_stop(args.name)
    if args.cmd == "respond":
        return cmd_respond(args.name, args.answer, args.dry_run, args.perm, args.model)
    if args.cmd == "spawn":
        names = _list_available() if args.all else args.names
        if not names:
            print("spawn: provide worker name(s) or --all", file=sys.stderr)
            return 1
        return cmd_spawn(names, args.dry_run, args.max_concurrent,
                         args.allow_over_cap, args.perm, args.model, args.budget_usd)
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
