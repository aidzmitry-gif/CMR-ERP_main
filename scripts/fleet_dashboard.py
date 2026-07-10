#!/usr/bin/env python3
"""fleet_dashboard.py — кокпит флота: один self-contained HTML из живого состояния.

Читает координационное состояние (без пере-замера — те же файлы, что ведёт флот):

  • coordination/readiness.json      — % готовности модулей (единый источник, § readiness.py)
  • coordination/.quality-log.jsonl  — лят-гейты качества (пишет claude_stop_hook.py)
  • coordination/PUSH-LOG.md         — лента пушей (пишет claude_pushlog_hook.py)

Рендерит coordination/fleet-dashboard.html — self-contained (без внешних ассетов),
тема light/dark по prefers-color-scheme. Регенерируется прогоном, руками НЕ правится.

    python scripts/fleet_dashboard.py            # → coordination/fleet-dashboard.html

Философия как у остальных хуков: fail-open по частям — нет readiness.json → пустая шапка,
нет quality-log → панель качества скрыта; скрипт не падает на отсутствии файла.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COORD = ROOT / "coordination"
OUT = COORD / "fleet-dashboard.html"

QUALITY_TAIL = 60   # последних прогонов гейта на спарклайн/статистику
PUSH_TAIL = 12      # последних пушей в ленте


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _load_quality(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for ln in lines[-QUALITY_TAIL:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


# «- `date` · сессия `sid` · ветка `br` · **hash** msg»
_PUSH_RE = re.compile(
    r"^- `(?P<date>[^`]+)`.*?ветка `(?P<branch>[^`]+)`.*?\*\*(?P<hash>[0-9a-f]+)\*\* ?(?P<msg>.*)$"
)


def _load_pushes(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for ln in lines:
        m = _PUSH_RE.match(ln.strip())
        if m:
            out.append(m.groupdict())
    return out[-PUSH_TAIL:][::-1]  # свежие сверху


def _band(pct: int) -> str:
    """Цветовая полоса готовности → CSS-класс."""
    if pct >= 85:
        return "hi"
    if pct >= 60:
        return "mid"
    if pct >= 30:
        return "lo"
    return "min"


def _e(s: object) -> str:
    return html.escape(str(s))


def _module_row(name: str, m: dict) -> str:
    pct = int(m.get("pct", 0))
    band = _band(pct)
    sub = "".join(
        f'<div class="sub"><span class="k">{_e(k)}</span>'
        f'<span class="track"><i style="width:{int(m.get(k, 0))}%"></i></span>'
        f'<span class="v">{int(m.get(k, 0))}</span></div>'
        for k in ("backend", "frontend", "data")
        if k in m
    )
    return f"""
    <article class="mod {band}">
      <header>
        <h3>{_e(name)}</h3>
        <span class="pct">{pct}<small>%</small></span>
      </header>
      <div class="track big"><i style="width:{pct}%"></i></div>
      <div class="subs">{sub}</div>
      <p class="note">{_e(m.get("note", ""))}</p>
    </article>"""


def _quality_panel(runs: list[dict]) -> str:
    if not runs:
        return ""
    ok = sum(1 for r in runs if r.get("ruff_ok") and r.get("tsc_ok"))
    rate = round(100 * ok / len(runs))
    spark = "".join(
        f'<i class="{"g" if (r.get("ruff_ok") and r.get("tsc_ok")) else "b"}" '
        f'title="ruff:{r.get("ruff_ok")} tsc:{r.get("tsc_ok")} touched:{r.get("touched")}"></i>'
        for r in runs
    )
    return f"""
    <section class="panel">
      <h2>Гейт качества <small>последних {len(runs)} ходов</small></h2>
      <div class="qhead"><span class="qrate">{rate}%</span> ходов прошли ruff+tsc чисто</div>
      <div class="spark">{spark}</div>
    </section>"""


def _push_panel(pushes: list[dict]) -> str:
    if not pushes:
        return ""
    rows = "".join(
        f'<li><code>{_e(p["hash"][:7])}</code>'
        f'<span class="br">{_e(p["branch"])}</span>'
        f'<span class="msg">{_e(p["msg"][:90])}</span>'
        f'<time>{_e(p["date"])}</time></li>'
        for p in pushes
    )
    return f"""
    <section class="panel">
      <h2>Свежие пуши <small>PUSH-LOG</small></h2>
      <ul class="pushes">{rows}</ul>
    </section>"""


def render(readiness: dict, runs: list[dict], pushes: list[dict]) -> str:
    mods = readiness.get("modules", {})
    ordered = sorted(mods.items(), key=lambda kv: kv[1].get("pct", 0), reverse=True)
    cards = "".join(_module_row(n, m) for n, m in ordered)
    overall = int(readiness.get("overall_pct", 0))
    updated = _e(readiness.get("updated", "—"))
    note = _e(readiness.get("overall_note", ""))
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Кокпит флота</title>
<style>
  :root {{
    --bg:#f7f8fa; --panel:#fff; --ink:#1a1d24; --soft:#5b6270; --line:#e6e8ee;
    --hi:#16a34a; --mid:#2563eb; --lo:#d97706; --min:#dc2626; --g:#16a34a; --b:#dc2626;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0e1117; --panel:#161b22; --ink:#e6edf3; --soft:#8b949e; --line:#232a33;
      --hi:#3fb950; --mid:#58a6ff; --lo:#d29922; --min:#f85149; --g:#3fb950; --b:#f85149; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:24px; background:var(--bg); color:var(--ink);
    font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  .wrap {{ max-width:1080px; margin:0 auto; }}
  .hero {{ display:flex; align-items:baseline; gap:16px; flex-wrap:wrap; margin-bottom:4px; }}
  .hero h1 {{ font-size:20px; margin:0; }}
  .big-pct {{ font-size:40px; font-weight:700; line-height:1; }}
  .big-pct small {{ font-size:18px; color:var(--soft); font-weight:500; }}
  .meta {{ color:var(--soft); font-size:12px; margin:2px 0 14px; }}
  .overall-note {{ color:var(--soft); font-size:13px; margin:0 0 20px; max-width:820px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:12px; }}
  .mod {{ background:var(--panel); border:1px solid var(--line); border-left-width:4px;
    border-radius:10px; padding:12px 14px; }}
  .mod.hi {{ border-left-color:var(--hi); }} .mod.mid {{ border-left-color:var(--mid); }}
  .mod.lo {{ border-left-color:var(--lo); }} .mod.min {{ border-left-color:var(--min); }}
  .mod header {{ display:flex; justify-content:space-between; align-items:baseline; }}
  .mod h3 {{ margin:0; font-size:15px; text-transform:capitalize; }}
  .pct {{ font-size:22px; font-weight:700; }} .pct small {{ font-size:12px; color:var(--soft); }}
  .track {{ background:var(--line); border-radius:99px; overflow:hidden; height:5px; }}
  .track.big {{ height:7px; margin:8px 0 10px; }}
  .track i {{ display:block; height:100%; background:var(--mid); border-radius:99px; }}
  .mod.hi .track.big i {{ background:var(--hi); }} .mod.lo .track.big i {{ background:var(--lo); }}
  .mod.min .track.big i {{ background:var(--min); }}
  .subs {{ display:grid; gap:5px; margin-bottom:8px; }}
  .sub {{ display:grid; grid-template-columns:64px 1fr 26px; align-items:center; gap:8px;
    font-size:11px; color:var(--soft); }}
  .sub .track {{ height:5px; }} .sub .v {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .note {{ margin:0; font-size:12px; color:var(--soft); }}
  .panels {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:20px; }}
  @media (max-width:720px) {{ .panels {{ grid-template-columns:1fr; }} }}
  .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .panel h2 {{ font-size:14px; margin:0 0 10px; }} .panel h2 small {{ color:var(--soft); font-weight:400; }}
  .qhead {{ font-size:13px; color:var(--soft); margin-bottom:8px; }}
  .qrate {{ font-size:24px; font-weight:700; color:var(--ink); }}
  .spark {{ display:flex; gap:2px; align-items:flex-end; }}
  .spark i {{ width:6px; height:18px; border-radius:2px; }}
  .spark i.g {{ background:var(--g); }} .spark i.b {{ background:var(--b); }}
  .pushes {{ list-style:none; margin:0; padding:0; display:grid; gap:7px; }}
  .pushes li {{ display:grid; grid-template-columns:auto auto 1fr; gap:8px; align-items:baseline;
    font-size:12px; border-bottom:1px solid var(--line); padding-bottom:6px; }}
  .pushes code {{ color:var(--mid); }} .pushes .br {{ color:var(--soft); font-size:11px; }}
  .pushes .msg {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .pushes time {{ grid-column:3; color:var(--soft); font-size:10px; }}
  footer {{ color:var(--soft); font-size:11px; margin-top:20px; text-align:center; }}
</style></head>
<body><div class="wrap">
  <div class="hero">
    <h1>Кокпит флота</h1>
    <span class="big-pct">{overall}<small>%</small></span>
  </div>
  <div class="meta">обновлено {updated} · источник coordination/readiness.json · регенерация: python scripts/fleet_dashboard.py</div>
  <p class="overall-note">{note}</p>
  <div class="grid">{cards}</div>
  <div class="panels">{_quality_panel(runs)}{_push_panel(pushes)}</div>
  <footer>Читает живое состояние флота — не редактируется руками. Пере-генерируй после смены readiness.json.</footer>
</div></body></html>"""


def main() -> int:
    try:  # Windows-консоль бывает cp1251 — путь с кириллицей рушит print
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    html_out = render(
        _load_json(COORD / "readiness.json"),
        _load_quality(COORD / ".quality-log.jsonl"),
        _load_pushes(COORD / "PUSH-LOG.md"),
    )
    OUT.write_text(html_out, encoding="utf-8")
    print(f"[fleet-dashboard] -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
