// Пакетная миграция HTML-макетов Sales 2.0 на дизайн-систему с ДВУМЯ темами.
// Механический слой контракта (coordination/mockup-redesign-tokens.md):
//  Inter+anti-flash, токены-значения, surface/sunken/line, поля ввода, бренд-каналы, синий→accent,
//  + аппенд двухтемного слоя (:root / html.dark) В КОНЕЦ <style> (перекрывает любые имена переменных).
// Переключатель темы в шапку и ручную доводку html.dark-бейджей делает оператор по каждому экрану.
// Идемпотентно. Запуск: node _redesign_mockups.mjs [--check]
import fs from 'node:fs';

const CHECK = process.argv.includes('--check');
const FILES = fs.readdirSync('.')
  .filter(f => /^sales-.*\.html$/.test(f))
  .filter(f => !f.endsWith('-old.html'))
  .filter(f => f !== 'sales-card-full.html')          // эталон уже готов вручную
  .filter(f => f !== 'sales-deals-spec-preview.html') // спец-тёмный экран — мигрирую вручную
  .sort();

const FONT_LINKS =
`<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,500;14..32,600;14..32,700;14..32,800&display=swap" rel="stylesheet">
<script>(function(){try{var t=localStorage.getItem('theme');if(t==='dark')document.documentElement.classList.add('dark');}catch(e){}})();<\/script>`;

// Двухтемный слой переопределения — аппендится в конец <style>. Перекрывает значения переменных
// независимо от того, как файл их объявил (--brand / --brand50 / --card и т.п.).
const THEME_LAYER = `
/* ═══ ДИЗАЙН-СИСТЕМА: 2 темы (C/D). Аппенд-слой перекрывает значения переменных файла. ═══ */
:root{
  --font:"Inter",system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  --canvas:#EEF1F5; --surface:#fff; --sunken:#F4F6F9;
  --ink:#0F172A; --muted:#5B6B82; --faint:#93A1B5;
  --line:#E2E8F0; --line-strong:#CBD5E1;
  --brand:#1E5EFF; --brand-50:#E3ECFF; --brand50:#E3ECFF; --brand-100:#E3ECFF; --brand100:#E3ECFF;
  --brand-700:#1545CC; --brand700:#1545CC;
  --accent:#1E5EFF; --accent-ink:#1545CC; --accent-soft:#E3ECFF;
  --money:#0E7C4A; --money-soft:#E2F3EA;
  --ok:#0E7C4A; --warn:#B45309; --bad:#DC2626;
  --ai:#7C3AED; --ai-50:#F2EBFE;
  /* статус-софт фоны (светлые в C, тёмные в D) — для бейджей/полос/шапок */
  --green-soft:#ECFDF5; --green-ink:#047857;
  --amber-soft:#FFFBEB; --amber-ink:#B45309;
  --red-soft:#FEF2F2; --red-ink:#B91C1C;
  --blue-soft:#EFF5FF; --blue-ink:#1D4ED8;
  --violet-soft:#EDE9FE; --violet-ink:#6D28D9;
  --shadow-card:0 1px 1px rgba(20,20,40,.03),0 2px 4px rgba(20,20,40,.04),0 6px 16px rgba(20,20,40,.04);
  --card:0 1px 1px rgba(20,20,40,.03),0 2px 4px rgba(20,20,40,.04),0 6px 16px rgba(20,20,40,.04);
  --pop:0 1px 2px rgba(20,20,40,.06),0 12px 28px rgba(20,20,40,.12);
}
html.dark{
  --canvas:#0E1116; --surface:#171B22; --sunken:#1F242C;
  --ink:#E8EAED; --muted:#9BA3AE; --faint:#6B7280;
  --line:#2A3038; --line-strong:#3A424C;
  --brand:#6E8BFF; --brand-50:#232A3D; --brand50:#232A3D; --brand-100:#232A3D; --brand100:#232A3D;
  --brand-700:#8AA0FF; --brand700:#8AA0FF;
  --accent:#6E8BFF; --accent-ink:#8AA0FF; --accent-soft:#232A3D;
  --money:#34D399; --money-soft:#16271F;
  --ok:#34D399; --warn:#FBBF24; --bad:#F87171;
  --ai:#A78BFA; --ai-50:#241B3A;
  --green-soft:#16271F; --green-ink:#34D399;
  --amber-soft:#2A2114; --amber-ink:#FBBF24;
  --red-soft:#3A1D1D; --red-ink:#F87171;
  --blue-soft:#1B2740; --blue-ink:#7FA8FF;
  --violet-soft:#241B3A; --violet-ink:#C4B5FD;
  --shadow-card:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.4);
  --card:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.4);
  --pop:0 2px 4px rgba(0,0,0,.5),0 18px 40px rgba(0,0,0,.55);
}
html,body{background:var(--canvas);color:var(--ink);font-family:var(--font);-webkit-font-smoothing:antialiased;font-feature-settings:"cv05","ss01";transition:background .2s,color .2s}
/* поля ввода — на токены (иначе белый фон + чёрный текст в тёмной) */
input,select,textarea{background:var(--surface);color:var(--ink)}
input::placeholder,textarea::placeholder{color:var(--faint)}
option{background:var(--surface);color:var(--ink)}
/* нестилизованные ссылки (дефолт-синие) → accent, читаемо в обеих темах */
a:not([class]){color:var(--accent)}
/* приглушить светлые статус-фоны в тёмной (бейджи/полосы), смысл-цвет сохраняем */
html.dark .st.posted,html.dark .ds.done,html.dark .c-main,html.dark .sent.pos,html.dark .ctag.sig{background:#16271F!important;color:#34D399!important}
html.dark .st.pending,html.dark .cd-badge{background:#2A2114!important;color:#FBBF24!important}
html.dark .st.paid{background:#1B2740!important;color:#7FA8FF!important}
html.dark .st.draft{background:var(--sunken)!important;color:var(--muted)!important}
/* бренд-цвета каналов (channels.tsx / DESIGN.md §4.1) */
.cbtn.call{background:#22C55E!important;border-color:#22C55E!important;color:#fff!important}
.cbtn.wa{background:#25D366!important;border-color:#25D366!important;color:#fff!important}
.cbtn.tg{background:#229ED9!important;border-color:#229ED9!important;color:#fff!important}
.chi{font-style:normal;font-size:11px;line-height:1}
/* переключатель темы (иконка + текст) — фикс. в правом нижнем углу */
.theme-tgl{position:fixed;right:14px;bottom:14px;z-index:9999;display:inline-flex;align-items:center;gap:7px;font-size:12.5px;font-weight:600;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:9px;padding:8px 13px;height:auto;cursor:pointer;transition:.14s;white-space:nowrap;box-shadow:0 4px 14px rgba(16,24,40,.12)}
.theme-tgl:hover{background:var(--sunken)}
.theme-tgl #themeIco{font-size:15px;line-height:0}
`;

