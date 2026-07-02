"use client";

import {
  Check,
  ClipboardList,
  FileText,
  Mic,
  Pause,
  Phone,
  PhoneForwarded,
  PhoneOff,
  Plus,
  Receipt,
  RefreshCw,
  Search,
  ShoppingCart,
  X,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  addDealItem,
  createDeal,
  createDealTask,
  createPriceQuote,
  fetchSkus,
  fetchStock,
  lookupCounterparty,
  updateDeal,
  type SkuOption,
  type StockRow,
} from "@/lib/api";
import { useCurrency } from "@/components/kanban/currency-context";
import { scriptFor } from "./call-scripts";

/**
 * Единое окно звонка (порт sales-call-popup.html, состояние «Идёт разговор»).
 *
 * ОДНО окно для лида и сделки — принципы одинаковы, отличается СКРИПТ (call-scripts.ts)
 * и итоговое действие колонки «Заказ»:
 *   • deal → подбор номенклатуры добавляется в позиции РЕАЛЬНОЙ сделки (addDealItem);
 *   • lead → позиции собираются и уходят «в сделку» (конвертация — следующий коммит).
 *
 * Фазы: dialing (короткий дозвон) → live (3 колонки) → done (итог).
 *
 * РЕАЛЬНО работает: скрипт-чеклист, реквизиты по УНП из ЕГР (lookupCounterparty),
 * подбор номенклатуры из справочника (fetchSkus), добавление позиций в сделку
 * (addDealItem), задача из звонка (createDealTask).
 * ЗАГЛУШКИ (помечены TODO): originate к АТС, отправка счёта/договора (1С),
 * резерв под счёт (SALES-51), микрофон/удержание/перевод, повтор заказа.
 */

export type CallContext =
  | {
      kind: "deal";
      dealId: string;
      number?: string;
      company: string;
      person?: string;
      phone?: string;
      stage?: string;
    }
  | {
      kind: "lead";
      leadId: number;
      company: string;
      person?: string;
      phone?: string;
      product?: string;
    }
  | {
      // Входящий с неизвестного номера / без записи — оформляем «за звонок»
      // (сделка/лид создаются при отправке счёта, как в макете livenew).
      kind: "new";
      company?: string;
      person?: string;
      phone?: string;
      callId?: number;
    };

interface OrderRow {
  skuId: number;
  code: string;
  title: string;
  unit: string;
  qty: number;
  picked: boolean;
}

/** Агрегированный остаток SKU по всем складам (подбор товара со склада в окне звонка). */
interface SkuStock {
  price: number;
  cost: number | null; // себестоимость из 1С — для маржи «в наличии»
  free: number; // ATP = Σ(available − reserved), не ниже 0
  forecast: number; // «в пути» (приход)
  warehouses: { name: string; free: number; forecast: number }[];
}

/** Свернуть строки /1c/stock в карту sku_code → агрегат (несколько складов на SKU). */
function aggregateStock(rows: StockRow[]): Record<string, SkuStock> {
  const map: Record<string, SkuStock> = {};
  for (const r of rows) {
    const free = Math.max(0, (r.qty_available || 0) - (r.qty_reserved || 0));
    const m = (map[r.sku_code] ??= { price: 0, cost: null, free: 0, forecast: 0, warehouses: [] });
    m.free += free;
    m.forecast += r.qty_forecast || 0;
    if (!m.price && r.price) m.price = r.price; // цена едина по складам
    if (m.cost == null && r.cost != null) m.cost = r.cost; // себес едина по складам
    if (free > 0 || r.qty_forecast > 0)
      m.warehouses.push({ name: r.warehouse, free, forecast: r.qty_forecast || 0 });
  }
  return map;
}

/** Срок поставки из остатка: свободное → в наличии; только в пути → в пути; иначе под заказ. */
function srokOf(s?: SkuStock): { label: string; cls: string } {
  if (!s || (s.free === 0 && s.forecast === 0)) return { label: "под заказ", cls: "text-faint" };
  if (s.free > 0) return { label: "в наличии", cls: "text-money" };
  return { label: "в пути", cls: "text-amber-600" };
}

/** Маржа позиции «в наличии» из 1С: (цена − себес)/цена. null — нет себес/цены. */
function marginOf(s?: SkuStock): { pct: number; gp: number } | null {
  if (!s || !s.price || s.cost == null) return null;
  const gp = s.price - s.cost;
  return { pct: (gp / s.price) * 100, gp };
}

// Условия оплаты — типовой B2B-набор CRM (предоплата/отсрочка/по факту) + свой вариант.
const TERMS = [
  "Предоплата 100%",
  "Предоплата 50%",
  "Отсрочка 5 дней",
  "Отсрочка 14 дней",
  "Отсрочка 30 дней",
  "По факту отгрузки",
];

