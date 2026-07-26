# -*- coding: utf-8 -*-
r"""Во что обходятся сессии флота — из транскриптов Claude Code, а не на глаз.

Зачем: два решения нельзя принять без цифр — какой ставить `--max-budget-usd` воркеру
(слишком низкий обрывает его на середине: деньги потрачены, результата нет) и куда
на самом деле уходит расход. Первый же замер 25.07.2026 показал, что 99% расхода дают
НЕ воркеры, а долгоживущие ручные сессии — см. `coordination/PLAYBOOK.md §5` про гигиену.

Запуск:  .\.venv\Scripts\python.exe scripts\session_costs.py

Считает по `usage` ассистентских сообщений в `~/.claude/projects/**/*.jsonl`. Цифры —
эквивалент по прайсу API; на подписке это мера ПОТРЕБЛЕНИЯ, а не выставленный счёт,
но `--max-budget-usd` меряет ровно в них, поэтому лимиты выбираются по этой шкале.
"""
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_cfg = os.environ.get("CLAUDE_CONFIG_DIR")
ROOT = (Path(_cfg) if _cfg else Path.home() / ".claude") / "projects"

# $/Мтокен (вход, выход). Кэш-чтение = 0.1× входа. Кэш-ЗАПИСЬ зависит от срока хранения:
# 5-минутный = 1.25× входа, часовой = 2×. Разбивку даёт `usage.cache_creation`
# (`ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`). Плоские 1.25× занижали расход:
# сессии этого проекта идут с ЧАСОВЫМ кэшем, а это самая крупная статья в длинном диалоге.
# Порядок важен: ключи проверяются подстрокой, "opus-5" должен идти раньше "opus-4".
PRICES = {
    "opus-5": (5.0, 25.0), "fable-5": (10.0, 50.0),
    "sonnet-5": (3.0, 15.0), "haiku-4-5": (1.0, 5.0),
    "opus-4": (15.0, 75.0), "sonnet-4": (3.0, 15.0),
}
WORKER_MARK = "crm-worker-"   # каталоги воркеров, поднятых spawn_workers.py


UNKNOWN = "неизвестно"


def model_key(model: str) -> str:
    """Ключ прайса по имени модели из транскрипта; UNKNOWN, если не распознали."""
    m = (model or "").lower()
    return next((k for k in PRICES if k in m), UNKNOWN)


def price(model: str) -> tuple[float, float]:
    # неизвестную модель считаем как Sonnet, чтобы не занижать расход
    return PRICES.get(model_key(model), (3.0, 15.0))


def session_cost(path: Path) -> tuple[float, str]:
    total, model_seen = 0.0, ""
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"usage"' not in line:      # дешёвый отсев до json.loads
                    continue
                try:
                    msg = json.loads(line).get("message") or {}
                except json.JSONDecodeError:
                    continue
                u = msg.get("usage")
                if not isinstance(u, dict):
                    continue
                pin, pout = price(msg.get("model", ""))
                model_seen = msg.get("model", "") or model_seen
                cc = u.get("cache_creation")
                if isinstance(cc, dict):
                    write = (cc.get("ephemeral_5m_input_tokens", 0) * 1.25
                             + cc.get("ephemeral_1h_input_tokens", 0) * 2.0)
                else:  # старые транскрипты без разбивки — считаем по 5-минутной ставке
                    write = u.get("cache_creation_input_tokens", 0) * 1.25
                total += (u.get("input_tokens", 0) * pin
                          + write * pin
                          + u.get("cache_read_input_tokens", 0) * pin * 0.10
                          + u.get("output_tokens", 0) * pout) / 1_000_000
    except OSError:
        pass
    return total, model_seen


def report(title: str, rows: list) -> None:
    if not rows:
        print(f"\n{title}: нет данных")
        return
    rows.sort(reverse=True)
    costs = sorted(c for c, *_ in rows)
    n = len(costs)
    print(f"\n=== {title}: {n} сессий, всего ${sum(costs):.2f}")
    print(f"    медиана ${costs[n // 2]:.2f} · 90-й перцентиль "
          f"${costs[min(n - 1, int(n * 0.9))]:.2f} · максимум ${costs[-1]:.2f}")
    print("    самые дорогие:")
    for c, model, proj, sid in rows[:8]:
        print(f"      ${c:8.2f}  {model or '?':22} {proj[-34:]}  {sid}")


def main() -> int:
    if not ROOT.is_dir():
        print(f"нет каталога транскриптов: {ROOT}", file=sys.stderr)
        return 1
    workers: list = []
    manual: list = []
    for d in ROOT.iterdir():
        if not d.is_dir():
            continue
        bucket = workers if WORKER_MARK in d.name else manual
        for f in d.glob("*.jsonl"):
            cost, model = session_cost(f)
            if cost > 0.001:
                bucket.append((cost, model, d.name, f.stem[:8]))

    report("ВОРКЕРЫ (spawn_workers)", workers)
    report("РУЧНЫЕ/ОРКЕСТРАТОРСКИЕ сессии", manual)

    by_model: dict[str, float] = {}
    for cost, model, *_ in workers + manual:
        key = model_key(model)
        by_model[key] = by_model.get(key, 0.0) + cost
    grand = sum(by_model.values()) or 1.0
    print("\n=== Расход по моделям (все сессии)")
    for k, v in sorted(by_model.items(), key=lambda kv: -kv[1]):
        print(f"    {k:12} ${v:9.2f}  {v / grand * 100:5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
