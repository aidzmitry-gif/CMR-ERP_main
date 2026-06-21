/* ════════════════════════════════════════════════════════════════════════
   sales-cur.js — общий слой «юр-лицо + валюта» для всех CRM-экранов.
   Подключение: <script src="sales-cur.js"></script> (одной строкой, в конце body).

   Что делает:
   • показывает селектор юр-лица (флаг · название · базовая валюта), фикс. сверху по центру;
   • выбранное ЮЛ запоминается в localStorage и держится при переходе между экранами;
   • КОНВЕРТИРУЕТ все денежные суммы «NNN Br» на странице в валюту выбранного ЮЛ
     по курсу НБ РБ (демо-курсы ниже) — включая суммы, отрисованные скриптами экрана
     (через MutationObserver: пере-применяется после любой перерисовки DOM).

   Модель: базовая валюта данных макетов — BYN (Br). Конвертация в валюту ЮЛ — на отображении.
   В бэкенде курс берётся из api.nbrb.by на дату операции; здесь демо-таблица.
   Доска (sales-board-mockup.html) имеет собственный встроенный движок и этот файл НЕ
   подключает — но читает/пишет тот же ключ localStorage, поэтому выбор ЮЛ общий. */
(function () {
  "use strict";
  if (window.SalesCur) return; // защита от двойного подключения

  var COMPANIES = [
    { id: "by", name: "ООО «АкуМир»",      country: "Беларусь", flag: "🇧🇾", base: "BYN" },
    { id: "ru", name: "ООО «АкуМир-РУС»",  country: "Россия",   flag: "🇷🇺", base: "RUB" },
    { id: "pl", name: "AkuMir Sp. z o.o.", country: "Польша",   flag: "🇵🇱", base: "EUR" },
  ];
  // Курс к BYN (демо НБ РБ): сколько BYN за 1 единицу валюты.
  var FX = { BYN: 1, USD: 3.25, EUR: 3.55, RUB: 0.037, PLN: 0.82 };
  var SIGN = { BYN: "Br", USD: "$", EUR: "€", RUB: "₽", PLN: "zł" };
  var KEY = "salesCompany";

  var cur = localStorage.getItem(KEY) || "by";
  function co(id) { return COMPANIES.find(function (c) { return c.id === id; }); }
  function base() { return co(cur).base; }
  function sign() { return SIGN[base()] || base(); }
  function convert(byn) { return byn / (FX[base()] || 1); } // BYN → валюта ЮЛ

  // Точные суммы (без «млн»): на карточках/счетах/реестрах важна точность, а рублёвые
  // суммы регулярно > 1 млн — округление до «млн» съело бы значащие цифры.
  function money(byn) { return Math.round(convert(byn)).toLocaleString("ru-RU") + " " + sign(); }

  // ── денежный токен «NNN Br» (учитываем nbsp/узкие пробелы из toLocaleString) ──
  var SP = "[\\u0020\\u00a0\\u202f\\u2009]";
  var AMT = "\\d(?:" + SP + "?\\d)*\\s*Br\\b";          // сумма: 46 800 Br
  var AMT_RE = new RegExp(AMT, "g");
  var TOKEN_RE = new RegExp("(" + AMT + ")|(\\bBr\\b)", "g"); // сумма | одиночное слово-валюта (в подписях)

  var observer = null;

  // Обернуть денежные токены: суммы → <span.sc-money data-byn>, слово-валюту в подписях → <span.sc-cur>.
  function wrapTextNode(node) {
    var txt = node.nodeValue;
    TOKEN_RE.lastIndex = 0;
    if (!TOKEN_RE.test(txt)) return;
    TOKEN_RE.lastIndex = 0;
    var frag = document.createDocumentFragment();
    var last = 0, m;
    while ((m = TOKEN_RE.exec(txt))) {
      if (m.index > last) frag.appendChild(document.createTextNode(txt.slice(last, m.index)));
      var span = document.createElement("span");
      if (m[1] != null) { // сумма
        var byn = parseInt(m[1].replace(/[^\d]/g, ""), 10) || 0;
        span.className = "sc-money";
        span.dataset.byn = byn;
        span.textContent = money(byn);
      } else { // одиночное «Br» — подпись/единица измерения
        span.className = "sc-cur";
        span.textContent = sign();
      }
      frag.appendChild(span);
      last = m.index + m[0].length;
    }
    if (last < txt.length) frag.appendChild(document.createTextNode(txt.slice(last)));
    node.parentNode.replaceChild(frag, node);
  }

  var SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, NOSCRIPT: 1 };
  function walk(root) {
    var tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        var p = n.parentNode;
        if (!p || SKIP[p.nodeName]) return NodeFilter.FILTER_REJECT;
        if (p.classList && (p.classList.contains("sc-money") || p.classList.contains("sc-cur")))
          return NodeFilter.FILTER_REJECT;
        if (p.closest && p.closest("#sc-pick")) return NodeFilter.FILTER_REJECT; // не трогать сам селектор
        TOKEN_RE.lastIndex = 0;
        return TOKEN_RE.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    var nodes = [], n;
    while ((n = tw.nextNode())) nodes.push(n);
    nodes.forEach(wrapTextNode);
  }

  // input value="NNN Br" — храним оригинал в data-byn, подставляем в валюте ЮЛ
  function handleInputs() {
    document.querySelectorAll("input").forEach(function (inp) {
      var v = inp.dataset.byn != null ? null : inp.value;
      if (v != null) {
        AMT_RE.lastIndex = 0;
        if (!AMT_RE.test(v)) return;
        inp.dataset.byn = parseInt(v.replace(/[^\d]/g, ""), 10) || 0;
      }
      if (inp.dataset.byn != null) inp.value = money(parseInt(inp.dataset.byn, 10) || 0);
    });
  }

  function apply() {
    if (observer) observer.disconnect();
    // 1) уже обёрнутые суммы и подписи-валюты — пересчитать/переименовать в текущую валюту
    document.querySelectorAll(".sc-money").forEach(function (s) {
      s.textContent = money(parseInt(s.dataset.byn, 10) || 0);
    });
    document.querySelectorAll(".sc-cur").forEach(function (s) { s.textContent = sign(); });
    // 2) новые сырые токены — оборачивать только если валюта НЕ BYN (BY оставляем как есть)
    if (base() !== "BYN") walk(document.body);
    handleInputs();
    if (observer) observer.observe(document.body, { subtree: true, childList: true, characterData: true });
  }

  // ── селектор юр-лица (фикс. сверху по центру) ──
  function injectSelector() {
    if (document.getElementById("sc-pick")) return;
    var css = document.createElement("style");
    css.textContent =
      "#sc-pick{position:fixed;top:8px;left:50%;transform:translateX(-50%);z-index:99998;font:600 12.5px -apple-system,'Segoe UI',sans-serif}" +
      "#sc-btn{display:inline-flex;align-items:center;gap:7px;background:rgba(255,255,255,.96);color:#0f172a;border:1px solid rgba(15,23,42,.14);border-radius:9px;padding:6px 11px;cursor:pointer;box-shadow:0 6px 18px rgba(16,24,40,.16)}" +
      "html.dark #sc-btn,.dark #sc-btn{background:rgba(20,26,40,.96);color:#e6edf6;border-color:rgba(255,255,255,.16)}" +
      "#sc-btn .b{font-weight:600;color:#64748b;font-size:11px;border:1px solid rgba(100,116,139,.4);border-radius:5px;padding:1px 5px}" +
      "#sc-menu{position:absolute;top:calc(100% + 6px);left:50%;transform:translateX(-50%);min-width:260px;background:#fff;color:#0f172a;border:1px solid rgba(15,23,42,.14);border-radius:11px;box-shadow:0 16px 44px rgba(16,24,40,.22);padding:6px;display:none}" +
      "html.dark #sc-menu,.dark #sc-menu{background:#141a28;color:#e6edf6;border-color:rgba(255,255,255,.16)}" +
      "#sc-menu.show{display:block}" +
      ".sc-opt{display:flex;align-items:center;gap:9px;padding:8px 9px;border-radius:8px;cursor:pointer}" +
      ".sc-opt:hover{background:rgba(100,116,139,.12)}" +
      ".sc-opt .nm{font-weight:600;font-size:13px}.sc-opt .sb{font-size:11px;color:#64748b}" +
      ".sc-opt .bs{margin-left:auto;font-size:11px;font-weight:600;color:#64748b;border:1px solid rgba(100,116,139,.4);border-radius:5px;padding:1px 6px}" +
      ".sc-opt .ck{color:#1E5EFF;font-weight:700;width:13px}" +
      ".sc-foot{font-size:10.5px;color:#64748b;padding:7px 9px 3px;line-height:1.4}";
    document.head.appendChild(css);

    var wrap = document.createElement("div");
    wrap.id = "sc-pick";
    wrap.innerHTML =
      '<button id="sc-btn" title="Юридическое лицо · валюта учёта"><span class="fl"></span>' +
      '<span class="nm"></span><span class="b"></span><span style="color:#94a3b8;font-size:10px">▾</span></button>' +
      '<div id="sc-menu"></div>';
    document.body.appendChild(wrap);

    document.getElementById("sc-btn").onclick = function (e) {
      e.stopPropagation();
      document.getElementById("sc-menu").classList.toggle("show");
    };
    document.addEventListener("click", function (e) {
      if (!e.target.closest("#sc-pick")) document.getElementById("sc-menu").classList.remove("show");
    });
    renderSelector();
  }

  function renderSelector() {
    var c = co(cur);
    var btn = document.getElementById("sc-btn");
    if (!btn) return;
    btn.querySelector(".fl").textContent = c.flag;
    btn.querySelector(".nm").textContent = c.name;
    btn.querySelector(".b").textContent = c.base;
    document.getElementById("sc-menu").innerHTML =
      COMPANIES.map(function (x) {
        return (
          '<div class="sc-opt" onclick="SalesCur.pick(\'' + x.id + "')\">" +
          '<span class="ck">' + (x.id === cur ? "✓" : "") + "</span>" +
          '<span style="font-size:15px">' + x.flag + "</span>" +
          '<span><div class="nm">' + x.name + '</div><div class="sb">' + x.country + "</div></span>" +
          '<span class="bs">' + x.base + "</span></div>"
        );
      }).join("") +
      '<div class="sc-foot">Раздельный учёт по юр-лицам. Суммы — в валюте выбранного ЮЛ по курсу НБ РБ.</div>';
  }

  function pick(id) {
    if (!co(id)) return;
    cur = id;
    localStorage.setItem(KEY, id);
    document.getElementById("sc-menu").classList.remove("show");
    renderSelector();
    apply();
  }

  // дебаунс пере-применения при перерисовках экрана
  var t = null;
  function schedule() {
    if (t) return;
    t = setTimeout(function () { t = null; apply(); }, 60);
  }

  function init() {
    injectSelector();
    observer = new MutationObserver(schedule);
    apply();
    window.addEventListener("load", apply);
  }

  window.SalesCur = { pick: pick, money: money, convert: convert, base: base, sign: sign, COMPANIES: COMPANIES, FX: FX };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
