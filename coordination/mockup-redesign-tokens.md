# Редизайн HTML-макетов Sales 2.0 — ЕДИНЫЙ КОНТРАКТ (2 темы)

Перевести статичный HTML-макет `sales-*.html` на дизайн-систему продукта: **2 темы
(светлая C / тёмная D) с переключателем**, токены = живой продукт. Эталон уже сделан —
**`sales-card-full.html`** (смотри его как образец; повторяй его решения 1:1).
Каноны: `frontend/DESIGN.md`, `frontend/src/app/globals.css`, `frontend/src/components/ui/button.tsx`,
`frontend/src/components/theme-toggle.tsx`, `frontend/src/components/channels.tsx`.

## Правило: НИЧЕГО не выдумывать

Цвет/кнопку/иконку **не сочиняй** — бери из эталона `sales-card-full.html` или из продукта.
Нет подходящего — спроси (NEEDS-ORCHESTRATOR-ANSWER), не изобретай.

## Шаги (повторить ровно как в эталоне)

### 0. Сохранить старую копию
Если нет `sales-X-old.html` — скопировать `sales-X.html` → `sales-X-old.html` ДО правок.
(Оператор уже создал -old для всех; не перезаписывать существующую.)

### 1. Inter + anti-flash в `<head>`
После `<meta viewport>`:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,500;14..32,600;14..32,700;14..32,800&display=swap" rel="stylesheet">
<script>(function(){try{var t=localStorage.getItem('theme');if(t==='dark')document.documentElement.classList.add('dark');}catch(e){}})();</script>
```

### 2. Двухтемные токены — В НАЧАЛО `<style>` (перед/вместо старого `:root`)
ВАЖНО: сохранить ВСЕ имена переменных, что уже использует файл (`--brand`, `--brand-50`/`--brand50`,
`--canvas`, `--ink`, `--muted`, `--shadow-card`/`--card`, `--ok/warn/bad`, `--ai`, `--line` и т.п.) —
переопредели их ЗНАЧЕНИЯ в этом блоке; добавь недостающие (`--surface/--sunken/--faint/--line-strong/
--accent*/--money*`). Скопируй блок из эталона `sales-card-full.html` (строки `:root{…}` и `html.dark{…}`),
адаптировав имена под конкретный файл (где `--brand50` без дефиса — добавь и его).

Светлая (C): canvas `#EEF1F5` surface `#fff` sunken `#F4F6F9` ink `#0F172A` muted `#5B6B82`
faint `#93A1B5` line `#E2E8F0` line-strong `#CBD5E1` **accent `#1E5EFF`** accent-ink `#1545CC`
accent-soft `#E3ECFF` **money `#0E7C4A`** money-soft `#E2F3EA` ok `#0E7C4A` warn `#B45309` bad `#DC2626` ai `#7C3AED`.
Тёмная (D, `html.dark`): canvas `#0E1116` surface `#171B22` sunken `#1F242C` ink `#E8EAED`
muted `#9BA3AE` faint `#6B7280` line `#2A3038` line-strong `#3A424C` **accent `#6E8BFF`** accent-ink `#8AA0FF`
accent-soft `#232A3D` **money `#34D399`** money-soft `#16271F` ok `#34D399` warn `#FBBF24` bad `#F87171` ai `#A78BFA`.

### 3. Шрифт на body
`font-family:var(--font)` (`--font:"Inter",system-ui,…`), добавить `-webkit-font-smoothing:antialiased;font-feature-settings:"cv05","ss01"`.

### 4. Переключатель темы — кнопка с иконкой И ТЕКСТОМ (утв. вид)
В шапку (topnav / nav-right). Стиль (обводка-secondary, иконка ☀/🌙 + подпись):
```css
.theme-tgl{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;font-weight:600;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:8px;padding:0 12px;height:34px;cursor:pointer;transition:.14s;white-space:nowrap}
.theme-tgl:hover{background:var(--sunken)}
.theme-tgl #themeIco{font-size:15px;line-height:0}
```
Разметка: `<button class="theme-tgl" id="themeTgl" onclick="toggleTheme()" title="Переключить тему"><span id="themeIco">🌙</span><span id="themeTxt">Тёмная</span></button>`
JS (в начало первого `<script>`): в светлой теме показывает «🌙 Тёмная», в тёмной — «☀️ Светлая».
```js
function applyTheme(t){document.documentElement.classList.toggle('dark',t==='dark');var i=document.getElementById('themeIco'),x=document.getElementById('themeTxt');if(i)i.textContent=t==='dark'?'☀️':'🌙';if(x)x.textContent=t==='dark'?'Светлая':'Тёмная';try{localStorage.setItem('theme',t);}catch(e){}}
function toggleTheme(){applyTheme(document.documentElement.classList.contains('dark')?'light':'dark');}
try{if(localStorage.getItem('theme')==='dark')applyTheme('dark');}catch(e){}
```
Если шапки нет (полноэкранный экран) — поставить кнопку в правый верхний угол `position:fixed`.