/** Локальная дата+время → значение `<input type="datetime-local">` (без секунд, без TZ). */
function toDatetimeLocal(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Ближайший будущий понедельник 09:00 (сегодня-понедельник → следующий, не сегодня). */
function nextMonday9(from: Date): Date {
  const d = new Date(from);
  const day = d.getDay(); // 0=вс..6=сб, понедельник=1
  const add = ((1 - day + 7) % 7) || 7;
  d.setDate(d.getDate() + add);
  d.setHours(9, 0, 0, 0);
  return d;
}

/** Chip-пресеты «Следующего шага»: подпись + вычисленное значение datetime-local. */
function nextStepPresets(now: Date = new Date()): { label: string; value: string }[] {
  const tomorrow10 = new Date(now);
  tomorrow10.setDate(tomorrow10.getDate() + 1);
  tomorrow10.setHours(10, 0, 0, 0);

  const in3days = new Date(now);
  in3days.setDate(in3days.getDate() + 3);

  return [
    { label: "Завтра 10:00", value: toDatetimeLocal(tomorrow10) },
    { label: "Через 3 дня", value: toDatetimeLocal(in3days) },
    { label: "Понедельник 09:00", value: toDatetimeLocal(nextMonday9(now)) },
  ];
}

export function CallWindow({
  context,
  onClose,
}: {
  context: CallContext | null;
  onClose: () => void;
}) {
  const { fmt } = useCurrency(); // суммы в валюте выбранного ЮЛ (CurrencyProvider в crm/layout)
  const [phase, setPhase] = useState<"dialing" | "live" | "done">("dialing");
  const [seconds, setSeconds] = useState(0);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [skus, setSkus] = useState<SkuOption[]>([]);
  const [stock, setStock] = useState<Record<string, SkuStock>>({}); // остатки/цены по складам
  const [rows, setRows] = useState<OrderRow[]>([]);
  const [query, setQuery] = useState("");
  const [reserve, setReserve] = useState(true);
  const [unp, setUnp] = useState(""); // УНП контрагента — резолв реквизитов (ЕГР/MDM) пока заглушка
  const [req, setReq] = useState<{
    unp: string;
    org: string;
    address: string;
    status: string;
  } | null>(null);
  const [term, setTerm] = useState(TERMS[0]);
  const [customTerm, setCustomTerm] = useState(""); // свой вариант условий оплаты
  const [note, setNote] = useState("");
  const [taskDraft, setTaskDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  // created = быстрая сделка, созданная из звонка (лид/новый клиент) с перенесёнными позициями.
  const [created, setCreated] = useState<{ id: string; number: string } | null>(null);

  const kind = context?.kind ?? "deal";
  const script = useMemo(() => scriptFor(kind), [kind]);

  // Сброс + дозвон при новом звонке; предотметить «done»-пункты скрипта.
  // Намеренный сброс всего стейта при смене открытого звонка (context) — легитимный
  // «reset on key change», а не каскад от рендера.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!context) return;
    setPhase("dialing");
    setSeconds(0);
    setRows([]);
    setQuery("");
    setReserve(true);
    setUnp("");
    setReq(null);
    setTerm(TERMS[0]);
    setCustomTerm("");
    setNote("");
    setTaskDraft("");
    setBusy(false);
    setCreated(null);
    setChecked(new Set(script.flatMap((s) => s.items.filter((i) => i.done).map((i) => i.id))));
    const t = setTimeout(() => setPhase("live"), 1200);
    return () => clearTimeout(t);
  }, [context, script]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // Таймер разговора.
  useEffect(() => {
    if (phase !== "live") return;
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [phase]);

  // Esc — закрыть.
  useEffect(() => {
    if (!context) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [context, onClose]);

  // Номенклатура справочника — для колонки «Товар со склада».
  useEffect(() => {
    if (!context) return;
    let alive = true;
    void fetchSkus().then((list) => {
      if (alive) setSkus(list);
    });
    // Остатки/цены/срок по складам (несколько складов на SKU) — demo-зеркало 1С.
    void fetchStock().then((rows) => {
      if (alive) setStock(aggregateStock(rows));
    });
    return () => {
      alive = false;
    };
  }, [context]);

  function flash(msg: string) {
    setToast(msg);
    window.clearTimeout((flash as { _t?: number })._t);
    (flash as { _t?: number })._t = window.setTimeout(() => setToast(null), 1900);
  }

  if (!context) return null;
  const ctx = context; // non-null, сужённый по kind — замыкания ниже его захватывают

  const mmss = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  const title =
    ctx.company ||
    ctx.person ||
    (ctx.kind === "deal" ? "Сделка" : ctx.kind === "lead" ? "Лид" : "Новый клиент");
  const subtitle =
    ctx.kind === "deal"
      ? `${ctx.person ? `${ctx.person} · ` : ""}сделка ${ctx.number ?? ctx.dealId}`
      : ctx.kind === "lead"
        ? `${ctx.person ? `${ctx.person} · ` : ""}лид${ctx.phone ? ` · ${ctx.phone}` : ""}`
        : `${ctx.phone ?? "новый номер"} · не в базе`;

  // Кандидаты для подбора: справочник минус уже добавленные, с фильтром поиска.
  const inOrder = new Set(rows.map((r) => r.skuId));
  const candidates = skus
    .filter((s) => !inOrder.has(s.id))
    .filter((s) =>
      query.trim()
        ? `${s.title} ${s.code}`.toLowerCase().includes(query.trim().toLowerCase())
        : true,
    )
    .slice(0, 6);

  function addSku(s: SkuOption) {
    setRows((r) => [
      ...r,
      { skuId: s.id, code: s.code, title: s.title, unit: s.unit, qty: 1, picked: true },
    ]);
    setQuery("");
  }
  function setRowQty(skuId: number, qty: number) {
    setRows((r) => r.map((x) => (x.skuId === skuId ? { ...x, qty: Math.max(1, qty) } : x)));
  }
  function toggleRow(skuId: number) {
    setRows((r) => r.map((x) => (x.skuId === skuId ? { ...x, picked: !x.picked } : x)));
  }
  function removeRow(skuId: number) {
    setRows((r) => r.filter((x) => x.skuId !== skuId));
  }

  // Подтянуть реквизиты по УНП через существующий резолвер ЕГР (РБ): lookupCounterparty
  // → /integrations/egr. Бэкенд сам отдаёт demo-данные, если ЕГР не сконфигурирован
  // (base_url пуст) — контракт RegistryInfo один и тот же, спец-обработки demo тут нет.
  async function pullReq() {
    const clean = unp.replace(/\D/g, "");
    if (clean.length !== 9) return flash("УНП — 9 цифр");
    setBusy(true);
    const info = await lookupCounterparty(clean);
    setBusy(false);
    if (!info) return flash("⚠️ По УНП ничего не найдено");
    setReq({ unp: info.unp || clean, org: info.name, address: info.address, status: info.status });
    flash("✅ Реквизиты подтянуты из ЕГР");
  }

  const pickedRows = rows.filter((r) => r.picked);
  // Итог заказа по ценам со склада (для счёта); НДС 20%.
  const orderTotal = pickedRows.reduce((sum, r) => sum + (stock[r.code]?.price ?? 0) * r.qty, 0);
  // Себес/маржа — ТОЛЬКО по позициям «в наличии» (себес из 1С). Под-заказ (нет себес)
  // в маржу не идёт — она появится с предрасчётом ([[pricing-calculation-todo]]).
  const costedRows = pickedRows.filter((r) => stock[r.code]?.cost != null);
  const costedRevenue = costedRows.reduce((s, r) => s + (stock[r.code]?.price ?? 0) * r.qty, 0);
  const orderCost = costedRows.reduce((s, r) => s + (stock[r.code]?.cost ?? 0) * r.qty, 0);
  const orderMargin = costedRevenue - orderCost;
  const hasUnderOrder = pickedRows.some((r) => stock[r.code]?.cost == null);

  // Колонка «Заказ» — главное действие зависит от контекста.
  async function commitOrder() {
    if (!pickedRows.length) return flash("Отметьте хотя бы одну позицию");
    setBusy(true);
    // Зафиксировать цену со склада клиенту (Price Engine) → позиция сделки покажет цену.
    const quotePrices = (cp: string) => {
      for (const r of pickedRows) {
        const p = stock[r.code]?.price;
        if (p) void createPriceQuote(r.code, cp, p);
      }
    };
    if (ctx.kind === "deal") {
      let ok = 0;
      for (const r of pickedRows) {
        if (await addDealItem(ctx.dealId, r.skuId, r.qty)) ok++;
      }
      quotePrices(ctx.company);
      flash(`✅ В сделку добавлено позиций: ${ok}/${pickedRows.length}`);
      setBusy(false);
      return;
    }
    // Быстрая сделка из звонка (лид / новый клиент): создаём сделку и переносим
    // подобранные позиции. convertLead требует routed-статус, поэтому для звонка делаем
    // прямую сделку (createDeal) + addDealItem; полноценную привязку к лиду (статус
    // converted) добавим эндпоинтом «быстрая сделка» отдельным шагом (SALES).
    // Реквизиты по УНП (если подтянули) дают официальное наименование, когда у лида/
    // нового клиента нет компании — иначе сохраняем известную компанию лида.
    const counterparty = ctx.company || req?.org || ctx.phone || "Новый клиент";
    // Date.now() в обработчике клика (не в рендере) — уникальный номер счёта в момент действия.
    // eslint-disable-next-line react-hooks/purity
    const number = `CRM-CALL-${Date.now().toString(36).toUpperCase()}`;
    const deal = await createDeal({
      number,
      title: `Заявка со звонка${ctx.company ? ` · ${ctx.company}` : ""}`,
      counterparty,
      amount: orderTotal, // сумма сделки = итог заказа по ценам со склада
      priority: "Средний",
      stage: "new",
      owner: "",
    });
    if (!deal) {
      flash("⚠️ Не удалось создать сделку");
      setBusy(false);
      return;
    }
    let ok = 0;
    for (const r of pickedRows) {
      if (await addDealItem(deal.id, r.skuId, r.qty)) ok++;
    }
    quotePrices(counterparty);
    if (ctx.kind === "lead") {
      // Пометить лиду намерение конвертации (списком позиций) — пока заметкой.
      void createDealTask(`lead:${ctx.leadId}`, {
        title: `Быстрая сделка ${deal.number} из звонка: ${pickedRows.map((r) => `${r.title}×${r.qty}`).join(", ")}`,
      });
    }
    setCreated({ id: deal.id, number: deal.number });
    flash(`✅ Сделка ${deal.number} создана · позиций: ${ok}/${pickedRows.length}`);
    setBusy(false);
  }

  async function addTask() {
    if (!taskDraft.trim()) return;
    setBusy(true);
    if (ctx.kind === "new") {
      // Записи ещё нет — задача уйдёт вместе с созданием сделки при оформлении.
      flash("✅ Заметка сохранена (привяжется к сделке)");
      setTaskDraft("");
      setBusy(false);
      return;
    }
    // У сделки — реальный числовой id (эндпоинт /deals/{id}/tasks). У лида пока entity_ref
    // `lead:{id}` (как в lead-call-popup) — бэкенд задач для лида ждёт SALES; fire-and-forget.
    const ref = ctx.kind === "deal" ? ctx.dealId : `lead:${ctx.leadId}`;
    await createDealTask(ref, { title: taskDraft.trim() });
    setTaskDraft("");
    flash("✅ Задача поставлена");
    setBusy(false);
  }

  const openHref =
    ctx.kind === "deal"
      ? `/crm/deals/${ctx.dealId}`
      : ctx.kind === "lead"
        ? `/crm/leads/${ctx.leadId}`
        : "/crm/leads";

  return (
    <div
      aria-modal
      role="dialog"
      aria-label={`Звонок · ${title}`}
      className="fixed inset-0 z-[60] flex items-center justify-center bg-ink/45 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[92vh] w-[980px] max-w-[96vw] flex-col overflow-hidden rounded-2xl bg-surface shadow-pop"
      >
        {/* ── Шапка ── */}
        <header
          className={`flex items-center gap-3 px-5 py-3.5 text-white ${
            phase === "done"
              ? "bg-gradient-to-br from-slate-500 to-slate-700"
              : "bg-gradient-to-br from-emerald-500 to-emerald-700"
          }`}
        >
          <div
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/20 ${
              phase === "dialing" ? "animate-pulse" : ""
            }`}
          >
            {phase === "done" ? <PhoneOff size={20} /> : <Phone size={20} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[14px] font-bold">
              {phase === "dialing"
                ? "Соединение…"
                : phase === "done"
                  ? "Итог звонка"
                  : `Разговор · ${title}`}
            </div>
            <div className="truncate text-[12px] opacity-90">{subtitle}</div>
          </div>
          {phase === "live" && (
            <div className="font-mono text-[20px] font-bold tabular-nums">{mmss}</div>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-white/80 hover:bg-white/20"
          >
            <X size={16} />
          </button>
        </header>

        {/* ── Тело ── */}
        {phase === "done" ? (
          <DoneSummary
            ctx={ctx}
            seconds={seconds}
            title={title}
            onClose={onClose}
            taskDraft={taskDraft}
            setTaskDraft={setTaskDraft}
            addTask={addTask}
            busy={busy}
            flash={flash}
          />
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-px overflow-y-auto bg-line md:grid-cols-[1fr_1fr_0.9fr]">
            {/* колонка 1: скрипт */}
            <section className="min-w-0 space-y-3 bg-surface p-4">
              <ColHeader icon={<ClipboardList size={14} />}>
                Скрипт звонка{" "}
                {ctx.kind === "deal" ? "· сделка" : ctx.kind === "lead" ? "· лид" : "· новый клиент"}
              </ColHeader>
              {script.map((sec) => (
                <div key={sec.n}>
                  <div className="mb-1.5 flex items-center gap-2 text-[12px] font-bold uppercase tracking-wide text-accent-ink">
                    <span className="flex h-5 w-5 items-center justify-center rounded-md bg-accent/15 text-[11px] text-accent-ink">
                      {sec.n}
                    </span>
                    {sec.title}
                  </div>
                  <div className="space-y-1">
                    {sec.items.map((it) => {
                      const on = checked.has(it.id);
                      return (
                        <button
                          key={it.id}
                          type="button"
                          onClick={() =>
                            setChecked((s) => {
                              const n = new Set(s);
                              n.has(it.id) ? n.delete(it.id) : n.add(it.id);
                              return n;
                            })
                          }
                          className={`flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-[12.5px] transition ${
                            it.tip ? "bg-amber-50 dark:bg-amber-500/10" : "hover:bg-sunken"
                          }`}
                        >
                          <span
                            className={`mt-px flex h-[15px] w-[15px] shrink-0 items-center justify-center rounded border ${
                              on
                                ? "border-money bg-money text-white"
                                : "border-line-strong text-transparent"
                            }`}
                          >
                            <Check size={11} />
                          </span>
                          <span className={on ? "text-faint line-through" : "text-ink"}>
                            {it.text}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </section>

            {/* колонка 2: заказ / счёт */}
            <section className="min-w-0 space-y-3 bg-surface p-4">
              <ColHeader icon={<ShoppingCart size={14} />}>Заказ / счёт</ColHeader>

              {/* Реквизиты по УНП (лид/новый клиент): подтянуть из ЕГР перед подбором.
                  Резолв — заглушка (demo); реальный ЕГР/MDM — SALES. У сделки контрагент
                  уже известен, поэтому блок только для lead/new. */}
              {ctx.kind !== "deal" && (
                <div>
                  <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-bold uppercase tracking-wide text-muted">
                    <StepNum n={1} />
                    Реквизиты по УНП
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      value={unp}
                      onChange={(e) => setUnp(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void pullReq();
                      }}
                      inputMode="numeric"
                      placeholder="УНП (9 цифр)"
                      aria-label="УНП контрагента"
                      className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink outline-none focus:border-accent"
                    />
                    <Button variant="primary" size="sm" onClick={pullReq} disabled={busy}>
                      Подтянуть
                    </Button>
                  </div>
                  {req && (
                    <div className="mt-1.5 space-y-1 rounded-lg border border-money/40 bg-money-soft px-2.5 py-2 text-[11.5px]">
                      <div className="font-semibold text-money">
                        ✅ Реквизиты по УНП {req.unp} — ЕГР
                      </div>
                      <ReqRow k="Организация" v={req.org} />
                      <ReqRow k="Адрес" v={req.address} />
                      {req.status && <ReqRow k="Статус" v={req.status} />}
                    </div>
                  )}
                  <div className="mt-1 text-[11px] text-faint">
                    Реквизиты из ЕГР (egr.gov.by) через интеграцию; demo-данные, если ЕГР не
                    сконфигурирован.
                  </div>
                </div>
              )}

              {/* Товар со склада — реальная номенклатура */}
              <div>
                <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-bold uppercase tracking-wide text-muted">
                  {ctx.kind !== "deal" && <StepNum n={2} />}
                  Товар со склада
                </div>
                {rows.length > 0 && (
                  <div className="mb-2 space-y-1.5">
                    {rows.map((r) => {
                      const st = stock[r.code];
                      const s = srokOf(st);
                      const m = marginOf(st);
                      return (
                        <div
                          key={r.skuId}
                          className="flex items-center gap-2 rounded-lg border border-line bg-sunken px-2.5 py-1.5"
                        >
                          <input
                            type="checkbox"
                            checked={r.picked}
                            onChange={() => toggleRow(r.skuId)}
                            className="h-4 w-4 accent-money"
                            aria-label={`Включить ${r.title}`}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-[12.5px] font-semibold text-ink">
                              {r.title}
                            </div>
                            <div className="truncate text-[11px] text-faint">
                              {st?.price ? `${fmt(st.price)} · ` : ""}своб {st?.free ?? 0}
                              {st?.forecast ? ` · в пути ${st.forecast}` : ""} ·{" "}
                              <span className={s.cls}>{s.label}</span>
                              {m ? (
                                <span className="text-money"> · маржа {Math.round(m.pct)}%</span>
                              ) : st?.free === 0 ? (
                                <span className="text-faint"> · себес из предрасчёта</span>
                              ) : null}
                            </div>
                          </div>
                          <input
                            value={r.qty}
                            onChange={(e) =>
                              setRowQty(r.skuId, parseInt(e.target.value.replace(/\D/g, ""), 10) || 1)
                            }
                            inputMode="numeric"
                            className="w-12 rounded-md border border-line bg-surface px-1.5 py-1 text-center text-[12.5px] tabular-nums text-ink outline-none focus:border-accent"
                            aria-label={`Количество ${r.title}`}
                          />
                          <button
                            type="button"
                            onClick={() => removeRow(r.skuId)}
                            aria-label="Убрать позицию"
                            className="text-faint hover:text-danger"
                          >
                            <X size={14} />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Поиск/подбор из справочника */}
                <div className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5">
                  <Search size={13} className="text-faint" />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Подобрать товар по названию / коду…"
                    className="min-w-0 flex-1 bg-transparent text-[12.5px] text-ink outline-none"
                  />
                </div>
                {(query.trim() || rows.length === 0) && (
                  <div className="mt-1 space-y-1">
                    {candidates.map((s) => {
                      const st = stock[s.code];
                      const sk = srokOf(st);
                      const m = marginOf(st);
                      return (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => addSku(s)}
                          className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-sunken"
                        >
                          <Plus size={13} className="mt-0.5 shrink-0 text-accent-ink" />
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2">
                              <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink">
                                {s.title}
                              </span>
                              <span className="shrink-0 text-[11px] text-faint">{s.code}</span>
                            </span>
                            <span className="mt-0.5 block truncate text-[11px] text-faint">
                              {st?.price ? `${fmt(st.price)} · ` : ""}своб {st?.free ?? 0}
                              {st?.forecast ? ` · в пути ${st.forecast}` : ""} ·{" "}
                              <span className={sk.cls}>{sk.label}</span>
                              {m ? (
                                <span className="text-money"> · маржа {Math.round(m.pct)}%</span>
                              ) : st?.free === 0 ? (
                                <span className="text-faint"> · предрасчёт</span>
                              ) : null}
                            </span>
                          </span>
                        </button>
                      );
                    })}
                    {candidates.length === 0 && (
                      <div className="px-2 py-1.5 text-[12px] text-faint">
                        {skus.length ? "Ничего не найдено" : "Загрузка номенклатуры…"}
                      </div>
                    )}
                    <div className="px-2 pt-0.5 text-[11px] text-faint">
                      номенклатура · 1С (через MDM); остатки по складам, цена и срок — из 1С
                      (demo); резерв под счёт — SALES-51
                    </div>
                  </div>
                )}
              </div>

              {/* Резерв + условия оплаты */}
              <label className="flex items-center gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-2.5 py-2 text-[12.5px] font-semibold text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
                <input
                  type="checkbox"
                  checked={reserve}
                  onChange={(e) => setReserve(e.target.checked)}
                  className="h-4 w-4 accent-amber-500"
                />
                📦 Зарезервировать под счёт
                <span className="ml-auto text-[11px] font-normal text-faint">SALES-51</span>
              </label>

              <div>
                <div className="mb-1 text-[12px] font-bold uppercase tracking-wide text-muted">
                  Условия оплаты
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {TERMS.map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setTerm(t)}
                      className={`rounded-lg border px-2.5 py-1.5 text-[12px] font-semibold transition ${
                        term === t
                          ? "border-accent bg-accent/10 text-accent-ink"
                          : "border-line text-muted hover:bg-sunken"
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                  <input
                    value={customTerm}
                    onChange={(e) => {
                      setCustomTerm(e.target.value);
                      setTerm(e.target.value || TERMS[0]);
                    }}
                    placeholder="свой вариант…"
                    aria-label="Свой вариант условий оплаты"
                    className={`w-32 rounded-lg border px-2.5 py-1.5 text-[12px] outline-none ${
                      customTerm && term === customTerm
                        ? "border-accent bg-accent/10 text-accent-ink"
                        : "border-line text-ink focus:border-accent"
                    }`}
                  />
                </div>
              </div>

              {orderTotal > 0 && (
                <div className="flex items-center justify-between rounded-lg bg-sunken px-3 py-2 text-[12.5px]">
                  <span className="text-muted">Итого{reserve ? " · резерв" : ""}</span>
                  <span className="font-bold text-ink">
                    {fmt(orderTotal)}
                    <span className="ml-1 font-normal text-faint">
                      · с НДС {fmt(orderTotal * 1.2)}
                    </span>
                  </span>
                </div>
              )}

              {/* Маржа по позициям «в наличии» (себес из 1С); под-заказ — отдельно (предрасчёт) */}
              {costedRows.length > 0 && costedRevenue > 0 && (
                <div className="flex items-center justify-between rounded-lg bg-money-soft px-3 py-2 text-[12px]">
                  <span className="font-semibold text-money">
                    Маржа{hasUnderOrder ? " · в наличии" : ""}
                  </span>
                  <span className="font-bold text-money">
                    {fmt(orderMargin)} ({Math.round((orderMargin / costedRevenue) * 100)}%)
                    <span className="ml-1 font-normal text-faint">· себес {fmt(orderCost)}</span>
                  </span>
                </div>
              )}
              {hasUnderOrder && (
                <p className="text-[11px] text-faint">
                  Под-заказ позиции — себестоимость из предварительного расчёта (скоро); пока в марже не учтены.
                </p>
              )}

              {/* CTA по контексту */}
              <div className="space-y-2 pt-1">
                <Button
                  variant="money"
                  block
                  onClick={commitOrder}
                  disabled={busy || !pickedRows.length}
                  icon={<ShoppingCart size={14} />}
                >
                  {context.kind === "deal"
                    ? `Добавить в сделку${pickedRows.length ? ` (${pickedRows.length})` : ""}`
                    : `Создать сделку с товаром${pickedRows.length ? ` (${pickedRows.length})` : ""}`}
                </Button>
                {created && (
                  <div className="rounded-lg border border-money/40 bg-money-soft px-3 py-2 text-[12.5px] text-money">
                    ✅ Создана{" "}
                    <Link href={`/crm/deals/${created.id}`} className="font-bold underline">
                      {created.number}
                    </Link>{" "}
                    с позициями — откройте, чтобы продолжить.
                  </div>
                )}
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => flash("🧾 Предпросмотр счёта — подключим к 1С (SALES)")}
                    icon={<Receipt size={13} />}
                  >
                    Счёт
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => flash("📄 Предпросмотр договора — по УНП (SALES-53)")}
                    icon={<FileText size={13} />}
                  >
                    Договор
                  </Button>
                </div>
                <p className="text-[11px] text-faint">
                  Счёт/договор и резерв подключим к 1С отдельным шагом — сейчас подбор и позиции
                  сделки работают вживую.
                </p>
              </div>
            </section>

            {/* колонка 3: управление звонком */}
            <section className="min-w-0 space-y-3 bg-surface p-4">
              <ColHeader icon={<Phone size={14} />}>Управление звонком</ColHeader>

              <div className="flex items-center gap-2.5 rounded-xl border border-line bg-sunken px-3 py-2.5">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/15 text-[12px] font-bold text-accent-ink">
                  {(context.company || "—").slice(0, 2).toUpperCase()}
                </div>
                <div className="min-w-0">
                  <div className="truncate text-[12.5px] font-semibold text-ink">{title}</div>
                  <div className="truncate text-[11.5px] text-muted">
                    {context.kind === "deal"
                      ? `${context.stage ? `${context.stage} · ` : ""}${context.number ?? context.dealId}`
                      : context.kind === "lead"
                        ? context.product || "новый интерес"
                        : `${context.phone ?? "новый номер"} · не в базе`}
                  </div>
                </div>
              </div>

              {/* микрофон / удержание / перевод — заглушки управления линией */}
              <div className="grid grid-cols-3 gap-1.5">
                {[
                  { icon: <Mic size={13} />, label: "Микр." },
                  { icon: <Pause size={13} />, label: "Удерж." },
                  { icon: <PhoneForwarded size={13} />, label: "Перевод" },
                ].map((b) => (
                  <button
                    key={b.label}
                    type="button"
                    onClick={() => flash(`«${b.label}» — управление линией АТС (SALES-50)`)}
                    className="flex flex-col items-center gap-1 rounded-lg border border-line bg-surface py-2 text-[11px] font-semibold text-muted hover:bg-sunken"
                  >
                    {b.icon}
                    {b.label}
                  </button>
                ))}
              </div>

              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Живая заметка по звонку…"
                className="min-h-[72px] w-full resize-y rounded-lg border border-line bg-surface px-2.5 py-2 text-[12.5px] text-ink outline-none focus:border-accent"
              />

              {/* быстрая задача */}
              <div className="flex gap-2">
                <input
                  value={taskDraft}
                  onChange={(e) => setTaskDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void addTask();
                  }}
                  placeholder="Задача: перезвонить, выслать КП…"
                  className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2.5 py-2 text-[12.5px] text-ink outline-none focus:border-accent"
                />
                <Button variant="primary" size="sm" onClick={addTask} disabled={busy || !taskDraft.trim()}>
                  <Plus size={14} />
                </Button>
              </div>

              <div className="flex items-start gap-1.5 rounded-lg bg-amber-50 px-2.5 py-2 text-[11.5px] text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
                <Zap size={13} className="mt-px shrink-0" />
                <span>
                  <b>Резерв под счёт:</b> при дефиците уйдёт запрос закупщику на подтверждение
                  срока.
                </span>
              </div>

              <div className="space-y-2 pt-1">
                <Button variant="hangup" block onClick={() => setPhase("done")} icon={<PhoneOff size={14} />}>
                  Завершить
                </Button>
                <Link href={openHref} className="block">
                  <Button variant="secondary" block icon={<ClipboardList size={13} />}>
                    {context.kind === "deal" ? "Открыть сделку" : "Открыть лид"}
                  </Button>
                </Link>
              </div>
            </section>
          </div>
        )}

        {toast && (
          <div className="pointer-events-none absolute bottom-4 left-1/2 z-10 -translate-x-1/2 rounded-lg bg-ink px-4 py-2 text-[12.5px] font-semibold text-canvas shadow-pop">
            {toast}
          </div>
        )}
      </div>
    </div>
  );
}

