# Аудит макета в ДВУХ темах: getComputedStyle по кнопкам/таблицам/полям/бейджам/панелям.
# Находит «белые пятна» в тёмной теме (светлый фон) и низкий контраст текст/фон.
# Запуск:  python _theme_audit.py <file.html> [<file2.html> ...]
import sys

from playwright.sync_api import sync_playwright

FILES = sys.argv[1:] or ["sales-card-full.html"]
BASE = "http://127.0.0.1:8899/"

# JS: собрать стили по селекторам + найти светлые фоны во ВСЕХ видимых блоках
PROBE = r"""
() => {
  const lum = (c) => { // c = "rgb(r, g, b)" → относительная яркость 0..1
    const m = c.match(/\d+/g); if(!m) return null;
    const [r,g,b] = m.map(Number);
    const f = v => { v/=255; return v<=.03928 ? v/12.92 : Math.pow((v+.055)/1.055,2.4); };
    return .2126*f(r)+.7152*f(g)+.0722*f(b);
  };
  const contrast = (a,b) => { const L1=lum(a),L2=lum(b); if(L1==null||L2==null) return null;
    const hi=Math.max(L1,L2),lo=Math.min(L1,L2); return +((hi+.05)/(lo+.05)).toFixed(2); };
  const isDark = document.documentElement.classList.contains('dark');

  // 1) сэмплы по ролям
  const roles = {
    'btn.primary':'.btn.primary, .ce-save, .dbtn.send, .cc-actions .end',
    'btn':'.btn:not(.primary):not(.danger)',
    'btn.danger':'.btn.danger',
    'panel':'.panel',
    'panel header':'.panel .ph',
    'table head':'.iv-tbl th, .stbl th, .pp-t th, .items .ih',
    'table cell':'.iv-tbl td, .stbl td',
    'input':'input, select, textarea',
    'badge':'.bdg',
    'ai-panel':'.ai-panel',
    'topnav':'.topnav',
    'body':'body',
  };
  const out = {};
  for (const [role, sel] of Object.entries(roles)) {
    const el = document.querySelector(sel);
    if (!el){ out[role] = null; continue; }
    const s = getComputedStyle(el);
    out[role] = { bg:s.backgroundColor, color:s.color, border:s.borderColor,
                  contrast: contrast(s.backgroundColor, s.color) };
  }

  // 2) поиск «белых пятен» в тёмной теме: видимый блок со светлым фоном
  const spots = [];
  if (isDark){
    document.querySelectorAll('div,section,header,td,th,button,input,select,textarea,span,a').forEach(el=>{
      const r = el.getBoundingClientRect();
      if (r.width<40 || r.height<14) return;
      const bg = getComputedStyle(el).backgroundColor;
      const L = lum(bg);
      if (L!=null && L>0.6){ // светлый фон в тёмной теме
        const m = bg.match(/[\d.]+/g);
        const alpha = m && m.length===4 ? parseFloat(m[3]) : 1;
        if (alpha < 0.15) return; // почти прозрачный — не пятно
        spots.push({ cls: (el.className||'').toString().slice(0,40), tag: el.tagName.toLowerCase(),
                     bg, w:Math.round(r.width), h:Math.round(r.height) });
      }
    });
  }
  // дедуп пятен по классу+bg
  const seen={}, uniq=[];
  for(const s of spots){ const k=s.tag+'|'+s.cls+'|'+s.bg; if(!seen[k]){seen[k]=1; uniq.push(s);} }

  // 3) ЧИТАЕМОСТЬ ТЕКСТА: для каждого видимого текст-листа — контраст к эффективному фону
  const effBg = (el)=>{ let n=el; while(n && n!==document.documentElement){ const b=getComputedStyle(n).backgroundColor; const m=b.match(/[\d.]+/g); const a=m&&m.length===4?parseFloat(m[3]):1; if(a>=0.6 && b!=='rgba(0, 0, 0, 0)') return b; n=n.parentElement; } return getComputedStyle(document.body).backgroundColor; };
  const unreadable=[];
  document.querySelectorAll('body *').forEach(el=>{
    if(el.children.length) return;
    const t=(el.textContent||'').trim(); if(!t) return;
    const cs=getComputedStyle(el);
    if(cs.display==='none'||cs.visibility==='hidden'||parseFloat(cs.opacity)<0.3) return;
    const r=el.getBoundingClientRect(); if(r.width<8||r.height<8) return;
    const col=cs.color, bg=effBg(el);
    const c=contrast(bg,col);
    if(c!=null && c<2.0) unreadable.push({txt:t.slice(0,30), color:col, bg, contrast:c, cls:(el.className||'').toString().slice(0,30)});
  });
  const seen2={}, uniq2=[];
  for(const u of unreadable){ const k=u.cls+'|'+u.color; if(!seen2[k]){seen2[k]=1; uniq2.push(u);} }

  return { roles: out, spots: uniq.slice(0,40), spotCount: spots.length, unreadable: uniq2.slice(0,30), unreadableCount: unreadable.length };
}
"""

def low_contrast(roles):
    bad=[]
    for r,v in roles.items():
        if v and v.get('contrast') is not None and v['contrast'] < 3.0 and r not in ('topnav',):
            bad.append((r, v['contrast'], v['bg'], v['color']))
    return bad

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={'width':1280,'height':900})
    for f in FILES:
        url = BASE + f
        print(f"\n===== {f} =====")
        for theme in ('light','dark'):
            pg.goto(url, wait_until='networkidle')
            pg.evaluate("(t)=>{document.documentElement.classList.toggle('dark', t==='dark');}", theme)
            pg.wait_for_timeout(250)
            res = pg.evaluate(PROBE)
            tag = f.replace('.html','')
            pg.screenshot(path=f"_audit-{tag}-{theme}.png", full_page=False)
            ucount = res.get('unreadableCount', 0)
            print(f"  --- {theme} ---  белых пятен: {res['spotCount']} | нечитаемый текст: {ucount}")
            lc = low_contrast(res['roles'])
            if lc:
                for role,c,bg,col in lc:
                    print(f"    [контраст {c}] [{role}]  bg={bg} text={col}")
            if theme=='dark' and res['spots']:
                for s in res['spots'][:8]:
                    print(f"    [пятно] <{s['tag']} class='{s['cls']}'>  bg={s['bg']}  {s['w']}x{s['h']}")
            if res.get('unreadable'):
                for u in res['unreadable'][:12]:
                    print(f"    [НЕЧИТАЕМО c={u['contrast']}] '{u['txt']}' cls='{u['cls']}' color={u['color']} bg={u['bg']}")
    b.close()
print("\nскриншоты: _audit-<file>-light.png / -dark.png")
