#!/usr/bin/env python3
"""claude_stop_hook.py — Stop: проверка качества тронутого за ход + строка статуса.

Когда Claude заканчивает ход, хук читает ВСЕ реестры своей сессии — свой
(coordination/.touched-<session>.txt) и реестры сабагентов (.touched-<session>-<agent>.txt,
их ведёт claude_quality_hook.py), — и:

  • гоняет ruff по изменённым .py (точечно) — это БЛОКИРУЮЩИЙ гейт: при ошибках
    печатает их в stderr и выходит кодом 2 → Claude чинит ДО завершения хода;
  • если в ходу менялись ts/tsx во frontend/ — один раз гоняет tsc --noEmit
    (РЕПОРТ-онли: печатает сводку, но НЕ блокирует — на большом WIP-фронте часто
    есть посторонние ошибки, ронять ход из-за них не нужно);
  • пишет компактную строку в coordination/.quality-log.jsonl;
  • при успехе очищает СВОЙ реестр (следующий ход начинается с чистого листа).

Один хук на два события. На **Stop** (главный цикл) гейт идёт по своему реестру И по
сабагентским — чтобы ничего не проскочило мимо ruff, — но удаляется только свой плюс
заведомо протухшие сабагентские (страховка от сабагента, умершего без SubagentStop).
На **SubagentStop** хук работает ровно с реестром своего сабагента: гейтит и удаляет его.
Так реестр чистит его собственный писатель в момент завершения, и родитель не стирает
файл под ЖИВЫМ фоновым сабагентом — иначе тронутое тем до этого момента гейт не увидел бы
никогда. Удаление обёрнуто в try/except OSError (Windows: файл может держать другой
процесс — WinError 32).

Точечная привязка к ходу (реестр), а НЕ git status — потому что рабочее дерево
почти всегда грязное, и проверять всё подряд = гонять tsc каждый ход.

Защита от зацикливания: stop_hook_active=true → чистим реестр и exit 0 (не более одной
добавочной попытки). Остальное fail-open: ошибка/таймаут → exit 0.

Регистрация — в .claude/settings.json, события Stop и SubagentStop (без matcher).
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
# Реестр сабагента, не тронутый столько часов, считаем брошенным (сабагент завершился без
# SubagentStop). Совпадает с окном «файл занят» в claude_audit_guard_hook.py.
STALE_LEDGER_HOURS = 8.0


def _project_dir() -> Path:
    """Каталог проекта: расположение самого хука, а не CLAUDE_PROJECT_DIR на веру.
    Полное обоснование — в claude_pushlog_hook.py (там цена ошибки нагляднее всего)."""
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
    try:  # байты + utf-8-sig: снимает BOM и не ломает кириллицу в путях (Windows cp1252)
        return sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return ""


def _session_id(data: dict) -> str:
    sid = re.sub(r"[^a-zA-Z0-9]", "", str(data.get("session_id") or ""))
    return sid[:8] or "nosess"


def _agent_id(data: dict) -> str:
    """Идентификатор сабагента из payload; пусто = главный цикл. Правило то же, что у
    писателя реестра (claude_quality_hook.py) — схемы имён обязаны совпадать."""
    agent = data.get("agent_id") or data.get("agentId")
    if not agent:
        return ""
    return re.sub(r"[^a-zA-Z0-9]", "", str(agent))[:12]


def _ledger(proj: Path, sid: str, agent: str = "") -> Path:
    """Реестр этого хода: свой (главный цикл) или конкретного сабагента."""
    suffix = f"-{agent}" if agent else ""
    return proj / "coordination" / f".touched-{sid}{suffix}.txt"


def _all_ledgers(proj: Path, sid: str) -> list[Path]:
    """Свой реестр + реестры сабагентов этой сессии (.touched-<sid>-<agent>.txt).

    Дефис обязателен: голый glob `.touched-<sid>*` цепляет чужую сессию, чей id начинается
    с нашего, и тогда ход блокируется её ошибками. То же правило владения — в
    claude_audit_guard_hook.py, схемы обязаны совпадать.
    """
    own = _ledger(proj, sid)
    try:
        subs = sorted((proj / "coordination").glob(f".touched-{sid}-*.txt"))
    except OSError:
        subs = []
    return ([own] if own.exists() else []) + subs


def _read_touched(ledgers: list[Path]) -> list[str]:
    seen: dict[str, None] = {}
    for ledger in ledgers:
        try:  # utf-8-sig + errors=replace: битый байт в ОДНОМ реестре не должен через
            # глобальный fail-open молча выключать ruff-гейт всей сессии
            lines = ledger.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except (OSError, ValueError):
            continue  # реестр сабагента могли удалить/ещё не создать — не мешаем
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
            encoding="utf-8", errors="replace",  # иначе на Windows cp1251/cp866 ломает кириллицу
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
            encoding="utf-8", errors="replace",  # иначе на Windows cp1251/cp866 ломает кириллицу
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
    sid = _session_id(data)
    agent = _agent_id(data)
    # На SubagentStop хук отвечает ТОЛЬКО за реестр своего сабагента, на Stop родителя —
    # за свой и (в уборке) за протухшие сабагентские. Так реестр чистит его собственный
    # писатель в момент своего завершения, и родитель не стирает файл под ЖИВЫМ сабагентом
    # (тогда тронутое им до этого момента гейт не увидел бы никогда).
    ledger = _ledger(proj, sid, agent)

    if data.get("stop_hook_active"):
        try:  # одну попытку уже дали — не зацикливаемся
            ledger.unlink(missing_ok=True)
        except OSError:
            pass  # файл может держать другой процесс (Windows WinError 32) — не мешаем
        return 0

    # Сабагент гейтит только своё; родитель — всё, что накопилось за ход (включая
    # сабагентское), чтобы ничего не проскочило мимо ruff.
    ledgers = [ledger] if agent else _all_ledgers(proj, sid)
    touched = _read_touched(ledgers)
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

    # Успех — чистим СВОЙ реестр (реестр = «тронуто с последнего зелёного гейта»).
    # Реестр сабагента удаляет он сам на своём SubagentStop, а не родитель: иначе зелёный
    # Stop родителя стирал бы файл под ЖИВЫМ фоновым сабагентом, и тронутое им до этого
    # момента гейт не увидел бы никогда.
    _cleanup: list[Path] = [ledger]
    if not agent:
        # Страховка от сабагентов, которые завершились без SubagentStop (упал, убит, старая
        # версия CLI): подметаем только ЗАВЕДОМО протухшие — живому писателю они не принадлежат.
        stale_before = time.time() - STALE_LEDGER_HOURS * 3600
        for _lg in _all_ledgers(proj, sid):
            try:
                if _lg != ledger and _lg.stat().st_mtime < stale_before:
                    _cleanup.append(_lg)
            except OSError:
                continue
    for _lg in _cleanup:
        try:
            _lg.unlink(missing_ok=True)
        except OSError:
            pass  # файл может держать другой процесс (Windows WinError 32) — не мешаем
    note = f"[quality/stop] OK — тронуто {len(touched)} код-файлов (py:{len(py)} fe:{len(fe)})"
    note += f"; ⚠ tsc: {tsc_note.splitlines()[0]}" if tsc_note else "; линт/типы чисты."
    print(note)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # fail-open: необработанная ошибка не должна ронять ход