function ColHeader({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 border-b border-line pb-2 text-[12.5px] font-bold text-ink">
      <span className="text-accent-ink">{icon}</span>
      {children}
    </div>
  );
}

/** Номер шага оформления (① Реквизиты по УНП → ② Товар со склада). */
function StepNum({ n }: { n: number }) {
  return (
    <span className="flex h-[18px] w-[18px] items-center justify-center rounded-md bg-accent/15 text-[11px] font-bold text-accent-ink">
      {n}
    </span>
  );
}

/** Строка подтянутых реквизитов (ключ → значение). */
function ReqRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3 text-faint">
      <span>{k}</span>
      <span className="text-right font-medium text-ink">{v}</span>
    </div>
  );
}

function DoneSummary({
  ctx,
  seconds,
  title,
  onClose,
  taskDraft,
  setTaskDraft,
  addTask,
  busy,
  flash,
}: {
  ctx: CallContext;
  seconds: number;
  title: string;
  onClose: () => void;
  taskDraft: string;
  setTaskDraft: (v: string) => void;
  addTask: () => void;
  busy: boolean;
  flash: (msg: string) => void;
}) {
  const [result, setResult] = useState("Дозвонился");
  const [next, setNext] = useState("");
  const [saving, setSaving] = useState(false);
  const dur = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  const presets = useMemo(() => nextStepPresets(), []);

  /** Сохранить итог звонка: next_step(текст)+next_step_at(дата) на сделке + задача-напоминание.
   * Для лида/нового клиента (нет числового id сделки) — только задача-заметка (как addTask). */
  async function saveAndClose() {
    if (!next) {
      onClose();
      return;
    }
    setSaving(true);
    const isoLocal = next.length === 16 ? `${next}:00` : next; // datetime-local без секунд
    if (ctx.kind === "deal") {
      await updateDeal(ctx.dealId, { next_step: result, next_step_at: isoLocal });
      await createDealTask(ctx.dealId, { title: `Следующий шаг: ${result}`, due_at: isoLocal });
      flash("✅ Следующий шаг сохранён");
    } else if (ctx.kind === "lead") {
      await createDealTask(`lead:${ctx.leadId}`, {
        title: `Следующий шаг: ${result}`,
        due_at: isoLocal,
      });
    }
    setSaving(false);
    onClose();
  }

  return (
    <div className="space-y-4 p-5">
      <div className="text-[12.5px] text-muted">
        Звонок завершён · {dur} · {title}
      </div>

      <div>
        <div className="mb-1.5 text-[12px] font-bold uppercase tracking-wide text-muted">
          Результат звонка
        </div>
        <div className="flex flex-wrap gap-1.5">
          {["Дозвонился", "Не дозвонился", "Перезвонить", "Отказ"].map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setResult(r)}
              className={`rounded-lg border px-3 py-1.5 text-[12.5px] font-semibold transition ${
                result === r
                  ? "border-accent bg-accent/10 text-accent-ink"
                  : "border-line text-muted hover:bg-sunken"
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div>
        <div className="mb-1.5 text-[12px] font-bold uppercase tracking-wide text-muted">
          Следующий шаг
        </div>
        <div className="mb-1.5 flex flex-wrap gap-1.5">
          {presets.map((p) => (
            <button
              key={p.label}
              type="button"
              onClick={() => setNext(p.value)}
              className={`rounded-lg border px-2.5 py-1 text-[12px] font-medium transition ${
                next === p.value
                  ? "border-accent bg-accent/10 text-accent-ink"
                  : "border-line text-muted hover:bg-sunken"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <input
          type="datetime-local"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
        />
      </div>

      <div className="flex gap-2">
        <input
          value={taskDraft}
          onChange={(e) => setTaskDraft(e.target.value)}
          placeholder="Поставить задачу коллеге…"
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
        />
        <Button variant="secondary" size="sm" onClick={addTask} disabled={busy || !taskDraft.trim()}>
          Задача
        </Button>
      </div>

      <div className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
        🔴 Запись сохранена · ИИ-транскрибация и резюме подтянутся в карточку (SALES-50).
      </div>

      <Button
        variant="money"
        block
        onClick={() => void saveAndClose()}
        disabled={saving}
        icon={<Check size={15} />}
      >
        Сохранить и закрыть
      </Button>
    </div>
  );
}
