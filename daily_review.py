#!/usr/bin/env python3
"""daily_review.py — авто-сессия ретроспективы дня (для Windows Task Scheduler, 23:59).

Открывает ВИДИМОЕ окно с headless `claude -p`, который читает транскрипты/логи за день и
пишет отчёт `coordination/daily-review/<дата>.md` (паттерны: мои, агентов, взаимодействий).
Промпт — `coordination/daily-review-prompt.md` (правь его, не код).

БЕЗОПАСНОСТЬ: сессия read-only-аналитическая, ей НЕ нужен запуск команд. Поэтому режим —
`acceptEdits` (авто-запись отчёта, но Bash/shell НЕ исполняется), а НЕ bypassPermissions.
Единственное, что требует shell (git log за день), предсобирается ЭТИМ скриптом в
`coordination/.daily-review-data/commits-today.txt` — сессия читает это как файл.

  python daily_review.py            запустить ретроспективу (окно появится)
  python daily_review.py --dry-run  показать команду запуска, НЕ запуская
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from shutil import which

from spawn_workers import CLAUDE_PROJECTS_DIR, _find_claude_cli

ROOT = Path(__file__).resolve().parent
PROMPT_FILE = ROOT / "coordination" / "daily-review-prompt.md"
LAUNCHER = ROOT / "coordination" / ".daily-review-launcher.ps1"
DATA_DIR = ROOT / "coordination" / ".daily-review-data"
CREATE_NEW_CONSOLE = 0x00000010


def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _psq(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _gather() -> None:
    """Предсобрать данные, требующие shell (чтобы сессии НЕ нужен был Bash). Сейчас —
    коммиты за сегодня. Сессия прочитает результат как обычный файл."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            ["git", "log", "--since=midnight", "--all", "--stat"],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        (DATA_DIR / "commits-today.txt").write_text(r.stdout or "(коммитов за сегодня нет)",
                                                    encoding="utf-8")
    except Exception as e:  # noqa: BLE001 — предсбор не должен ронять запуск
        (DATA_DIR / "commits-today.txt").write_text(f"(git недоступен: {e})", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _utf8()
    argv = argv if argv is not None else sys.argv[1:]
    cli = _find_claude_cli()
    if not cli:
        print("claude CLI не найден (задай $CLAUDE_CLI или поставь Claude Code)", file=sys.stderr)
        return 1
    if not PROMPT_FILE.is_file():
        print(f"нет промпта {PROMPT_FILE}", file=sys.stderr)
        return 1

    # acceptEdits: отчёт пишется без подтверждений, но команды/Bash НЕ исполняются.
    claude_call = (
        f"& {_psq(cli)} --print --verbose --permission-mode acceptEdits "
        f"--add-dir {_psq(str(ROOT))} --add-dir {_psq(str(CLAUDE_PROJECTS_DIR))} "
        f"--model opus -- $prompt"
    )
    if "--dry-run" in argv:
        print("режим: acceptEdits (read-only анализ + запись отчёта; Bash не исполняется)")
        print("launch:", claude_call.replace("$prompt", "<daily-review-prompt.md>"))
        print(f"  cwd: {ROOT}")
        print(f"  --add-dir: {ROOT} ; {CLAUDE_PROJECTS_DIR}")
        return 0

    _gather()
    LAUNCHER.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n"
        "$OutputEncoding = [Text.Encoding]::UTF8\n"
        "$Host.UI.RawUI.WindowTitle = 'daily-review'\n"
        f"Set-Location -LiteralPath {_psq(str(ROOT))}\n"
        f"$prompt = Get-Content -Raw -Encoding UTF8 -LiteralPath {_psq(str(PROMPT_FILE))}\n"
        "Write-Host '=== ретроспектива дня (read-only): claude стартует ===' -ForegroundColor Cyan\n"
        f"{claude_call}\n"
        "Write-Host '=== готово: отчёт в coordination/daily-review/ ===' -ForegroundColor Yellow\n",
        encoding="utf-8-sig",
    )
    ps_args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(LAUNCHER)]
    wt = which("wt.exe") or which("wt")
    if wt:
        subprocess.Popen([wt, "new-tab", "--title", "daily-review", "powershell", *ps_args],
                         cwd=str(ROOT))
        method = "windows-terminal"
    else:
        subprocess.Popen(["powershell", *ps_args], creationflags=CREATE_NEW_CONSOLE)
        method = "new-console"
    print(f"ретроспектива запущена ({method}); отчёт ляжет в coordination/daily-review/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
