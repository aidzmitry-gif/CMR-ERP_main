#!/usr/bin/env python3
"""scope_scaffold.py — генератор пары scope + first-msg + seed acceptance-гейта для воркера.

Снимает ручной шаг №1 оркестратора (писать 2 файла по ~80 строк на каждого воркера).
Заполняет каркас из аргументов; задачно-специфику (трассировка, детали) дописываешь руками
в помеченных TODO. Сразу связывает всю цепочку:
  • scope получает поля model:/mcp: (их читает spawn_workers._model_for_worker/_mcp_config_for_worker);
  • seed coordination/acceptance/<name>.json (его проверяет integrate перед merge).

Запуск:
  python scope_scaffold.py <name> --goal "одна строка цели" \\
      --include "modules/sales/**" --include "tests/test_sales_*.py" \\
      --exclude "core/**" --model sonnet --mcp none \\
      --test '& ".\\.venv\\Scripts\\python.exe" -m pytest tests/test_sales_*.py -x -q'

Создаёт: coordination/first-msgs/<name>.md, coordination/<name>-scope.md,
coordination/acceptance/<name>.json. Без --force не перезаписывает существующее.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COORD = ROOT / "coordination"
FIRST_MSG_DIR = COORD / "first-msgs"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

FIRST_MSG_TMPL = """# Задание: {goal}

**Goal-Driven**: {goal}

**Читай первым** свой скоуп: `coordination/{name}-scope.md` — там LOOP CONTRACT
(что МОЖНО/НЕЛЬЗЯ трогать), команда запуска тестов и acceptance gate. Затем —
релевантный код по скоупу и `CLAUDE.md`/`modules/sales/module.py` (эталон).

Работай **автономно**, не жди ввода. Нужно решение оркестратора — пиши
`NEEDS-ORCHESTRATOR-ANSWER` в `coordination/{name}-status.md`. Не вызывай AskUserQuestion.

Жёстко: трогай только файлы из `include`; `exclude` не трогай. Перед `STATE: COMPLETE`
прогони `acceptance_gate.py check {name}` и добейся ЗЕЛЁНОГО.
"""

SCOPE_TMPL = """# {name} — scope

## Задача (уровень 2: касаемые файлы + верификация)

{goal}

<!-- TODO: трассировка к требованиям (FR/§), рекомендации по реализации/мокам, детали -->

## LOOP CONTRACT

```yaml
scope:
  include:
{inc}
  exclude:
{exc}
permissions:
  repo: write-branch
  db: read-only
  llm: enabled
model: {model}              # haiku=механика / sonnet=код / opus=архитектура / inherit
mcp: {mcp}                  # none / serena (семантич. навигация по символам)
budget:
  max_iterations: {iters}
  max_runtime_minutes: 30
  max_files_changed: {max_files}
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - acceptance_gate_red_after_3_iters
  - file_touched_outside_scope
  - product_behavior_ambiguous
report:
  destination: coordination/{name}-status.md
```

## Команда запуска тестов (worktree БЕЗ своего .venv — python ГЛАВНОГО репо)

```powershell
{test_cmd}
```

## Acceptance gate (машинный — coordination/acceptance/{name}.json)

- [ ] {goal} — выполнено и проверено доказательством (file:line / тест / скрин)
- [ ] линт чист (`ruff`)
- [ ] тесты зелёные
- [ ] тронуты ТОЛЬКО файлы из include
- [ ] six-layer в теле коммита; status заканчивается `STATE: COMPLETE`

Воркер правит ТОЛЬКО поле `passes` в json и прикладывает `evidence`; сами критерии не трогает.

## Anticipated failure modes
<!-- TODO: вероятные провалы + класс бага A/B/C/D/E + как заметишь -->
"""


def _lint_path_from_include(include: list[str]) -> str:
    g = include[0] if include else "."
    g = re.sub(r"/\*\*?$", "", g).rstrip("/")
    return g or "."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Генератор scope+first-msg+acceptance для воркера")
    ap.add_argument("name")
    ap.add_argument("--goal", required=True, help="одна строка: цель задачи")
    ap.add_argument("--include", action="append", default=[], help="glob, что МОЖНО трогать (повторяемо)")
    ap.add_argument("--exclude", action="append", default=[], help="glob, что НЕЛЬЗЯ трогать (повторяемо)")
    ap.add_argument("--model", default="sonnet", choices=["haiku", "sonnet", "opus", "inherit"])
    ap.add_argument("--mcp", default="none", choices=["none", "serena"])
    ap.add_argument("--test", default="", help="команда запуска тестов (для scope и acceptance)")
    ap.add_argument("--iters", type=int, default=5)
    ap.add_argument("--max-files", type=int, default=10)
    ap.add_argument("--force", action="store_true", help="перезаписать существующие файлы")
    args = ap.parse_args(argv)

    fm = FIRST_MSG_DIR / f"{args.name}.md"
    sc = COORD / f"{args.name}-scope.md"
    gate = COORD / "acceptance" / f"{args.name}.json"
    clash = [p for p in (fm, sc, gate) if p.is_file()]
    if clash and not args.force:
        print(f"scaffold: уже есть {', '.join(p.name for p in clash)} — --force чтобы перезаписать.",
              file=sys.stderr)
        return 1

    include = args.include or ["<TODO: что МОЖНО трогать>"]
    exclude = args.exclude or ["core/**", "config/**"]
    inc = "\n".join(f"    - {g}" for g in include)
    exc = "\n".join(f"    - {g}" for g in exclude)
    test_cmd = args.test or '& ".\\.venv\\Scripts\\python.exe" -m pytest -x -q   # TODO'

    FIRST_MSG_DIR.mkdir(parents=True, exist_ok=True)
    fm.write_text(FIRST_MSG_TMPL.format(name=args.name, goal=args.goal), encoding="utf-8")
    sc.write_text(
        SCOPE_TMPL.format(name=args.name, goal=args.goal, inc=inc, exc=exc, model=args.model,
                          mcp=args.mcp, iters=args.iters, max_files=args.max_files, test_cmd=test_cmd),
        encoding="utf-8",
    )

    checks = [
        {"id": "lint", "kind": "lint", "desc": "ruff чисто",
         "cmd": f'"{VENV_PY}" -m ruff check {_lint_path_from_include(args.include)}',
         "passes": False, "evidence": ""},
        {"id": "tests", "kind": "test", "desc": "тесты зелёные",
         "cmd": args.test, "passes": False, "evidence": ""},
        {"id": "feature", "kind": "manual", "desc": f"{args.goal} — работает end-to-end",
         "passes": False, "evidence": ""},
    ]
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps({"worker": args.name, "checks": checks}, ensure_ascii=False, indent=2)
                    + "\n", encoding="utf-8")

    print(f"scaffold {args.name}: создано\n  {fm}\n  {sc}\n  {gate}")
    print(f"Заполни TODO в scope, затем:  spawn_workers.py spawn {args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