// фикс-кнопка переключателя темы (вставляется сразу после <body>)
const THEME_BTN = `<button class="theme-tgl" id="themeTgl" onclick="toggleTheme()" title="Переключить тему" aria-label="Переключить тему"><span id="themeIco">🌙</span><span id="themeTxt">Тёмная</span></button>`;

const THEME_JS = `
function applyTheme(t){document.documentElement.classList.toggle('dark',t==='dark');var i=document.getElementById('themeIco'),x=document.getElementById('themeTxt');if(i)i.textContent=t==='dark'?'☀️':'🌙';if(x)x.textContent=t==='dark'?'Светлая':'Тёмная';try{localStorage.setItem('theme',t);}catch(e){}}
function toggleTheme(){applyTheme(document.documentElement.classList.contains('dark')?'light':'dark');}
try{if(localStorage.getItem('theme')==='dark')applyTheme('dark');}catch(e){}
/* демо-отклик: кнопки без своего действия показывают тост (чтобы не было «ничего не произошло») */
(function(){
  function dtoast(msg){var t=document.getElementById('_demoToast');if(!t){t=document.createElement('div');t.id='_demoToast';t.style.cssText='position:fixed;left:50%;bottom:64px;transform:translateX(-50%) translateY(10px);background:var(--ink);color:var(--canvas);font:600 13px var(--font);padding:10px 16px;border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.25);z-index:99999;opacity:0;pointer-events:none;transition:.22s;max-width:90vw';document.body.appendChild(t);}t.textContent=msg;t.style.opacity='1';t.style.transform='translateX(-50%) translateY(0)';clearTimeout(t._h);t._h=setTimeout(function(){t.style.opacity='0';t.style.transform='translateX(-50%) translateY(10px)';},1900);}
  document.addEventListener('click',function(e){
    var el=e.target.closest('button,.btn,[class*="btn"],.abtn,.chip,.seg button,.tab,a[role="button"]');
    if(!el)return;
    if(el.id==='themeTgl'||el.closest('#themeTgl'))return;
    if(el.hasAttribute('onclick')||el.closest('[onclick]'))return;
    if(el.tagName==='A'&&el.getAttribute('href')&&el.getAttribute('href')!=='#')return;
    if(getComputedStyle(el).cursor!=='pointer'&&el.tagName!=='BUTTON')return;
    var label=(el.textContent||'').trim().slice(0,32)||'Действие';
    dtoast('Демо: «'+label+'» — действие появится с бэкендом');
  },true);
})();
`;

