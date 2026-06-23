"use client";

import {
  ArrowRight,
  Boxes,
  Check,
  Info,
  Minus,
  PackageCheck,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  Star,
  Truck,
  Wallet,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { formatByn, plural } from "@/lib/format";

// ──────────────────────────────────────────────────────────────────────────
// demo-данные (бэкенда по экрану пока нет). Каталог: остатки по складам,
// «в пути», прошлая → текущая цена; tags — параметры для ИИ-подбора.
// Валюта продукта — BYN.
// ──────────────────────────────────────────────────────────────────────────

type Warehouse = { n: string; on: number; res: number; inc?: number; eta?: string };

type Product = {
  sku: string;
  grp: string;
  art: string;
  bar: string;
  priceNow: number;
  priceWas: number;
  tags: string[];
  wh: Warehouse[];
};

const CATALOG: Product[] = [
  {
    sku: "АКБ 6СТ-190 (Зубр)",
    grp: "Аккумуляторы / Грузовые",
    art: "AKB-6ST-190",
    bar: "4811234567894",
    priceNow: 1100,
    priceWas: 980,
    tags: ["грузовой", "фура", "тягач", "man", "volvo", "scania", "камаз", "12в", "190ач", "пуск 1250a"],
    wh: [
      { n: "Минск (центр.)", on: 54, res: 13, inc: 40, eta: "18.06" },
      { n: "Гомель", on: 20, res: 0 },
      { n: "Брест", on: 8, res: 5, inc: 12, eta: "25.06" },
    ],
  },
  {
    sku: "АКБ 6СТ-225 (промышленный)",
    grp: "Аккумуляторы / Грузовые",
    art: "AKB-6ST-225",
    bar: "4811234567900",
    priceNow: 2600,
    priceWas: 2600,
    tags: ["грузовой", "спецтехника", "автобус", "экскаватор", "12в", "225ач", "высокий пуск", "мороз"],
    wh: [{ n: "Минск (центр.)", on: 18, res: 0, inc: 30, eta: "22.06" }],
  },
  {
    sku: "АКБ 6СТ-77 (легковой)",
    grp: "Аккумуляторы / Легковые",
    art: "AKB-6ST-77",
    bar: "4811234567801",
    priceNow: 260,
    priceWas: 285,
    tags: ["легковой", "авто", "седан", "кроссовер", "12в", "77ач", "бюджет"],
    wh: [
      { n: "Минск (центр.)", on: 120, res: 10 },
      { n: "Гомель", on: 60, res: 0 },
    ],
  },
  {
    sku: "АКБ тяговая 6ЭМ-145",
    grp: "Аккумуляторы / Тяговые",
    art: "AKB-6EM-145",
    bar: "4811234567955",
    priceNow: 3900,
    priceWas: 3600,
    tags: ["погрузчик", "штабелёр", "склад", "тяговый", "ричтрак", "145ач", "циклический"],
    wh: [{ n: "Минск (центр.)", on: 3, res: 2, inc: 6, eta: "01.07" }],
  },
  {
    sku: "Зарядное устройство ЗУ-15А",
    grp: "Зарядные устройства",
    art: "ZU-15A",
    bar: "4811234568013",
    priceNow: 420,
    priceWas: 420,
    tags: ["зарядка", "зу", "обслуживание", "сопутствующий", "до 200ач"],
    wh: [
      { n: "Минск (центр.)", on: 30, res: 0 },
      { n: "Гомель", on: 12, res: 2 },
    ],
  },
  {
    sku: "Зарядное устройство ЗУ-30А PRO",
    grp: "Зарядные устройства",
    art: "ZU-30A-PRO",
    bar: "4811234568020",
    priceNow: 980,
    priceWas: 1050,
    tags: ["зарядка", "зу", "профи", "автопарк", "быстрая", "сопутствующий"],
    wh: [{ n: "Минск (центр.)", on: 7, res: 0 }],
  },
  {
    sku: "Тестер АКБ цифровой",
    grp: "Оборудование",
    art: "TST-DIG",
    bar: "4811234568105",
    priceNow: 180,
    priceWas: 180,
    tags: ["тестер", "диагностика", "обслуживание", "сопутствующий"],
    wh: [{ n: "Минск (центр.)", on: 45, res: 0 }],
  },
  {
    sku: "Доставка по РБ",
    grp: "Услуги",
    art: "SRV-DELIV",
    bar: "—",
    priceNow: 5000,
    priceWas: 5000,
    tags: ["доставка", "логистика", "услуга"],
    wh: [],
  },
];

// ── ИИ-скрипт вопросов; pull — что «подтянуть из транскрибации разговора» (демо)
type ScriptStep = {
  id: "item" | "vehicle" | "need" | "budget" | "urgency";
  q: string;
  type: "text" | "select";
  ph?: string;
  opts?: string[];
  pull: string;
};

const AI_SCRIPT: ScriptStep[] = [
  { id: "item", q: "Товар (наименование)", type: "text", ph: "АКБ 6СТ, ЗУ, тестер…", pull: "АКБ 6СТ-190" },
  { id: "vehicle", q: "Тип техники / модель", type: "text", ph: "фура MAN, погрузчик, легковой…", pull: "фура MAN TGX" },
  {
    id: "need",
    q: "Что нужно",
    type: "select",
    opts: ["", "Аккумулятор", "Зарядное устройство", "Диагностика", "Комплект"],
    pull: "Аккумулятор",
  },
  { id: "budget", q: "Бюджет, BYN (до)", type: "text", ph: "напр. 1500", pull: "1500" },
  {
    id: "urgency",
    q: "Срочность",
    type: "select",
    opts: ["", "Срочно (со склада)", "Можно подождать приход", "Не срочно"],
    pull: "Срочно (со склада)",
  },
];

type AiAnswers = Partial<Record<ScriptStep["id"], string>>;

// ── helpers по складу
function whFree(p: Product): number {
  return p.wh.reduce((a, w) => a + (w.on - w.res), 0);
}
function whInc(p: Product): number {
  return p.wh.reduce((a, w) => a + (w.inc ?? 0), 0);
}
function isService(p: Product): boolean {
  return p.wh.length === 0;
}

// совпадение по наименованию: имя/артикул/теги (АКБ 6СТ → все 6СТ; ЗУ → зарядные)
function matchItem(p: Product, item: string): boolean {
  const hay = (p.sku + " " + p.art + " " + p.tags.join(" ")).toLowerCase();
  return item.split(/\s+/).every((w) => w.length < 2 || hay.includes(w));
}

// ── ИИ-сигнал и скоринг
type Signal = { text: string; budget: number; urgent: boolean; words: string[] };
type Scored = { p: Product; s: number; hits: string[] };

function buildSignal(ans: AiAnswers, free: string): Signal {
  const low = free.toLowerCase();
  const parts = [ans.item, ans.vehicle, ans.need, low].filter(Boolean).join(" ").toLowerCase();
  const freeBudget = low.match(/до\s*(\d+)/);
  const budget = parseInt((ans.budget ?? "").replace(/\D/g, ""), 10) || (freeBudget ? +freeBudget[1] : 0);
  const urgent = (ans.urgency ?? "").includes("Срочно") || /срочно/.test(low);
  return { text: parts, budget, urgent, words: parts.split(/[\s,;/]+/).filter((w) => w.length > 2) };
}

function scoreProduct(p: Product, sig: Signal): Scored {
  let s = 0;
  const hits: string[] = [];
  sig.words.forEach((w) => {
    if (p.tags.some((t) => t.includes(w) || w.includes(t))) {
      s += 2;
      hits.push(w);
    } else if ((p.sku + " " + p.grp).toLowerCase().includes(w)) {
      s += 1;
    }
  });
  if (sig.budget && p.priceNow <= sig.budget) s += 1;
  if (sig.urgent && whFree(p) > 0) s += 1;
  return { p, s, hits };
}

function whyText(x: Scored, sig: Signal): string {
  const p = x.p;
  const bits: string[] = [];
  if (x.hits.length) bits.push("подходит по: " + [...new Set(x.hits)].slice(0, 3).join(", "));
  if (sig.budget && p.priceNow <= sig.budget) bits.push("в бюджет");
  if (sig.urgent && whFree(p) > 0) bits.push("есть на складе сейчас");
  if (whInc(p)) bits.push("+приход " + whInc(p));
  return bits.join(" · ") || "близко к запросу";
}

const STATUS_BADGE = "rounded-full px-2 py-0.5 text-[11px] font-semibold";

export function CatalogPicker() {
  // фильтры каталога
  const [query, setQuery] = useState("");
  const [grp, setGrp] = useState("");
  const [whFilter, setWhFilter] = useState("");
  const [inStockOnly, setInStockOnly] = useState(false);

  // корзина (что уйдёт в счёт): sku -> qty
  const [cart, setCart] = useState<Record<string, number>>({});

  // ИИ-подбор
  const [aiAns, setAiAns] = useState<AiAnswers>({});
  const [aiFree, setAiFree] = useState("");
  const [aiRanked, setAiRanked] = useState<Scored[] | null>(null);
  const [aiNote, setAiNote] = useState<{ kind: "clarify" | "reco"; sig: Signal } | null>(null);

  const groups = useMemo(() => [...new Set(CATALOG.map((p) => p.grp))].sort(), []);
  const item = (aiAns.item ?? "").toLowerCase().trim();

  // фильтрация каталога (поиск / группа / склад / в наличии / ИИ-наименование)
  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    return CATALOG.filter(
      (p) =>
        (!grp || p.grp === grp) &&
        (!whFilter || p.wh.some((w) => w.n === whFilter)) &&
        (!inStockOnly || isService(p) || whFree(p) > 0) &&
        (!q || (p.sku + " " + p.art + " " + p.bar).toLowerCase().includes(q)) &&
        (!item || matchItem(p, item)),
    );
  }, [query, grp, whFilter, inStockOnly, item]);

  // если задано наименование — плоский список с сортировкой по ATP (свободно ↓), сервис в конец
  const groupedList = useMemo(() => {
    if (item) {
      const atp = (p: Product) => (isService(p) ? -Infinity : whFree(p));
      const sorted = [...filtered].sort((a, b) => atp(b) - atp(a));
      return [{ title: `Подбор по «${aiAns.item}» · сортировка по наличию (ATP)`, items: sorted }];
    }
    const map = new Map<string, Product[]>();
    filtered.forEach((p) => {
      const arr = map.get(p.grp) ?? [];
      arr.push(p);
      map.set(p.grp, arr);
    });
    return [...map.keys()].sort().map((title) => ({ title, items: map.get(title)! }));
  }, [filtered, item, aiAns.item]);

  // позиции корзины
  const cartItems = useMemo(
    () =>
      Object.keys(cart)
        .map((sku) => ({ p: CATALOG.find((x) => x.sku === sku)!, qty: cart[sku] }))
        .filter((x) => x.p),
    [cart],
  );
  const subtotal = cartItems.reduce((a, { p, qty }) => a + qty * p.priceNow, 0);
  const vat = (subtotal * 20) / 120;

  // ── скорборд (метрики экрана)
  const skuCount = CATALOG.length;
  const inStockCount = CATALOG.filter((p) => !isService(p) && whFree(p) > 0).length;
  const incomingTotal = CATALOG.reduce((a, p) => a + whInc(p), 0);

  // ── действия корзины
  function adj(sku: string, delta: number) {
    setCart((c) => {
      const next = Math.max(0, (c[sku] ?? 0) + delta);
      const out = { ...c };
      if (next <= 0) delete out[sku];
      else out[sku] = next;
      return out;
    });
  }
  function setQty(sku: string, value: string) {
    const n = parseInt(value, 10) || 0;
    setCart((c) => {
      const out = { ...c };
      if (n <= 0) delete out[sku];
      else out[sku] = n;
      return out;
    });
  }
  function removeItem(sku: string) {
    setCart((c) => {
      const out = { ...c };
      delete out[sku];
      return out;
    });
  }

  // ── ИИ-подбор
  function aiSetAnswer(id: ScriptStep["id"], value: string) {
    setAiAns((a) => ({ ...a, [id]: value }));
  }
  function aiPull(id: ScriptStep["id"]) {
    const step = AI_SCRIPT.find((s) => s.id === id);
    if (step) aiSetAnswer(id, step.pull);
  }
  function aiReset() {
    setAiAns({});
    setAiFree("");
    setAiRanked(null);
    setAiNote(null);
  }
  function aiRun() {
    const sig = buildSignal(aiAns, aiFree);
    if (!sig.text.trim()) {
      setAiRanked([]);
      setAiNote({ kind: "clarify", sig });
      return;
    }
    const ranked = CATALOG.map((p) => scoreProduct(p, sig))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s);
    const topScore = ranked.length ? ranked[0].s : 0;
    const needsClarify =
      topScore < 2 || (!aiAns.vehicle && !/фур|погруз|легк|груз|авто|спец|склад/.test(sig.text));
    setAiRanked(ranked.slice(0, 4));
    setAiNote({ kind: needsClarify ? "clarify" : "reco", sig });
  }
  function aiAdd(sku: string) {
    adj(sku, 1);
  }

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-[1220px] space-y-4">
        {/* Заголовок */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-bold text-ink">
              <Boxes size={20} className="text-accent" /> Каталог-подбор
            </h1>
            <p className="mt-1 max-w-[680px] text-sm text-muted">
              Большой каталог: остатки по складам, «в пути», прошлая → текущая цена. Отмеченные позиции справа уйдут
              в счёт. Карточка товара — в модуле «Справочники».
            </p>
            <p className="mt-1 text-[11px] text-faint">
              Позиции уйдут в счёт CRM-1029 · ОАО «Белтранс»
            </p>
          </div>
        </div>

        {/* Скорборд — метрики экрана */}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Metric tone="blue" icon={<Boxes size={16} />} label="Позиций в каталоге" value={String(skuCount)} />
          <Metric
            tone="emerald"
            icon={<PackageCheck size={16} />}
            label="В наличии (своб. > 0)"
            value={String(inStockCount)}
          />
          <Metric tone="violet" icon={<Truck size={16} />} label="В пути, шт" value={String(incomingTotal)} />
          <Metric
            tone="money"
            icon={<Wallet size={16} />}
            label="В счёте сейчас"
            value={formatByn(subtotal)}
          />
        </div>

        {/* Основная сетка: каталог + корзина */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_380px]">
          {/* ЛЕВО — каталог */}
          <div className="space-y-4">
            {/* ИИ-подбор */}
            <section className="rounded-2xl border-l-4 border-violet-400 bg-surface p-4 shadow-card">
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex items-center gap-1.5 text-sm font-bold text-violet-600">
                  <Sparkles size={16} /> ИИ-подбор товара
                </span>
                <span className="text-[11px] text-muted">
                  скрипт вопросов · ответы вручную или из разговора · свободный запрос
                </span>
                <button
                  onClick={aiReset}
                  title="Сбросить"
                  className="ml-auto flex h-7 w-7 items-center justify-center rounded-lg border border-line text-violet-600 hover:bg-sunken"
                >
                  <RotateCcw size={14} />
                </button>
              </div>

              {/* скрипт вопросов */}
              <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                {AI_SCRIPT.map((s) => {
                  const v = aiAns[s.id] ?? "";
                  return (
                    <div key={s.id} className="rounded-xl bg-sunken p-2.5">
                      <div className="mb-1.5 flex items-center justify-between gap-2">
                        <span className="text-[11px] font-bold text-violet-600">{s.q}</span>
                        <button
                          onClick={() => aiPull(s.id)}
                          title="Подтянуть из транскрибации разговора"
                          className={`${STATUS_BADGE} bg-blue-50 text-blue-600`}
                        >
                          ↓ из разговора
                        </button>
                      </div>
                      {s.type === "select" ? (
                        <select
                          value={v}
                          onChange={(e) => aiSetAnswer(s.id, e.target.value)}
                          className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-[13px] text-ink focus:border-accent focus:outline-none"
                        >
                          {(s.opts ?? []).map((o) => (
                            <option key={o} value={o}>
                              {o || "— не выбрано —"}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          value={v}
                          placeholder={s.ph}
                          onChange={(e) => aiSetAnswer(s.id, e.target.value)}
                          className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-[13px] text-ink placeholder:text-faint focus:border-accent focus:outline-none"
                        />
                      )}
                    </div>
                  );
                })}
              </div>

              {/* свободный запрос */}
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <input
                  value={aiFree}
                  placeholder="Свободный запрос ИИ: «нужен АКБ на фуру MAN, бюджет до 1500, срочно»"
                  onChange={(e) => setAiFree(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") aiRun();
                  }}
                  className="flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-faint focus:border-accent focus:outline-none"
                />
                <button
                  onClick={aiRun}
                  className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-violet-500 px-4 py-2 text-[13px] font-bold text-white hover:bg-violet-600"
                >
                  <Sparkles size={15} /> Подобрать
                </button>
              </div>

              {/* вывод ИИ */}
              {aiNote && (
                <div className="mt-3 space-y-2.5">
                  {aiNote.kind === "clarify" && aiRanked && aiRanked.length === 0 && (
                    <ClarifyBox text="Опишите задачу: тип техники и что нужно — или впишите свободный запрос. Можно подтянуть ответы из разговора (↓)." />
                  )}
                  {aiNote.kind === "clarify" && aiRanked && aiRanked.length > 0 && (
                    <ClarifyBox text="Уточните: для какой техники подбираем — грузовой/тягач, легковой, погрузчик (склад) или спецтехника? Это сильно сужает подбор. Пока показываю ближайшее ниже." />
                  )}
                  {aiRanked && aiRanked.length > 0 && (
                    <div className="rounded-xl border border-line bg-sunken p-3">
                      <div className="mb-1.5 text-[12px] font-bold text-violet-600">
                        Рекомендую под задачу «{aiNote.sig.text.trim()}»
                        {aiNote.sig.budget ? ` · бюджет до ${formatByn(aiNote.sig.budget)}` : ""}
                        {aiNote.sig.urgent ? " · только со склада приоритетно" : ""}:
                      </div>
                      <div className="divide-y divide-line">
                        {aiRanked.map((x, i) => {
                          const p = x.p;
                          const inCart = (cart[p.sku] ?? 0) > 0;
                          return (
                            <div key={p.sku} className="flex items-center gap-2.5 py-2">
                              <span
                                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-[13px] font-bold ${
                                  i === 0 ? "bg-emerald-50 text-emerald-600" : "bg-violet-50 text-violet-600"
                                }`}
                              >
                                {i === 0 ? <Star size={14} /> : `${Math.min(99, x.s * 20)}%`}
                              </span>
                              <div className="min-w-0 flex-1">
                                <div className="truncate text-[13px] font-bold text-ink">
                                  {p.sku} · {formatByn(p.priceNow)}
                                  {isService(p) ? "" : ` · своб. ${whFree(p)}`}
                                </div>
                                <div className="truncate text-[11px] text-muted">{whyText(x, aiNote.sig)}</div>
                              </div>
                              <button
                                onClick={() => aiAdd(p.sku)}
                                className={`inline-flex shrink-0 items-center gap-1 rounded-lg px-3 py-1.5 text-[12px] font-bold ${
                                  inCart
                                    ? "border border-emerald-200 bg-emerald-50 text-emerald-600"
                                    : "bg-accent text-accent-ink"
                                }`}
                              >
                                {inCart ? <Check size={13} /> : <Plus size={13} />}
                                {inCart ? "в счёте" : "в счёт"}
                              </button>
                            </div>
                          );
                        })}
                      </div>
                      <div className="mt-2 text-[11px] text-faint">
                        Подбор по параметрам техники и наличию. Решение — за менеджером; уточните бюджет/совместимость
                        при сомнении.
                      </div>
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* Фильтры */}
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-[200px] flex-1">
                <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
                <input
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="поиск: название / артикул / штрихкод"
                  className="w-full rounded-xl border border-line bg-surface py-2 pl-9 pr-3 text-[13px] text-ink placeholder:text-faint focus:border-accent focus:outline-none"
                />
              </div>
              <select
                value={grp}
                onChange={(e) => setGrp(e.target.value)}
                className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-muted focus:border-accent focus:outline-none"
              >
                <option value="">Все группы</option>
                {groups.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
              <select
                value={whFilter}
                onChange={(e) => setWhFilter(e.target.value)}
                className="rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-muted focus:border-accent focus:outline-none"
              >
                <option value="">Все склады</option>
                <option>Минск (центр.)</option>
                <option>Гомель</option>
                <option>Брест</option>
              </select>
              <label className="flex items-center gap-1.5 text-[13px] text-muted">
                <input
                  type="checkbox"
                  checked={inStockOnly}
                  onChange={(e) => setInStockOnly(e.target.checked)}
                  className="accent-accent"
                />
                только в наличии
              </label>
            </div>

            {/* Чипы-фасеты групп */}
            <div className="flex flex-wrap gap-2">
              <Chip active={!grp} onClick={() => setGrp("")} label="Все" count={CATALOG.length} />
              {groups.map((g) => (
                <Chip
                  key={g}
                  active={grp === g}
                  onClick={() => setGrp(g)}
                  label={g}
                  count={CATALOG.filter((p) => p.grp === g).length}
                />
              ))}
            </div>

            {/* Список каталога */}
            <div className="space-y-4">
              {filtered.length === 0 ? (
                <div className="rounded-2xl border border-line bg-surface p-10 text-center text-sm text-faint shadow-card">
                  Ничего не найдено{item ? ` по «${aiAns.item}»` : ""}
                </div>
              ) : (
                groupedList.map((group) => (
                  <div key={group.title} className="space-y-2.5">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">{group.title}</div>
                    {group.items.map((p) => (
                      <ProductCard
                        key={p.sku}
                        p={p}
                        qty={cart[p.sku] ?? 0}
                        onAdd={() => adj(p.sku, 1)}
                        onInc={() => adj(p.sku, 1)}
                        onDec={() => adj(p.sku, -1)}
                        onSetQty={(v) => setQty(p.sku, v)}
                      />
                    ))}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* ПРАВО — корзина (что уйдёт в счёт) */}
          <aside className="lg:sticky lg:top-4 lg:self-start">
            <div className="flex max-h-[calc(100vh-2rem)] flex-col overflow-hidden rounded-2xl bg-surface shadow-card">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <span className="text-[15px] font-bold text-ink">В счёт</span>
                <span className={`${STATUS_BADGE} bg-sunken text-muted`}>
                  {cartItems.length} {plural(cartItems.length, ["позиция", "позиции", "позиций"])}
                </span>
              </div>

              <div className="flex-1 overflow-auto px-4 py-2">
                {cartItems.length === 0 ? (
                  <div className="px-2 py-10 text-center text-sm text-faint">
                    Пусто. Добавьте товары из каталога слева — они уйдут в счёт.
                  </div>
                ) : (
                  cartItems.map(({ p, qty }) => {
                    const sum = qty * p.priceNow;
                    let byInc = 0;
                    let buy = 0;
                    if (!isService(p)) {
                      const def = qty - whFree(p);
                      if (def > 0) {
                        byInc = Math.min(def, whInc(p));
                        buy = def - byInc;
                      }
                    }
                    return (
                      <div key={p.sku} className="border-b border-line py-2.5 last:border-0">
                        <div className="flex items-start justify-between gap-2">
                          <span className="text-[13px] font-semibold text-ink">{p.sku}</span>
                          <button
                            onClick={() => removeItem(p.sku)}
                            title="Убрать"
                            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-faint hover:text-red-600"
                          >
                            <X size={14} />
                          </button>
                        </div>
                        <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted">
                          <span>
                            {qty} × {formatByn(p.priceNow)}
                          </span>
                          <span className="font-bold text-ink">{formatByn(sum)}</span>
                        </div>
                        {byInc > 0 && (
                          <div className="mt-1 text-[11px] text-blue-600">
                            <Truck size={11} className="-mt-0.5 mr-1 inline" />
                            {byInc} шт закроется приходом
                          </div>
                        )}
                        {buy > 0 && (
                          <div className="mt-1 text-[11px] text-amber-600">⚠ {buy} шт под заказ → закупка</div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>

              {cartItems.length > 0 && (
                <div className="border-t border-line px-4 py-3.5">
                  <div className="flex justify-between py-0.5 text-[13px] text-muted">
                    <span>Позиций</span>
                    <span>{cartItems.length}</span>
                  </div>
                  <div className="flex justify-between py-0.5 text-[13px] text-muted">
                    <span>в т.ч. НДС 20%</span>
                    <span>{formatByn(vat)}</span>
                  </div>
                  <div className="mt-1.5 flex justify-between border-t border-line pt-2 text-[17px] font-bold text-ink">
                    <span>Итого</span>
                    <span className="text-money">{formatByn(subtotal)}</span>
                  </div>
                  <button
                    onClick={() => undefined}
                    className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-accent px-4 py-3 text-sm font-bold text-accent-ink hover:bg-accent-soft"
                  >
                    Перенести в счёт <ArrowRight size={16} />
                  </button>
                </div>
              )}
            </div>
          </aside>
        </div>
      </div>
    </main>
  );
}

// ── метрика-тайл скорборда
const METRIC_TONE: Record<string, string> = {
  blue: "bg-blue-50 text-blue-600",
  emerald: "bg-emerald-50 text-emerald-600",
  violet: "bg-violet-50 text-violet-600",
  money: "bg-money-soft text-money",
};

function Metric({
  tone,
  icon,
  label,
  value,
}: {
  tone: keyof typeof METRIC_TONE;
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl bg-surface p-4 shadow-card">
      <div className="flex items-center gap-2">
        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${METRIC_TONE[tone]}`}>
          {icon}
        </span>
        <span className="text-[11px] uppercase tracking-wide text-faint">{label}</span>
      </div>
      <div className="mt-2 text-lg font-bold tabular-nums text-ink">{value}</div>
    </div>
  );
}

// ── чип-фасет группы
function Chip({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12px] font-semibold ${
        active
          ? "border-accent bg-accent text-accent-ink"
          : "border-line bg-surface text-muted hover:text-accent"
      }`}
    >
      {label}
      <span className={`tabular-nums ${active ? "opacity-80" : "text-faint"}`}>{count}</span>
    </button>
  );
}

// ── подсказка ИИ (уточнение)
function ClarifyBox({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2.5 text-[12px] text-amber-600">
      <Info size={15} className="mt-0.5 shrink-0" />
      <span>{text}</span>
    </div>
  );
}

// ── карточка товара
function ProductCard({
  p,
  qty,
  onAdd,
  onInc,
  onDec,
  onSetQty,
}: {
  p: Product;
  qty: number;
  onAdd: () => void;
  onInc: () => void;
  onDec: () => void;
  onSetQty: (value: string) => void;
}) {
  const inCart = qty > 0;
  const free = whFree(p);
  const low = free <= 5;
  const inc = whInc(p);
  const priceUp = p.priceNow > p.priceWas;
  const priceChanged = p.priceNow !== p.priceWas;
  const delta = priceChanged ? Math.abs(((p.priceNow - p.priceWas) / p.priceWas) * 100) : 0;

  return (
    <div
      className={`grid grid-cols-[1fr_auto] items-center gap-3 rounded-2xl bg-surface p-4 shadow-card ${
        inCart ? "ring-2 ring-accent" : "border border-line"
      }`}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13.5px] font-bold text-ink">{p.sku}</span>
          <span className={`inline-flex items-center gap-1 ${STATUS_BADGE} bg-blue-50 text-blue-600`}>
            <Info size={11} /> карточка
          </span>
        </div>
        <div className="mt-1 flex flex-wrap gap-2.5 text-[11px] text-muted">
          <span className="tabular-nums">арт. {p.art}</span>
          <span>ШК {p.bar}</span>
        </div>
        {/* остатки */}
        {isService(p) ? (
          <div className="mt-1.5 text-[11px] text-muted">услуга — без склада</div>
        ) : (
          <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px]">
            <span className={`font-bold ${low ? "text-red-600" : "text-emerald-600"}`}>
              Свободно: {free}
              {low ? " ⚠" : ""}
            </span>
            {inc > 0 && (
              <span className="inline-flex items-center gap-1 font-bold text-blue-600">
                <Truck size={11} /> в пути +{inc}
              </span>
            )}
            <span className="text-muted">
              {p.wh.map((w) => `${w.n.split(" ")[0]} ${w.on - w.res}`).join(" · ")}
            </span>
          </div>
        )}
      </div>

      <div className="flex flex-col items-end gap-1.5">
        {/* цена */}
        <div className="whitespace-nowrap text-base font-bold text-ink">
          {priceChanged && (
            <span className="mr-1.5 text-[11px] font-semibold text-faint line-through">
              {formatByn(p.priceWas)}
            </span>
          )}
          {formatByn(p.priceNow)}
          {priceChanged && (
            <span
              className={`ml-1 ${STATUS_BADGE} ${
                priceUp ? "bg-red-50 text-red-600" : "bg-emerald-50 text-emerald-600"
              }`}
            >
              {priceUp ? "▲" : "▼"}
              {delta.toFixed(0)}%
            </span>
          )}
        </div>
        {/* контрол количества */}
        {inCart ? (
          <div className="flex items-center gap-1.5">
            <button
              onClick={onDec}
              className="flex h-7 w-7 items-center justify-center rounded-lg border border-line bg-surface text-muted hover:bg-sunken"
            >
              <Minus size={14} />
            </button>
            <input
              value={qty}
              inputMode="numeric"
              onChange={(e) => onSetQty(e.target.value)}
              className="w-12 rounded-lg border border-line bg-surface px-1 py-1 text-center text-[13px] tabular-nums text-ink focus:border-accent focus:outline-none"
            />
            <button
              onClick={onInc}
              className="flex h-7 w-7 items-center justify-center rounded-lg border border-line bg-surface text-muted hover:bg-sunken"
            >
              <Plus size={14} />
            </button>
          </div>
        ) : (
          <button
            onClick={onAdd}
            className="inline-flex items-center gap-1 rounded-xl bg-accent px-3.5 py-2 text-[12.5px] font-bold text-accent-ink hover:bg-accent-soft"
          >
            <Plus size={14} /> В счёт
          </button>
        )}
      </div>
    </div>
  );
}
