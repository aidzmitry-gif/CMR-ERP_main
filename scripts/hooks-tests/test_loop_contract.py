# -*- coding: utf-8 -*-
"""LOOP CONTRACT: model/effort/max_usd должны читаться из scope с ХВОСТОВЫМ комментарием —
именно так поле записано в каноническом шаблоне coordination/worker-engineering-standards.md.
"""
import sys
import tempfile
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ))
import spawn_workers as sw  # noqa: E402

TPL = """# scope воркера

```yaml
LOOP CONTRACT:
model: sonnet              # тир: haiku 4.5=механика / sonnet 5=код / opus 5=архитектура
effort: low                # low механика / medium фича / high ревью-деньги
budget:
  max_iterations: 6
  max_usd: 7               # прокидывается в --max-budget-usd
```
"""
TPL_NO_COMMENTS = "model: opus\neffort: xhigh\nbudget:\n  max_usd: 12\n"
TPL_EMPTY = "# скоуп без LOOP CONTRACT\nПросто текст.\n"
TPL_FABLE = "model: fable   # хочу флагман\neffort: high\n"

fails = 0


def check(desc, scope_text, want_model, want_effort, want_budget):
    global fails
    with tempfile.TemporaryDirectory() as td:
        name = "tmpworker"
        p = Path(td) / f"{name}-scope.md"
        p.write_text(scope_text, encoding="utf-8")
        orig = sw._scope_path
        sw._scope_path = lambda n, _p=p: _p
        try:
            got = (sw._model_for_worker(name, "DEFMODEL"),
                   sw._effort_for_worker(name, "DEFEFFORT"),
                   sw._budget_for_worker(name, "DEFBUDGET"))
        finally:
            sw._scope_path = orig
    want = (want_model, want_effort, want_budget)
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'OK  ' if ok else 'FAIL'} {desc}\n      got={got} want={want}")


check("шаблон с хвостовыми комментариями (канон)", TPL, "sonnet", "low", "7")
check("без комментариев", TPL_NO_COMMENTS, "opus", "xhigh", "12")
check("скоуп без полей → дефолты", TPL_EMPTY, "DEFMODEL", "DEFEFFORT", "DEFBUDGET")
check("fable отклоняется → дефолт модели", TPL_FABLE, "DEFMODEL", "high", "DEFBUDGET")

print(f"\nИтог: {'все прошли' if not fails else f'ПРОВАЛОВ: {fails}'}")
sys.exit(1 if fails else 0)