let touched = 0;
for (const file of FILES) {
  let html = fs.readFileSync(file, 'utf8');
  const before = html;

  // 1) Inter + anti-flash
  if (!html.includes('fonts.googleapis.com/css2?family=Inter')) {
    if (/<meta[^>]*viewport[^>]*>/i.test(html)) html = html.replace(/(<meta[^>]*viewport[^>]*>)/i, `$1\n${FONT_LINKS}`);
    else html = html.replace(/<head[^>]*>/i, m => `${m}\n${FONT_LINKS}`);
  }

  // 2) синий-brand → accent-токен (значения и хардкоды)
  html = html.replace(/#2563EB/g, 'var(--brand)').replace(/#1D4FD7/g, 'var(--brand-700)')
             .replace(/#1E3A8A/g, 'var(--brand-700)')
             .replace(/linear-gradient\(135deg,\s*var\(--brand\),\s*var\(--brand-700\)\)/g,'linear-gradient(135deg,var(--brand),var(--brand-700))');
  // фикс: не плодить рекурсию в ОБЪЯВЛЕНИЯХ переменных (--brand:var(--brand) → реальный hex; аппенд-слой всё равно перебьёт)
  html = html.replace(/(--brand\s*:\s*)var\(--brand\)/g, '$1#1E5EFF')
             .replace(/(--brand-?700\s*:\s*)var\(--brand-700\)/g, '$1#1545CC')
             .replace(/(--accent\s*:\s*)var\(--brand\)/g, '$1#1E5EFF');

  // 3) поверхности/границы/текст → токены
  html = html.replace(/background:\s*#fff(?![0-9a-f])/gi,'background:var(--surface)')
             .replace(/background:\s*#ffffff(?![0-9a-f])/gi,'background:var(--surface)')
             .replace(/background-color:\s*#fff(?![0-9a-f])/gi,'background-color:var(--surface)');
  ['#F8FAFC','#F8FAFD','#FBFBFD','#F9FAFB','#F1F5F9','#F3F4F6','#F1F3F5','#F6F7F9','#FAFAFB','#F5F6F8','#F4F5F7','#EEF0F2','#F2F4F6']
    .forEach(c=>{html=html.replace(new RegExp('background:\\s*'+c+'(?![0-9a-f])','gi'),'background:var(--sunken)')
                          .replace(new RegExp('background-color:\\s*'+c+'(?![0-9a-f])','gi'),'background-color:var(--sunken)');});
  ['#E5E7EB','#EEF0F2','#F1F3F5','#EAECEF','#EDEFF2','#ECECF0']
    .forEach(c=>{html=html.replace(new RegExp('(border[^:;]*:\\s*[^;]*?)'+c,'gi'),'$1var(--line)');});
  ['#CBD5E1','#D1D5DB']
    .forEach(c=>{html=html.replace(new RegExp('(border[^:;]*:\\s*[^;]*?)'+c,'gi'),'$1var(--line-strong)');});
  // тёмные «заголовочные» цвета текста (почти чёрные) → var(--ink) (иначе невидимы в тёмной теме)
  ['#111827','#1F2937','#0F172A','#1A1A23','#111111','#1e293b','#0f172a','#1D2939','#101828']
    .forEach(c=>{html=html.replace(new RegExp('color:\\s*'+c+'(?![0-9a-f])','gi'),'color:var(--ink)');});
  ['#6B7280','#475467','#64748b','#475569','#374151','#5b6573','#334155']
    .forEach(c=>{html=html.replace(new RegExp('color:\\s*'+c+'(?![0-9a-f])','gi'),'color:var(--muted)');});
  ['#9aa3b0','#9CA3AF','#94a3b8','#b0b8c4']
    .forEach(c=>{html=html.replace(new RegExp('color:\\s*'+c+'(?![0-9a-f])','gi'),'color:var(--faint)');});

  // статус-ТЕКСТ (тёмные тоновые цвета) → -ink токены (тёмные в C, светлые в D) — парны к -soft фонам
  const INK = {
    'red':['#B91C1C','#DC2626','#991B1B','#B42318'],
    'amber':['#92400E','#B45309','#9A3412','#854D0E','#78350F','#C2410C','#7C2D12'],
    'green':['#047857','#15803D','#065F46','#027A48','#166534'],
    'blue':['#1D4ED8','#1E40AF','#1E3A8A','#1D4FD7','#3A2D9E'],
    'violet':['#6D28D9','#5B21B6','#6366F1','#4F46E5','#4C1D95','#3730A3','#3b2d63','#3B2D63','#6d5a9c'],
  };
  for (const [tone, hexes] of Object.entries(INK)) {
    for (const c of hexes) html = html.replace(new RegExp('color:\\s*'+c+'(?![0-9a-f])','gi'),'color:var(--'+tone+'-ink)');
  }
  // статус-софт фоны (светлые пастели) → токены (светлые в C, тёмные в D)
  const SOFT = {
    'green':['#ECFDF5','#DCFCE7','#F0FDF4','#ECFDF3','#D1FAE5','#DEF7EC'],
    'amber':['#FFFBEB','#FEF3C7','#FFF7ED','#FFEDD5','#FEF9C3','#FFFBF0','#FEF9E7'],
    'red':['#FEF2F2','#FEE2E2','#FECACA','#FEF3F2'],
    'blue':['#EFF5FF','#EFF6FF','#DBEAFE','#E0E7FF','#EAF1FF','#E3ECFF'],
    'violet':['#EDE9FE','#F5F3FF','#EEE9FE','#F2EBFE','#E9D5FF'],
  };
  for (const [tone, hexes] of Object.entries(SOFT)) {
    for (const c of hexes) {
      html = html.replace(new RegExp('background:\\s*'+c+'(?![0-9a-f])','gi'),'background:var(--'+tone+'-soft)')
                 .replace(new RegExp('background-color:\\s*'+c+'(?![0-9a-f])','gi'),'background-color:var(--'+tone+'-soft)');
    }
  }
  // светлые градиенты AI-панелей/спецблоков → токен (иначе светлое пятно в тёмной)
  html = html.replace(/linear-gradient\(135deg,\s*#F5F3FF,\s*#FAF5FF\)/gi,'var(--ai-50)')
             .replace(/linear-gradient\(135deg,\s*#ECFDF5,\s*#F0FDFA\)/gi,'var(--green-soft)')
             .replace(/linear-gradient\([^)]*#F5F3FF[^)]*\)/gi,'var(--ai-50)')
             .replace(/linear-gradient\([^)]*#FAF5FF[^)]*\)/gi,'var(--ai-50)');
  // светлые «таблично-серые» шапки/бейджи (#FAFBFC.. #E5E7EB как ФОН) → sunken
  ['#FAFBFC','#FAFBFD','#FCFCFD','#FBFCFE','#E5E7EB','#EDF0F2','#F0F1F3']
    .forEach(c=>{html=html.replace(new RegExp('background:\\s*'+c+'(?![0-9a-f])','gi'),'background:var(--sunken)')
                          .replace(new RegExp('background-color:\\s*'+c+'(?![0-9a-f])','gi'),'background-color:var(--sunken)');});

  // 4) системный шрифт на body → var(--font)
  html = html.replace(/font-family:\s*-apple-system,\s*BlinkMacSystemFont,\s*'Segoe UI',\s*Roboto,\s*sans-serif/gi,'font-family:var(--font)')
             .replace(/font:14px\/1\.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif/gi,'font:14px/1.4 var(--font)');

  // 5) аппенд двухтемного слоя в конец первого <style> (один раз)
  if (!html.includes('Аппенд-слой перекрывает')) {
    html = html.replace(/<\/style>/i, THEME_LAYER + '\n</style>');
  }
  // 6) JS переключателя — в конец первого <script>…</script> (один раз)
  if (!html.includes('function toggleTheme(')) {
    html = html.replace(/<\/script>/i, THEME_JS + '\n</script>');
  }
  // 7) фикс-кнопка темы — сразу после <body…> (один раз)
  if (!html.includes('id="themeTgl"')) {
    html = html.replace(/(<body[^>]*>)/i, `$1\n${THEME_BTN}`);
  }

  if (html !== before) {
    if (!CHECK) fs.writeFileSync(file, html, 'utf8');
    const blue=(html.match(/#2563EB|#1D4FD7/g)||[]).length;
    const surf=(html.match(/var\(--surface\)/g)||[]).length;
    console.log(`${CHECK?'WOULD':'OK   '} ${file.padEnd(34)} surface:${surf} blueLeft:${blue}`);
    touched++;
  } else console.log(`skip  ${file}`);
}
console.log(`---\n${CHECK?'будет':'обработано'}: ${touched} из ${FILES.length}`);
