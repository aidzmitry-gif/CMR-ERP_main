#!/usr/bin/env python3
"""acceptance_gate.py — машинно-проверяемый гейт приёмки воркера (durable JSON-чеклист).

По мотивам Anthropic «Effective harnesses for long-running agents»: внешний durable
acceptance-gate в JSON (а НЕ markdown — модель реже перезаписывает JSON). Каждый критерий
стартует passes:false; воркер вправе менять ТОЛЬКО поле passes и обязан приложить evidence;
править/удалять сами критерии нельзя.

Ключевое отличие от «доверия флагу»: для объективно-проверяемых критериев (есть поле `cmd`:
ruff/tsc/pytest и т.п.) `check` ЗАПУСКАЕТ команду и ПЕРЕЗАПИСЫВАЕТ passes её результатом —
поэтому оптимистичный флаг воркера не выживает (ловим «галлюцинацию done»). Критерии без cmd
(`manual`, напр. «доска рендерит карточки») засчитываются ТОЛЬКО при passes:true И непустом
evidence — авто-проверить их нельзя, но без доказательства не пройдут.

Файл гейта: coordination/acceptance/<worker>.json
  {"worker": "...", "checks": [
     {"id": "lint",   "kind": "lint",   "desc": "ruff чисто",  "cmd": "...", "passes": false, "evidence": ""},
     {"id": "tests",  "kind": "test",   "desc": "юнит зелёные","cmd": "...", "passes": false, "evidence": ""},
     {"id": "board",  "kind": "manual", "desc": "доска ок",    "passes": false, "evidence": "скрин ...png"}
  ]}

Команды:
  init   <worker> [--check "id|kind|desc|cmd" ...] [--from file.json]   создать/дополнить гейт
  check  <worker>                                                       проверить; exit 0 зелёный, иначе 2
  status [<worker> ...]                                                 сводка по гейтам (для дашборда флота)

cmd выполняется через шелл с cwd=корень проекта (доверенный dev-контекст; катастрофы режет
claude_guard_hook.py). Повреждённый JSON → check возвращает 2 (не зелёный), молча не падает.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

CMD_TIMEOUT = 600


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


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _gate_path(proj: Path, worker: str) -> Path:
    return proj / "coordination" / "acceptance" / f"{worker}.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_check_spec(spec: str) -> dict:
    parts = spec.split("|", 3)  # id|kind|desc|cmd ; cmd опционален и может содержать |
    cid = parts[0].strip()
    kind = (parts[1].strip() if len(parts) > 1 else "manual") or "manual"
    desc = parts[2].strip() if len(parts) > 2 else ""
    cmd = parts[3].strip() if len(parts) > 3 else ""
    out = {"id": cid, "kind": kind, "desc": desc, "passes": False, "evidence": ""}
    if cmd:
        out["cmd"] = cmd
    return out


def cmd_init(proj: Path, args: argparse.Namespace) -> int:
    path = _gate_path(proj, args.worker)
    gate = _load(path) if path.exists() else {"worker": args.worker, "checks": []}
    by_id = {c.get("id"): c for c in gate.get("checks", [])}

    new_checks: list[dict] = []
    for spec in args.check or []:
        new_checks.append(_parse_check_spec(spec))
    if args.from_file:
        loaded = json.loads(Path(args.from_file).read_text(encoding="utf-8-sig"))
        new_checks.extend(loaded.get("checks", loaded) if isinstance(loaded, dict) else loaded)

    for c in new_checks:
        cid = c.get("id")
        if not cid:
            continue
        if cid in by_id:  # апсерт: сохраняем passes/evidence существующего критерия
            existing = by_id[cid]
            existing["kind"] = c.get("kind", existing.get("kind", "manual"))
            existing["desc"] = c.get("desc", existing.get("desc", ""))
            if c.get("cmd"):
                existing["cmd"] = c["cmd"]
        else:
            c.setdefault("passes", False)
            c.setdefault("evidence", "")
            gate.setdefault("checks", []).append(c)
            by_id[cid] = c

    _save(path, gate)
    print(f"[gate] {args.worker}: {len(gate.get('checks', []))} критериев → {path}")
    return 0


def _eval_check(proj: Path, c: dict) -> tuple[bool, str]:
    """Вернёт (passed, note). Для cmd — запускает и ПЕРЕЗАПИСЫВАЕТ passes результатом."""
    cmd = c.get("cmd")
    if cmd:
        try:
            r = subprocess.run(
                cmd, shell=True, cwd=str(proj),
                capture_output=True, text=True, timeout=CMD_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return False, "таймаут"
        except Exception as e:  # noqa: BLE001 — гейт не должен падать
            return False, f"ошибка запуска: {e}"
        ok = r.returncode == 0
        c["passes"] = ok  # объективный результат бьёт флаг воркера
        c["evidence"] = f"auto: exit {r.returncode}"
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        return ok, (tail[-1][:120] if tail else f"exit {r.returncode}")
    # manual: засчитываем только при флаге + непустом доказательстве
    ev = str(c.get("evidence", "")).strip()
    if c.get("passes") and ev:
        return True, "manual+evidence"
    if c.get("passes") and not ev:
        return False, "passes:true без evidence — не зачтено"
    return False, "passes:false"


def cmd_check(proj: Path, args: argparse.Namespace) -> int:
    path = _gate_path(proj, args.worker)
    if not path.exists():
        print(f"[gate] нет гейта для {args.worker} ({path}) — нечего проверять", file=sys.stderr)
        return 2
    try:
        gate = _load(path)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[gate] повреждён JSON гейта {args.worker}: {e}", file=sys.stderr)
        return 2

    checks = gate.get("checks", [])
    if not checks:
        print(f"[gate] {args.worker}: критериев нет — гейт пуст, считаю НЕ пройденным", file=sys.stderr)
        return 2

    results = []
    for c in checks:
        passed, note = _eval_check(proj, c)
        results.append((c.get("id", "?"), passed, note))
    _save(path, gate)  # сохраняем перепроверенные passes/evidence

    green = all(p for _, p, _ in results)
    width = max((len(cid) for cid, _, _ in results), default=4)
    lines = [f"  {'✓' if p else '✗'} {cid.ljust(width)}  {note}" for cid, p, note in results]
    body = "\n".join(lines)
    head = f"[gate] {args.worker}: {sum(p for _, p, _ in results)}/{len(results)} критериев пройдено"
    if green:
        print(head + " — ЗЕЛЁНЫЙ\n" + body)
        return 0
    sys.stderr.write(head + " — КРАСНЫЙ (интеграция запрещена)\n" + body + "\n")
    return 2


def _passed_norun(c: dict) -> bool:
    """Лёгкая оценка БЕЗ запуска cmd — для сводки status (берёт результат прошлого check)."""
    if c.get("cmd"):
        return bool(c.get("passes"))
    return bool(c.get("passes")) and bool(str(c.get("evidence", "")).strip())


def cmd_status(proj: Path, args: argparse.Namespace) -> int:
    base = proj / "coordination" / "acceptance"
    if args.workers:
        files = [_gate_path(proj, w) for w in args.workers]
    else:
        files = sorted(base.glob("*.json")) if base.exists() else []
    if not files:
        print("[gate] гейтов нет")
        return 0
    for path in files:
        worker = path.stem
        try:
            gate = _load(path)
            checks = gate.get("checks", [])
            done = sum(1 for c in checks if _passed_norun(c))
            total = len(checks)
            mark = "ЗЕЛЁНЫЙ" if total and done == total else f"{done}/{total}"
            print(f"  {worker.ljust(24)} {mark}")
        except (json.JSONDecodeError, OSError):
            print(f"  {worker.ljust(24)} ПОВРЕЖДЁН")
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    ap = argparse.ArgumentParser(description="Машинно-проверяемый гейт приёмки воркера")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="создать/дополнить гейт")
    p_init.add_argument("worker")
    p_init.add_argument("--check", action="append", help='спека "id|kind|desc|cmd"')
    p_init.add_argument("--from", dest="from_file", help="JSON-файл с критериями")

    p_check = sub.add_parser("check", help="проверить гейт (exit 0 зелёный / 2 красный)")
    p_check.add_argument("worker")

    p_status = sub.add_parser("status", help="сводка по гейтам")
    p_status.add_argument("workers", nargs="*")

    args = ap.parse_args(argv)
    proj = _project_dir()
    if args.cmd == "init":
        return cmd_init(proj, args)
    if args.cmd == "check":
        return cmd_check(proj, args)
    if args.cmd == "status":
        return cmd_status(proj, args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
