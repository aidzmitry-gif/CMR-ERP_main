// Браузерный аудит экрана. Вставлять как тело функции в Playwright browser_evaluate:
//   browser_evaluate({ function: "() => { <содержимое этого файла без строки IIFE> }" })
// Возвращает: интерактивные элементы без обработчика, битые onclick и визуальные проблемы.
// Запускать на нескольких ширинах (browser_resize → 1440, 768, 390) — переносы/наложения
// часто проявляются только на узком экране.
() => {
  const vw = document.documentElement.clientWidth;
  const txt = el => (el.textContent || '').trim().slice(0, 40);
  const out = {
    viewport: vw,
    onclickBad: [],
    deadClickables: [],
    visual: { pageScrollX: false, beyondViewport: [], clipped: [], overlap: [], tinyText: [] },
  };

  // 1) onclick/oninput/... ссылаются на неопределённые функции
  const RESERVED = new Set(['if','for','while','return','event','this','window','document','toggle','classList','contains','closest','querySelector','getElementById','location','focus']);
  document.querySelectorAll('[onclick],[oninput],[onchange],[onkeydown]').forEach(el => {
    const code = el.getAttribute('onclick') || el.getAttribute('oninput') || el.getAttribute('onchange') || el.getAttribute('onkeydown') || '';
    [...code.matchAll(/([a-zA-Z_$][\w$]*)\s*\(/g)].map(m => m[1]).forEach(n => {
      if (RESERVED.has(n)) return;
      if (typeof window[n] !== 'function') out.onclickBad.push({ fn: n, txt: txt(el) });
    });
  });

  // 2) элементы, выглядящие кликабельными, но без обработчика и без делегирования
  const DELEGATED = ['.seg button', '.dialpad .k', '.tl-filter button', '.iv-terms .seg button', '.ct-field .seg button'];
  const isDelegated = el => DELEGATED.some(sel => el.closest(sel.replace(/\s+\S+$/, '')) && el.matches(sel));
  document.querySelectorAll('button, a, .btn, .add, .x, .chip, [class*="btn"], [class*="cbtn"], [class*="dbtn"], .ch').forEach(el => {
    const hasHandler = el.hasAttribute('onclick') || el.closest('[onclick]');
    const isLink = el.tagName === 'A' && el.getAttribute('href') && el.getAttribute('href') !== '#';
    if (hasHandler || isLink || isDelegated(el)) return;
    if (getComputedStyle(el).cursor === 'pointer') out.deadClickables.push({ tag: el.tagName, cls: (el.className || '').toString().slice(0, 40), txt: txt(el) });
  });
  // дедуп
  const seen = new Set();
  out.deadClickables = out.deadClickables.filter(x => { const k = x.cls + '|' + x.txt; return seen.has(k) ? false : (seen.add(k), true); });

  // 3) визуал
  out.visual.pageScrollX = document.documentElement.scrollWidth > vw + 2;
  const leaves = [];
  document.querySelectorAll('body *').forEach(el => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;

    // вылет за правый край вьюпорта
    if (r.right > vw + 2 && cs.position !== 'fixed' && cs.position !== 'sticky')
      out.visual.beyondViewport.push({ cls: (el.className || '').toString().slice(0, 36), right: Math.round(r.right), txt: txt(el) });

    // обрезанный одностолбцовый текст
    if (!el.children.length && el.textContent.trim() && el.scrollWidth > el.clientWidth + 2 && /hidden|clip/.test(cs.overflowX))
      out.visual.clipped.push({ cls: (el.className || '').toString().slice(0, 36), txt: txt(el) });

    // мелкий шрифт
    const fs = parseFloat(cs.fontSize);
    if (fs && fs < 11 && el.textContent.trim() && !el.children.length)
      out.visual.tinyText.push({ px: fs, txt: txt(el) });

    // листовые текстовые узлы для проверки наложений
    if (!el.children.length && el.textContent.trim()) leaves.push({ el, r });
  });

  // 4) наложения: соседние текстовые листья одного родителя с пересечением > 6px по обеим осям
  const intersect = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) > 6
    && Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)) > 6;
  for (let i = 0; i < leaves.length; i++) {
    const A = leaves[i];
    for (let j = i + 1; j < leaves.length; j++) {
      const B = leaves[j];
      if (A.el.parentElement !== B.el.parentElement) continue;
      if (intersect(A.r, B.r)) out.visual.overlap.push({ a: txt(A.el), b: txt(B.el) });
    }
  }

  // ограничить объём
  for (const k of ['beyondViewport', 'clipped', 'tinyText', 'overlap']) out.visual[k] = out.visual[k].slice(0, 12);
  out.summary = {
    onclickBad: out.onclickBad.length, deadClickables: out.deadClickables.length,
    pageScrollX: out.visual.pageScrollX, beyondViewport: out.visual.beyondViewport.length,
    clipped: out.visual.clipped.length, overlap: out.visual.overlap.length, tinyText: out.visual.tinyText.length,
  };
  return out;
}