### 5. Перевод хардкод-цветов на токены (КРИТИЧНО для тёмной темы)
- `background:#fff`/`#ffffff` (фон карточек/панелей/модалок) → `background:var(--surface)`
- светло-серые фоны (`#F8FAFC #F1F5F9 #F3F4F6 #FBFBFD #F6F7F9 …`) → `var(--sunken)`
- нейтральные границы (`#E5E7EB #EEF0F2 #F1F3F5 …`) → `var(--line)`; `#CBD5E1 #D1D5DB` → `var(--line-strong)`
- серый текст (`#6B7280 #475467 #64748b #334155 …`) → `var(--muted)`; (`#9aa3b0 #94a3b8 …`) → `var(--faint)`
- старый canvas-фон бумаги `#F4F5F7` в inline → `var(--sunken)`
- **ВСЕ поля ввода**: добавить глобальное правило `input,select,textarea{background:var(--surface);color:var(--ink)}` + `::placeholder{color:var(--faint)}` + `option{background:var(--surface);color:var(--ink)}`. Иначе белый фон + чёрный текст в тёмной.
- светлые градиенты спецблоков (AI `#F5F3FF…`, upsell `#ECFDF5…`) → `var(--ai-50)` / `var(--money-soft)`.

### 6. Статус-тона в тёмной теме (приглушить светлые бейджи)
Пастельные фоны бейджей/полос в тёмной = «белые пятна». Добавить `html.dark` переопределения
(копируй из эталона): `.bdg.reg/.sent.pos/.ctag.sig → #16271F/#34D399`; `.bdg.pri/.temp → #3A1D1D/#F87171`;
`.bdg.ship/.shipbar/.cargo-deal.cur → #2A2114`; `.st.posted → #16271F`; `.st.paid → #1B2740/#7FA8FF`;
`.st.pending → #2A2114/#FBBF24`; AI-панель тексты `#5B21B6/#3b2d63/#6d28d9 → #C4B5FD`; инверсные кнопки
`background:var(--ink)` → в тёмной на `var(--brand)`. Статус-ЦВЕТ (зелёный/красный смысл) сохраняем.

### 7. Кнопки — по дизайн-системе (button.tsx)
primary=accent(синий), secondary=обводка surface, money=зелёный (деньги), **violet=AI** (фиолет
ТОЛЬКО для AI-действий — оставить), danger=красный текст/обводка, call=зелёный (телефония),
hangup=красный. Старый синий-brand уже станет accent через токен. Фиолетовые НЕ-AI кнопки → синие.

### 8. Иконки каналов — бренд-цвета (channels.tsx, DESIGN.md §4.1)
НЕ цветные эмодзи. Звонок `#22C55E`, WhatsApp `#25D366`, Telegram `#229ED9`, Email `#3B82F6`,
ЭДО/Ссылка нейтраль. Кнопка-канал у контакта: квадрат, заливка бренд-цветом, иконка белая
(классы `.cbtn.call/.wa/.tg` как в эталоне). Канальная панель: чип + бренд-иконка слева (`●`/`✈`/`✉`
с inline `color`), фон чипа нейтральный.

## Проверка (ОБЯЗАТЕЛЬНО, иначе задача не COMPLETE)
1. `node .claude/skills/ui-crawl/scripts/handler-audit.mjs <файл>` → `MISSING: none ✓`, `JS OK ✓`.
2. theme+ui аудит (оператор гоняет `_theme_audit.py`/`_ui_crawl.py`): **0 белых пятен в тёмной**,
   контраст по ролям OK, 0 dead-кнопок, 0 ошибок консоли, переключение темы работает.
3. `grep '#2563EB\|#1D4FD7'` по файлу (вне `-old`) = 0.
4. Все блоки оригинала на месте (ничего не выкинуто).

## НЕ делать
НЕ менять JS-логику/id/тексты/структуру. НЕ трогать `-old.html`. НЕ трогать чужие файлы.
НЕ пушить (коммит локальный). НЕ выдумывать цвета — только из эталона/продукта.
