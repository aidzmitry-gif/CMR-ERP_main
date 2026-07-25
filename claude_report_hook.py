#!/usr/bin/env python3
"""claude_report_hook.py — Stop-хук: структурный доклад полосы координатору.

Когда сессия завершает ход, хук читает её транскрипт (путь приходит в stdin — поэтому
работает и для десктоп-чатов, которых координатор НЕ видит файлово), берёт ПОСЛЕДНЕЕ
сообщение ассистента и ищет строки-маркеры `КООРД: ...`. Каждую найденную дописывает в
`coordination/REPORTS.md` (время + короткий id сессии). Координатор читает REPORTS.md
(и снимок STATUS.md) вместо транскриптов.

Формат маркера (полоса пишет в конце хода):
  КООРД: <DONE|BLOCKED|NEEDS-MIG|NEEDS-ARB|INFO> <полоса> — <одна строка>

Философия: fail-open. Любая ошибка → exit 0 (хук никогда не ломает работу полосы).
Дедуп: не дублирует маркер, идентичный последней строке REPORTS.md.
Регистрация — `.claude/settings.json`, событие Stop (владелец — координатор).
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

REPORTS_REL = "coordination/REPORTS.md"
# Строгий маркер: НАЧАЛО строки (допускаем bullet/quote/backtick-префикс) + РЕАЛЬНЫЙ статус-ключ.
# Так шаблон `КООРД: <DONE|...>` и упоминания в прозе/доке НЕ ловятся (нет статуса-ключа / не с начала).
MARKER = re.compile(
    r"(?m)^[\s>*`\-]*КООРД:\s*(DONE|BLOCKED|NEEDS-MIG|NEEDS-ARB|INFO)\b[ \t:—\-]*(.*)$"
)


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


def _read_stdin() -> dict:
    if sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _recent_assistant_texts(transcript: Path, n: int = 6) -> list[str]:
    """Тексты последних n сообщений ассистента, новейшие первыми.

    Один проход файла на всё: раньше рядом жила ещё `_last_assistant_text`, читавшая ТОТ ЖЕ
    транскрипт вторым чтением. Хук висит на Stop, транскрипт длинной сессии — многие мегабайты,
    а fallback «последний ход был tooling, маркер выше по истории» — обычный случай, не редкий:
    второе чтение случалось на большинстве ходов. Первый элемент списка = бывший
    `_last_assistant_text`, поэтому поведение не изменилось.
    """
    try:
        lines = transcript.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return []
    out: list[str] = []
    for ln in reversed(lines):  # с конца — первое assistant-сообщение и есть последнее
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        if obj.get("isSidechain") is True:  # сабагент (--forward-subagent-text) — не доклад полосы
            continue
        content = (obj.get("message") or {}).get("content")
        if isinstance(content, str):
            txt = content
        elif isinstance(content, list):
            txt = "\n".join(b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text")
        else:
            txt = ""
        if txt.strip():
            out.append(txt)
        if len(out) >= n:
            break
    return out


def _session_id(data: dict) -> str:
    sid = re.sub(r"[^a-zA-Z0-9]", "", str(data.get("session_id") or ""))
    return sid[:8] or "nosess"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    data = _read_stdin()
    tpath = data.get("transcript_path") or ""
    if not tpath:
        return 0
    def _extract(t: str) -> list[str]:
        return [f"{m.group(1)} {m.group(2).strip()}".strip() for m in MARKER.finditer(t)]

    # Одно чтение транскрипта: последнее assistant-сообщение идёт первым, и если в нём маркера
    # нет (ход закончился вызовом инструмента), продолжаем вверх по истории тем же списком.
    markers: list[str] = []
    for t in _recent_assistant_texts(Path(tpath), 6):
        if (markers := _extract(t)):
            break
    if not markers:
        return 0

    proj = _project_dir()
    log = proj / REPORTS_REL
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    sid = _session_id(data)

    try:
        existing = log.read_text(encoding="utf-8-sig", errors="replace") if log.exists() else ""
    except OSError:
        existing = ""

    new_lines = []
    for mk in markers:
        line = f"- `{when}` · сессия `{sid}` · **КООРД:** {mk}"
        if mk and mk not in existing:  # дедуп по тексту маркера
            new_lines.append(line)
    if not new_lines:
        return 0

    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # fail-open: хук никогда не должен ронять ход сессии
