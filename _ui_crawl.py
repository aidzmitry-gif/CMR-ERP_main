# ui-crawl headless: browser-audit.js логика × (light/dark) × (1440/768/390) + click-through.
# Запуск: python _ui_crawl.py <file.html> [<file2.html> ...]
import pathlib
import sys

from playwright.sync_api import sync_playwright

FILES = sys.argv[1:] or ["sales-card-full.html"]
BASE = "http://127.0.0.1:8899/"
AUDIT_JS = pathlib.Path(".claude/skills/ui-crawl/scripts/browser-audit.js").read_text(encoding="utf-8")
# вырезаем шапку-комментарий: реальная функция — ПОСЛЕДНее "() => {" (первое сидит в комментарии)
AUDIT_FN = AUDIT_JS[AUDIT_JS.rindex("() => {"):]

WIDTHS = [1440, 768, 390]
THEMES = ["light", "dark"]

with sync_playwright() as p:
    b = p.chromium.launch()
    for f in FILES:
        url = BASE + f + "?v=crawl"
        print(f"\n========== {f} ==========")
        # --- consoleошибки + клик-через на одной загрузке (десктоп, светлая) ---
        pg = b.new_page(viewport={"width":1440,"height":900})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
        pg.goto(url, wait_until="networkidle")
        pg.wait_for_timeout(200)
        # клик-через: тема, открыть счёт, договор, заказ-наряд, закрыть; переход стадии
        clicks = [
            ("toggle theme", "#themeTgl"),
            ("toggle theme back", "#themeTgl"),
        ]
        clicked = []
        for label, sel in clicks:
            try:
                el = pg.query_selector(sel)
                if el:
                    el.click(timeout=1500)
                    pg.wait_for_timeout(120)
                    clicked.append(f"{label}:ok")
                else:
                    clicked.append(f"{label}:NO-EL")
            except Exception as e:
                clicked.append(f"{label}:ERR {str(e)[:40]}")
        print("  click-through:", "; ".join(clicked))
        print("  console errors:", len([e for e in errs if "favicon" not in e]) or "0 ✓")
        if errs:
            for e in errs[:6]:
                if "favicon" not in e:
                    print("    [err]", e[:120])

        # --- визуальный + dead-click аудит на всех ширинах × темах ---
        for theme in THEMES:
            for w in WIDTHS:
                pg.set_viewport_size({"width":w, "height":900})
                pg.goto(url, wait_until="networkidle")
                pg.evaluate("(t)=>document.documentElement.classList.toggle('dark',t==='dark')", theme)
                pg.wait_for_timeout(150)
                res = pg.evaluate(f"({AUDIT_FN})()")
                s = res["summary"]
                labels = {
                    "onclickBad": "onclickBad", "deadClickables": "dead",
                    "beyondViewport": "overflow", "clipped": "clipped",
                    "overlap": "overlap", "tinyText": "tiny",
                }
                flags = [f"{lbl}={s[k]}" for k, lbl in labels.items() if s[k]]
                if s["pageScrollX"]:
                    flags.append("H-SCROLL")
                # проверка выравнивания: соседние кнопки-иконки в группе должны быть на одной линии
                misalign = pg.evaluate(r"""()=>{
                    const groups=document.querySelectorAll('.c-acts,.doc-acts,.chs,.cc-sub,.h-actions,.nav-right');
                    const bad=[];
                    groups.forEach(g=>{
                        const kids=[...g.children].filter(e=>e.getBoundingClientRect().height>0);
                        if(kids.length<2)return;
                        const tops=kids.map(e=>Math.round(e.getBoundingClientRect().top));
                        const spread=Math.max(...tops)-Math.min(...tops);
                        if(spread>2)bad.push({cls:(g.className||'').toString().slice(0,24),spread});
                    });
                    return bad;
                }""")
                if misalign:
                    flags.append(f"misalign={len(misalign)}")
                status = "  ".join(flags) if flags else "чисто OK"
                print(f"  [{theme:5} {w:>4}px] {status}")
                for m in (misalign or [])[:6]:
                    print(f"      misalign .{m['cls']} spread={m['spread']}px")
                # детали для значимых проблем
                if s["deadClickables"]:
                    for d in res["deadClickables"][:8]:
                        print(f"      dead: <{d['tag']} .{d['cls']}> '{d['txt']}'")
                if s["beyondViewport"]:
                    for d in res["visual"]["beyondViewport"][:6]:
                        print(f"      overflow .{d['cls']} right={d['right']} '{d['txt']}'")
                if s["tinyText"]:
                    for d in res["visual"]["tinyText"][:6]:
                        print(f"      tiny {d['px']}px '{d['txt']}'")
        pg.close()
    b.close()
print("\nui-crawl завершён.")
