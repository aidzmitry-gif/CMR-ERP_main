#!/usr/bin/env python3
"""claude_stop_hook.py — Stop: проверка качества тронутого за ход + строка статуса.

Когда Claude заканчивает ход, хук читает реестр тронутого за ход
(coordination/.touched-<session>.txt, который ведёт claude_quality_hook.py) и:

  • гоняет ruff по изменённым .py (точечно) — это БЛОКИРУЮЩИЙ гейт: при ошибках
    печатает их в stderr и выходит кодом 2 → Claude чинит ДО завершения хода;
  • если в ходу менялись ts/tsx во frontend/ — один раз гоняет tsc --noEmit
    (РЕПОРТ-онли: печатает сводку, но НЕ блокирует — на большом WIP-фронте часто
    есть посторонние ошибки, ронять ход из-за них не нужно);
  • пишет компактную строку в coordination/.quality-log.jsonl;
  • при успехе очищает реестр (следующий ход начинается с чистого листа).

Точечная привязка к ходу (реестр), а НЕ git status — потому что рабочее дерево
почти всегда грязное, и проверять всё подряд = гонять tsc каждый ход.

Защита от зацикливания: stop_hook_active=true → чистим реестр и exit 0 (не более одной
добавочной попытки). Остальное fail-open: ошибка/таймаут → exit 0.

Регистрация — в .claude/settings.json, событие Stop (без matcher).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RUFF_TIMEOUT = 60
TSC_TIMEOUT = 180
GIT_TIMEOUT = 20  # зарезервировано, не используется


def _project_dir() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else Path(__file__).resolve().parent


def _read_stdin() -> str:
    if sys.stdin.isatty():
        return ""
    try:  # байты + utf-8-sig: снимает BOM и не ломает кириллицу в путях (Windows cp1252)
        return sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return ""


def _session_id(data: dict) -> str:
    sid = re.sub(r"[^a-zA-Z0-9]", "", str(data.get("session_id") or ""))
    return sid[:8] or "nosess"


def _ledger(proj: Path, sid: str) -> Path:
    return proj / "coordination" / f".touched-{sid}.txt"


def _read_touched(ledger: Path) -> list[str]:
    try:  # utf-8-sig — на случай BOM в реестре
        lines = ledger.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    seen: dict[str, None] = {}
    for ln in lines:
        p = ln.strip()
        if p and Path(p).exists():
            seen.setdefault(p, None)
    return list(seen)


def _is_frontend_ts(proj: Path, f: str) -> bool:
    n = str(Path(f)).replace("\\", "/").lower()
    if n.rsplit(".", 1)[-1] not in ("ts", "tsx"):
        return False
    pf = str(proj).replace("\\", "/").lower().rstrip("/")
    return n.startswith(f"{pf}/frontend/") or "/frontend/" in n or n.startswith("frontend/")


def _ruff_changed(proj: Path, py: list[str]) -> str | None:
    """Блокирующий: вернёт текст ошибок или None."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--quiet", "--force-exclude", *py],
            cwd=str(proj), capture_output=True, text=True, timeout=RUFF_TIMEOUT,
        )
    except Exception:
        return None
    if r.returncode != 0 and (r.stdout.strip() or r.stderr.strip()):
        return (r.stdout or r.stderr).strip()[:3000]
    return None


def _tsc_report(proj: Path) -> str | None:
    """Репорт-онли: сводка ошибок типов или None. Никогда не блокирует."""
    fe = proj / "frontend"
    node_entry = fe / "node_modules" / "typescript" / "bin" / "tsc"
    try:
        if node_entry.exists():
            cmd: list[str] = ["node", str(node_entry), "--noEmit", "-p", "tsconfig.json"]
            shell = False
        else:
            shim = fe / "node_modules" / ".bin" / ("tsc.cmd" if os.name == "nt" else "tsc")
            if not shim.exists():
                return None
            cmd = [str(shim), "--noEmit", "-p", "tsconfig.json"]
            shell = os.name == "nt"  # .cmd на Windows надёжнее через шелл
        r = subprocess.run(
            cmd, cwd=str(fe), capture_output=True, text=True,
            timeout=TSC_TIMEOUT, shell=shell,
        )
    except Exception:
        return None
    if r.returncode != 0 and r.stdout.strip():
        lines = [ln for ln in r.stdout.splitlines() if "error TS" in ln]
        head = "\n".join(lines[:20]) if lines else r.stdout.strip()[:1500]
        return f"{len(lines)} ошибок типов:\n{head}"
    return None


def main() -> int:
    for _s in (sys.stdout, sys.stderr):
        try:  # сообщения на русском должны уйти как UTF-8, а не cp866
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    raw = _read_stdin()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0

    proj = _project_dir()
    ledger = _ledger(proj, _session_id(data))

    if data.get("stop_hook_active"):
        ledger.unlink(missing_ok=True)  # одну попытку уже дали — не зацикливаемся
        return 0

    touched = _read_touched(ledger)
    if not touched:
        return 0  # в этом ходу код не трогали — молчим

    py = [f for f in touched if f.lower().endswith(".py")]
    fe = [f for f in touched if _is_frontend_ts(proj, f)]

    ruff_err = _ruff_changed(proj, py) if py else None
    tsc_note = _tsc_report(proj) if fe else None

    try:
        log = proj / "coordination" / ".quality-log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": time.time(), "touched": len(touched),
            "py": len(py), "fe": len(fe),
            "ruff_ok": ruff_err is None, "tsc_ok": tsc_note is None,
        }
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass

    if ruff_err:
        msg = "[quality/stop] ruff: проблемы в изменённых .py — почини до завершения:\n\n"
        msg += ruff_err
        if tsc_note:
            msg += "\n\n[tsc, не блокирует] " + tsc_note
        sys.stderr.write(msg + "\n")
        return 2  # реестр НЕ чистим: на следующем стопе перепроверим

    ledger.unlink(missing_ok=True)  # успех — чистим реестр хода
    note = f"[quality/stop] OK — тронуто {len(touched)} код-файлов (py:{len(py)} fe:{len(fe)})"
    note += f"; ⚠ tsc: {tsc_note.splitlines()[0]}" if tsc_note else "; линт/типы чисты."
    print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
