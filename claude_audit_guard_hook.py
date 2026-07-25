#!/usr/bin/env python3
"""claude_audit_guard_hook.py — страховки по аудиту сессий 10–16.07.2026 (PreToolUse).

Закрывает три класса повторявшихся потерь (числа — из адверсариально проверенного аудита):

1) **Битые параметры инструментов** (13 InputValidationError/нед, один и тот же
   run_in_background у Workflow — 5 раз за 5 дней): deny ДО отправки в API с корректной
   сигнатурой в причине. Память модели тут доказанно не работает — работает хук.
2) **Правка чужих файлов в общем дереве** (~100 forensics-проверок «не подхватил ли
   чужое»/нед): deny, если file_path числится в свежем (<8ч) реестре другой сессии
   `coordination/.touched-<sid>.txt` или `.touched-<sid>-<agent>.txt` (реестр уже ведёт
   claude_quality_hook.py; agent-суффикс — сабагенты сессии, владелец «свой», если
   реестр начинается с текущего sid, — иначе сессия блокировала бы сама себя/свои
   сабагенты). Обход при осознанной необходимости: env AIOS_ALLOW_FOREIGN_EDIT=1.
3) **Advisory** (не блокирует): Edit, добавляющий в .py только import-строки (ruff-хук
   откатит их как F401 — 11 циклов/нед) и Edit файлов авто-памяти (append-only, Read
   непосредственно перед Edit).

Философия — fail-open: любая внутренняя ошибка → exit 0 без вывода. Deny — только по
точному совпадению с известным классом потерь. Регистрация — .claude/settings.json,
PreToolUse, matcher Edit|Write|NotebookEdit|Workflow|TaskUpdate|TaskCreate|Monitor|SendUserFile.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

TOUCHED_FRESH_HOURS = 8.0

BAD_PARAMS = {
    # tool -> (запрещённые параметры, обязательные параметры, подсказка-сигнатура)
    "Workflow": ({"run_in_background"}, set(),
                 "Workflow НЕ имеет run_in_background — он и так фоновый. "
                 "Параметры: script | scriptPath | name, args, resumeFromRunId."),
    "TaskUpdate": ({"tasks", "state"}, {"taskId"},
                   "TaskUpdate: один таск на вызов, обязателен taskId (строка); "
                   "статус — поле status."),
    "TaskCreate": ({"tasks", "prompt", "subagent_type"}, {"subject", "description"},
                   "TaskCreate: один таск на вызов, обязательны subject + description."),
    "Monitor": (set(), {"description"}, "Monitor: обязателен параметр description."),
}


def _read_stdin() -> dict:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


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


def _session_id(data: dict) -> str:
    sid = re.sub(r"[^a-zA-Z0-9]", "", str(data.get("session_id") or ""))
    return sid[:8] or "nosess"


def _deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False))
    sys.exit(0)


def _advise(context: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": context,
    }}, ensure_ascii=False))
    sys.exit(0)


def _check_tool_params(tool: str, tool_input: dict) -> None:
    forbidden, required, hint = BAD_PARAMS[tool]
    present = set(tool_input.keys())
    bad = forbidden & present
    missing = required - present
    if bad or missing:
        parts = []
        if bad:
            parts.append("лишние параметры: " + ", ".join(sorted(bad)))
        if missing:
            parts.append("не хватает: " + ", ".join(sorted(missing)))
        _deny(f"[audit-guard] {tool}: " + "; ".join(parts) + ". " + hint +
              " (13 таких InputValidationError за неделю аудита — сигнатуры в памяти tool-signatures.md)")


def _check_send_user_file(tool_input: dict) -> None:
    files = tool_input.get("files")
    if files is not None and not isinstance(files, list):
        _deny("[audit-guard] SendUserFile: files — это JSON-массив строк-путей, не строка.")


def _norm(p: str | Path) -> str:
    try:
        return os.path.normcase(os.path.normpath(str(Path(p).resolve())))
    except Exception:
        return os.path.normcase(os.path.normpath(str(p)))


def _check_foreign_touched(proj: Path, sid: str, file_path: str) -> None:
    if os.environ.get("AIOS_ALLOW_FOREIGN_EDIT") == "1":
        return
    target = _norm(file_path)
    now = time.time()
    coord = proj / "coordination"
    try:
        # СВОИ реестры — теми же двумя точными шаблонами, что и в claude_stop_hook.py
        # (`_all_ledgers`): свой + сабагентские `<sid>-<agent>`. Схемы имён обязаны
        # совпадать, поэтому и техника одинаковая — рассинхрон тут не шумит, а тихо
        # блокирует правку собственных файлов или, наоборот, пропускает чужие.
        own = set(coord.glob(f".touched-{sid}.txt")) | set(coord.glob(f".touched-{sid}-*.txt"))
        ledgers = [lg for lg in coord.glob(".touched-*.txt") if lg not in own]
    except Exception:
        return
    for ledger in ledgers:
        try:
            owner = ledger.stem[len(".touched-"):]
            if (now - ledger.stat().st_mtime) > TOUCHED_FRESH_HOURS * 3600:
                continue
            lines = ledger.read_text(encoding="utf-8", errors="replace").splitlines()
            if any(_norm(ln) == target for ln in lines if ln.strip()):
                _deny(f"[audit-guard] Файл занят параллельной сессией {owner} "
                      f"(coordination/{ledger.name}, свежее {TOUCHED_FRESH_HOURS:.0f}ч). "
                      "Координируйся через ACTIVE-SESSIONS.md или, если уверен, что сессия "
                      "закончила: AIOS_ALLOW_FOREIGN_EDIT=1 для осознанного обхода.")
        except SystemExit:
            raise
        except Exception:
            continue


_IMPORT_RE = re.compile(r"^\s*(import\s+\S|from\s+\S+\s+import\s)")


def _added_lines(old: str, new: str) -> list[str]:
    old_set = set(old.splitlines())
    return [ln for ln in new.splitlines() if ln.strip() and ln not in old_set]


def _advisories(tool: str, tool_input: dict) -> list[str]:
    out: list[str] = []
    fp = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    low = fp.lower().replace("\\", "/")
    if "/memory/" in low or low.endswith("memory.md"):
        out.append("[audit-guard] Это файл авто-памяти, общий для параллельных сессий: "
                   "Read непосредственно перед этим Edit; индекс MEMORY.md — только "
                   "append-строкой в конец (42% ошибок 'File has not been read yet' "
                   "за неделю аудита пришлись на память).")
    if tool == "Edit" and fp.endswith(".py"):
        added = _added_lines(str(tool_input.get("old_string") or ""),
                             str(tool_input.get("new_string") or ""))
        if added and all(_IMPORT_RE.match(ln) for ln in added):
            out.append("[audit-guard] Правка добавляет ТОЛЬКО import-строки: ruff-хук "
                       "удалит неиспользуемый импорт (F401). Добавь импорт одним Edit "
                       "вместе с кодом, который его использует (11 таких циклов за "
                       "неделю аудита).")
    return out


def main() -> int:
    data = _read_stdin()
    tool = str(data.get("tool_name") or "")
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0

    if tool in BAD_PARAMS:
        _check_tool_params(tool, tool_input)
        return 0
    if tool == "SendUserFile":
        _check_send_user_file(tool_input)
        return 0

    if tool in ("Edit", "Write", "NotebookEdit"):
        proj = _project_dir()
        # NotebookEdit кладёт путь в notebook_path, а не file_path
        fp = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if fp:
            _check_foreign_touched(proj, _session_id(data), fp)
        notes = _advisories(tool, tool_input)
        if notes:
            _advise("\n".join(notes))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # fail-open
