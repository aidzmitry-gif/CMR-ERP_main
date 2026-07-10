"""Полная сверка декабря 2025: import cache vs dev.db vs API."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "import_2025-12"
DB = ROOT / "dev.db"
API = "http://127.0.0.1:8000/sales/kpis?period=2025-12"
OPEN = ("new", "qual", "prop", "contract", "appr", "protected")


def load_jsonl(name: str) -> list[dict]:
    path = CACHE / name
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def cache_stats() -> dict:
    deals = load_jsonl("bx_deals.jsonl")
    calls = load_jsonl("bx_calls.jsonl")
    sales = load_jsonl("onec_sales.jsonl")
    dates_d = sorted({d.get("DATE_CREATE", "")[:10] for d in deals if d.get("DATE_CREATE")})
    dates_c = sorted({c.get("CALL_START_DATE", "")[:10] for c in calls if c.get("CALL_START_DATE")})
    dates_s = sorted({str(s.get("Date", ""))[:10] for s in sales if s.get("Date")})
    bad_d = sum(1 for d in dates_d if not d.startswith("2025-12"))
    bad_c = sum(1 for c in dates_c if not c.startswith("2025-12"))
    bad_s = sum(1 for s in dates_s if not s.startswith("2025-12"))
    return {
        "deals": len(deals),
        "won_bitrix": sum(1 for d in deals if d.get("STAGE_ID") == "WON"),
        "calls": len(calls),
        "sales": len(sales),
        "sales_sum": sum(float(x.get("СуммаДокумента") or 0) for x in sales),
        "dates_deals": (dates_d[0], dates_d[-1]) if dates_d else None,
        "dates_calls": (dates_c[0], dates_c[-1]) if dates_c else None,
        "dates_sales": (dates_s[0], dates_s[-1]) if dates_s else None,
        "out_of_month": bad_d + bad_c + bad_s,
    }


def db_stats() -> dict:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    dec = "created_at >= '2025-12-01' AND created_at < '2026-01-01'"
    rev = cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payment "
        "WHERE kind='receivable' AND paid_at >= '2025-12-01' AND paid_at < '2026-01-01'"
    ).fetchone()
    calls = cur.execute(
        "SELECT COUNT(*) FROM call_log WHERE started_at >= '2025-12-01' AND started_at < '2026-01-01'"
    ).fetchone()[0]
    won = cur.execute(
        f"SELECT COUNT(*), COALESCE(SUM(amount),0) FROM deal WHERE stage IN ('won','rp_won') AND {dec}"
    ).fetchone()
    new_deals = cur.execute(f"SELECT COUNT(*) FROM deal WHERE {dec}").fetchone()[0]
    bx = cur.execute("SELECT COUNT(*) FROM deal WHERE number LIKE 'BX-%'").fetchone()[0]
    nc_total = cur.execute("SELECT COUNT(*) FROM deal WHERE funnel='new_clients'").fetchone()[0]
    kanban = {}
    for st in OPEN:
        row = cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM deal WHERE funnel='new_clients' AND stage=?",
            (st,),
        ).fetchone()
        if row[0]:
            kanban[st] = {"count": row[0], "sum": float(row[1])}
    con.close()
    return {
        "payments_n": rev[0],
        "payments_sum": float(rev[1]),
        "calls": calls,
        "won_n": won[0],
        "won_sum": float(won[1]),
        "new_deals_dec": new_deals,
        "bx_total": bx,
        "new_clients_total": nc_total,
        "kanban": kanban,
    }


def api_stats() -> dict:
    r = requests.get(API, headers={"X-User-Roles": "director"}, timeout=15)
    r.raise_for_status()
    by = {x["key"]: x for x in r.json()}
    keys = ("ship_plan", "payments_vat", "calls_all", "won_count", "new_deals_count", "gross_profit")
    return {k: {"actual": by[k]["actual"], "target": by[k]["target"]} for k in keys if k in by}


def main() -> int:
    print("=== СВЕРКА ДЕКАБРЬ 2025 ===\n")
    c = cache_stats()
    d = db_stats()
    try:
        a = api_stats()
    except Exception as exc:
        print(f"API: НЕДОСТУПЕН ({exc})")
        return 1

    checks: list[tuple[str, bool, str]] = []

    checks.append(("Кэш: даты только в декабре", c["out_of_month"] == 0, f"вне месяца: {c['out_of_month']}"))
    checks.append(("Кэш: 280 сделок Bitrix", c["deals"] == 280, str(c["deals"])))
    checks.append(("Кэш: 1871 звонков", c["calls"] == 1871, str(c["calls"])))
    checks.append(("Кэш: 192 реализации 1С", c["sales"] == 192, str(c["sales"])))
    checks.append(("Кэш: сумма 1С ~438936", abs(c["sales_sum"] - 438935.97) < 1, f"{c['sales_sum']:,.2f}"))

    checks.append(("БД: 1871 звонков", d["calls"] == 1871, str(d["calls"])))
    checks.append(("БД: 192 платежа", d["payments_n"] == 192, str(d["payments_n"])))
    checks.append(("БД: выручка ~438936", abs(d["payments_sum"] - 438935.97) < 1, f"{d['payments_sum']:,.2f}"))
    checks.append(("БД: 123 won", d["won_n"] == 123, str(d["won_n"])))
    checks.append(("БД: 259 сделок created в дек", d["new_deals_dec"] == 259, str(d["new_deals_dec"])))
    checks.append(("БД: канбан new=5", d["kanban"].get("new", {}).get("count") == 5, str(d["kanban"].get("new"))))
    checks.append(("БД: канбан qual=3", d["kanban"].get("qual", {}).get("count") == 3, str(d["kanban"].get("qual"))))

    checks.append(("API=БД выручка", abs(a["ship_plan"]["actual"] - d["payments_sum"]) < 1, f"api {a['ship_plan']['actual']}"))
    checks.append(("API=БД звонки", a["calls_all"]["actual"] == d["calls"], f"api {a['calls_all']['actual']}"))
    checks.append(("API=БД won", a["won_count"]["actual"] == d["won_n"], f"api {a['won_count']['actual']}"))
    checks.append(("API=БД новые", a["new_deals_count"]["actual"] == d["new_deals_dec"], f"api {a['new_deals_count']['actual']}"))
    checks.append(("Маржа пока 0 (ожидаемо)", a["gross_profit"]["actual"] == 0, "ok"))

    # load gap
    gap = c["deals"] - d["new_deals_dec"]
    checks.append(("Разрыв extract->БД сделок 21", gap == 21, "280->259, отсев воронок при load"))

    ok = 0
    for name, passed, detail in checks:
        mark = "OK" if passed else "FAIL"
        if passed:
            ok += 1
        print(f"[{mark}] {name}: {detail}")

    print(f"\nИтого: {ok}/{len(checks)} проверок пройдено")
    print("\nКанбан (вся воронка, не только дек):")
    print(f"  new_clients всего: {d['new_clients_total']} (UI ~467)")
    for st, v in d["kanban"].items():
        print(f"  {st}: {v['count']} / {v['sum']:,.0f} Br")

    return 0 if ok == len(checks) else 2


if __name__ == "__main__":
    sys.exit(main())
