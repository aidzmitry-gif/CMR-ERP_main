#!/usr/bin/env python3
"""spawn_workers.py — Windows orchestrator for parallel Claude Code workers.

Rewritten for Windows 11 + PowerShell + this project (CRM ERP / AI-First OS).
The original (macOS / job_ghost_stalker, Terminal.app + osascript + GNU screen)
is preserved as spawn_workers.macos-reference.py.

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

# Permission mode for unattended workers. Workers run HEADLESS (claude --print):
# there's no human to approve tool calls, so they must never block on a
# permission prompt -> "bypassPermissions". Workers are isolated in their own
# git worktree. Override with --perm or $WORKER_PERMISSION_MODE.
DEFAULT_PERMISSION_MODE = os.environ.get("WORKER_PERMISSION_MODE", "bypassPermissions")

# Soft cap on concurrently-live workers (every concurrent claude draws the same
# account quota). Overridable with --max-concurrent / --allow-over-cap.
DEFAULT_MAX_CONCURRENT = int(os.environ.get("WORKER_MAX_CONCURRENT", "5"))

# Model for workers. Workers do scoped, well-specified implementation work
# (write a screen, a migration by the `sales` exemplar, tests) — Sonnet handles
# this at a fraction of Opus's token cost. Keep the orchestrator (this driver +
# the lead session you run by hand) on Opus where the planning judgement lives.
# Override per-run with --model, or globally with $WORKER_MODEL. Use "inherit"
# to drop the flag and let the worker use the account default.
DEFAULT_WORKER_MODEL = os.environ.get("WORKER_MODEL", "sonnet")

# How long to wait for a worker's JSONL transcript to appear after launch.
TRANSCRIPT_TIMEOUT_SEC = 75.0
# Cap how many transcripts we scan when discovering a worker session.
MAX_TRANSCRIPTS_TO_SCAN = 80


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


def _write_launcher(name: str, wt: Path, message: str, claude_cli: str,
                    perm: str, model: str) -> Path:
    """Write the per-worker prompt + PowerShell launcher. The launcher reads
    the (multi-line) prompt from a file and passes it as a single argv to
    claude — avoids all wt.exe / shell quoting hell."""
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    LAUNCHER_DIR.mkdir(parents=True, exist_ok=True)
    PID_DIR.mkdir(parents=True, exist_ok=True)
    if not EMPTY_MCP_FILE.exists():
        EMPTY_MCP_FILE.write_text('{"mcpServers": {}}\n', encoding="utf-8")

    prompt_file = PROMPT_DIR / f"{name}.txt"
    prompt_file.write_text(message, encoding="utf-8")
    launcher = LAUNCHER_DIR / f"{name}.ps1"
    pid_file = PID_DIR / f"{name}.pid"

    # Single-quote PowerShell literals; escape embedded single quotes by doubling.
    def psq(s: str) -> str:
        return "'" + str(s).replace("'", "''") + "'"

    # "inherit" => no --model flag => worker uses the account default model.
    model_flag = "" if model == "inherit" else f"--model {psq(model)} "

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
        f"$prompt = Get-Content -Raw -Encoding UTF8 -LiteralPath {psq(str(prompt_file))}\n"
        f"Write-Host '=== worker:{name} — claude (auto mode) starting ===' -ForegroundColor Cyan\n"
        f"& {psq(claude_cli)} --print --verbose --permission-mode {perm} "
        f"{model_flag}"
        f"--strict-mcp-config --mcp-config {psq(str(EMPTY_MCP_FILE))} "
        f"--add-dir {psq(str(REPO_ROOT))} "
        f"-- $prompt\n"
        "Write-Host ''\n"
        f"Write-Host '=== worker:{name} — claude finished (window kept open) ===' "
        "-ForegroundColor Yellow\n",
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
              allow_over_cap: bool, perm: str, model: str) -> int:
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
        print("⚠️  SECURITY: workers run with --permission-mode bypassPermissions "
              "(no command is blocked; worktree is not a sandbox). "
              "Use --perm acceptEdits/default to restrict, or sandbox the host.",
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
            if dry_run:
                wt = _worktree_path(name)
                exists = "exists" if wt.is_dir() else f"would create from {BASE_BRANCH}"
                print(f"[dry-run:spawn:{name}] worktree {wt} ({exists}); "
                      f"prompt {len(message)} chars (pitfalls {len(mem)}); "
                      f"perm={perm}; model={model}; cli={claude_cli}")
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
            launcher = _write_launcher(name, wt, message, claude_cli, perm, model)
            method = _launch_window(name, launcher)
            _set_worker_state(
                name,
                worktree=str(wt),
                spawned_at=datetime.now(timezone.utc).isoformat(),
                spawn_method=method,
                prompt_chars=len(message),
                launcher=str(launcher),
                pid_file=str(PID_DIR / f"{name}.pid"),
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


def cmd_respond(name: str, answer: str, dry_run: bool, perm: str, model: str) -> int:
    """Answer a worker that wrote NEEDS-ORCHESTRATOR-ANSWER. Headless workers
    exit when they need a decision, so 'answering' = append the orchestrator's
    answer to the worker's first-message and re-spawn it in the SAME worktree
    (its prior commits are preserved on the branch). The worker resumes with
    the answer + a pointer to its own status file."""
    msg_path = _first_msg_path(name)
    if not msg_path.is_file():
        print(f"[respond:{name}] no first-message at {msg_path}", file=sys.stderr)
        return 1
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    block = (
        f"\n\n## Ответ оркестратора ({ts})\n"
        f"{answer}\n\n"
        f"Продолжи с того места, где остановился: прочитай свой "
        f"coordination/{name}-status.md, учти ответ выше и доведи задачу до "
        f"STATE: COMPLETE.\n"
    )
    if dry_run:
        print(f"[dry-run:respond:{name}] would append {len(block)} chars to "
              f"{msg_path.name} and re-spawn.")
        return 0
    # Stop any lingering process/window first, then append + re-spawn.
    _stop_worker(name)
    with msg_path.open("a", encoding="utf-8") as f:
        f.write(block)
    # Record the answer for audit.
    try:
        ans_dir = COORD_DIR / "orchestrator-answers"
        ans_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (ans_dir / f"{stamp}_{name}.md").write_text(
            f"# Answer to {name} @ {ts}\n\n{answer}\n", encoding="utf-8")
    except OSError:
        pass
    print(f"[respond:{name}] answer appended; re-spawning worker...")
    return cmd_spawn([name], dry_run=False, max_concurrent=DEFAULT_MAX_CONCURRENT,
                     allow_over_cap=True, perm=perm, model=model)


# ─── transcript discovery + summary ─────────────────────────────────────────────


def _find_worker_transcript(name: str) -> Path | None:
    """Find this worker's JSONL by matching the `cwd` field (== worktree) or the
    unique scope-marker in the first user message. Scans ALL project dirs since
    the Windows project-slug is hard to predict from the path."""
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
    for name in names:
        r = _status_row(name)
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
    done = [n for n in names if "COMPLETE" in _status_row(n)["state"]
            and _worktree_path(n).is_dir()]
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
    existing_sigs = {_pitfall_sig(l) for l in existing.splitlines() if l.strip()}
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
        # wt.exe + .venv are non-fatal
        fatal = label not in ("wt.exe (Windows Terminal)", ".venv python", f"on {BASE_BRANCH}")
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
                    choices=["auto", "acceptEdits", "bypassPermissions", "default"],
                    help=f"claude --permission-mode (default {DEFAULT_PERMISSION_MODE})")
    sp.add_argument("--model", default=DEFAULT_WORKER_MODEL,
                    help=f"claude --model for workers (default {DEFAULT_WORKER_MODEL}; "
                         f"use 'inherit' for the account default)")
    sp.add_argument("--max-concurrent", type=int, default=DEFAULT_MAX_CONCURRENT)
    sp.add_argument("--allow-over-cap", action="store_true")

    st = sub.add_parser("status", help="status table across workers")
    st.add_argument("names", nargs="*")

    tl = sub.add_parser("tail", help="recent transcript entries for one worker")
    tl.add_argument("name")
    tl.add_argument("-n", type=int, default=20)

    ig = sub.add_parser("integrate", help=f"merge worker branch -> {BASE_BRANCH} + smoke + report")
    ig.add_argument("name")
    ig.add_argument("--dry-run", action="store_true")

    cl = sub.add_parser("cleanup", help="retire fully-merged workers (stop+close window, remove worktree + branch)")
    cl.add_argument("names", nargs="*")
    cl.add_argument("--dry-run", action="store_true")

    so = sub.add_parser("stop", help="kill a worker's process tree + close its window (keeps worktree+branch)")
    so.add_argument("name")

    rs = sub.add_parser("respond", help="answer a NEEDS-ORCHESTRATOR-ANSWER worker: append answer to its first-msg + re-spawn")
    rs.add_argument("name")
    rs.add_argument("answer", help="the orchestrator's answer/clarification text")
    rs.add_argument("--dry-run", action="store_true")
    rs.add_argument("--perm", default=DEFAULT_PERMISSION_MODE,
                    choices=["auto", "acceptEdits", "bypassPermissions", "default"])
    rs.add_argument("--model", default=DEFAULT_WORKER_MODEL,
                    help=f"claude --model for the re-spawned worker (default {DEFAULT_WORKER_MODEL})")

    sub.add_parser("health", help="preflight check")
    sub.add_parser("list", help="list known workers")

    args = p.parse_args(argv)
    if args.cmd is None:
        p.print_help()
        return 1
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
        return cmd_integrate(args.name, args.dry_run)
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
                         args.allow_over_cap, args.perm, args.model)
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
