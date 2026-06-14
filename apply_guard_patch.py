#!/usr/bin/env python3
r"""apply_guard_patch.py — разовый РУЧНОЙ патч claude_guard_hook.py.

Добавляет границы слов в правило самозащиты гарда: `rm|del` -> `\brm\b|\bdel\b`, чтобы
гард не ловил ложно «Pe[rm]issions», «mo[del]» и т.п. Строго безопаснее: реальное
`rm claude_guard_hook.py` по-прежнему ловится, ложняки на словах — нет.

ЗАПУСКАЕШЬ ТЫ (человек), в своём терминале:
    & ".\.venv\Scripts\python.exe" apply_guard_patch.py

Почему не ассистент: сам гард блокирует правку себя инструментами Claude — это by design
(защита от автономных факапов / prompt-injection). Человек в петле = санкционированный путь.

Идемпотентно: уже пропатчено — ничего не делает. Делает бэкап claude_guard_hook.py.bak.
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "claude_guard_hook.py"
OLD = r"|sed\s+-i|rm|del|Remove-Item)"
NEW = r"|sed\s+-i|\brm\b|\bdel\b|Remove-Item)"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not TARGET.is_file():
        print(f"не найден {TARGET}")
        return 1
    text = TARGET.read_text(encoding="utf-8")
    if NEW in text:
        print("уже пропатчено — границы слов на месте, менять нечего.")
        return 0
    if OLD not in text:
        print("целевая строка не найдена — формат гарда изменился, пропатчь вручную.")
        return 1

    backup = TARGET.with_name(TARGET.name + ".bak")
    backup.write_text(text, encoding="utf-8")
    TARGET.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print(r"OK: claude_guard_hook.py пропатчен (\brm\b|\bdel\b). Бэкап: claude_guard_hook.py.bak")
    print("Гард перечитывается на каждом вызове — изменение активно сразу, рестарт не нужен.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
