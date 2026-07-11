/**
 * Конструктор месячного плана продавца — чистая доменная логика (без React).
 *
 * Контракт с бэкендом (GET /sales/plan-sources, PUT /sales/plan-items) описан в типах
 * ниже. Компонент (`components/plan/plan-constructor.tsx`) только рендерит и держит
 * состояние формы; вся арифметика и защита от краевых случаев — здесь, чтобы её можно
 * было тестировать без React (см. plan-constructor.test.ts).
 */

export type PlanItemSource = "committed" | "regular" | "activity";

/** Строка снапшота плана — то, что улетает в PUT /sales/plan-items (см. PlanItemIn бэкенда). */
export interface PlanItemIn {
  source: PlanItemSource;
  ref: string;
  title: string;
  when_label: string;
  revenue: number;
  gross: number;
  probability: number;
  enabled: boolean;
}

/** Рабочая строка конструктора на фронте — по форме идентична PlanItemIn. */
export type PlanItemDraft = PlanItemIn;

/** Сохранённая строка снапшота (ответ GET/PUT). created_at — опционально: контракт его
 * не гарантирует, но если бэкенд отдаёт время создания снапшота — используем для подписи. */
export interface PlanItemOut extends PlanItemIn {
  id: number;
  owner_id: number;
  period_key: string;
  created_at?: string;
}

export interface CommittedRow {
  ref: string;
  title: string;
  when_label: string;
  revenue: number;
  gross: number | null;
  probability: number;
}

export interface RegularRow {
  counterparty: string;
  orders_count: number;
  cycle_days: number | null;
  last_order: string; // ISO yyyy-mm-dd
  expected: string | null; // ISO yyyy-mm-dd
  in_month: boolean;
  avg_check: number;
  probability: number;
  gross: number | null;
}

export interface CalcDefaults {
  avg_check: number | null;
  margin_pct: number | null;
}

export interface PlanSources {
  month: string;
  owner: string | null;
  base_gross: number | null;
  committed: CommittedRow[];
  regulars: RegularRow[];
  defaults: CalcDefaults;
  saved_items: PlanItemOut[];
}

export interface ActivityInput {
  leads: number;
  leadConvPct: number;
  calls: number;
  callConvPct: number;
  avgCheck: number;
  marginPct: number;
}

export interface ActivityResult {
  deals: number;
  revenue: number;
  gross: number;
}

/** "05.07" из ISO "2026-07-05" — строкой, без Date (без риска сдвига по TZ). */
export function formatDateShort(iso: string): string {
  const parts = iso.split("-");
  if (parts.length !== 3) return iso;
  const [, m, d] = parts;
  return `${d}.${m}`;
}

/** Подпись в колонке «Ожид. заказ»: дата ожидания либо периодичность, если даты ещё нет. */
export function regularWhenLabel(r: RegularRow): string {
  if (r.expected) return `ожид. ${formatDateShort(r.expected)}`;
  if (r.cycle_days != null) return `цикл ~${r.cycle_days} дн`;
  return "цикл не определён";
}

/** Подпись под именем клиента: «цикл ~N дн · посл. дата» либо «1 заказ — цикла ещё нет». */
export function regularCycleCaption(r: RegularRow): string {
  if (r.cycle_days == null) return "1 заказ — цикла ещё нет";
  return `цикл ~${r.cycle_days} дн · посл. ${formatDateShort(r.last_order)}`;
}

/** Источники → рабочие драфт-строки. committed всегда включены; regular — только те,
 * что ожидаются в месяце (in_month); остальные показываются, но выключены (можно подтянуть раньше). */
export function toDrafts(sources: PlanSources): PlanItemDraft[] {
  const committed: PlanItemDraft[] = sources.committed.map((c) => ({
    source: "committed",
    ref: c.ref,
    title: c.title,
    when_label: c.when_label,
    revenue: c.revenue,
    gross: c.gross ?? 0,
    probability: c.probability,
    enabled: true,
  }));
  const regulars: PlanItemDraft[] = sources.regulars.map((r) => ({
    source: "regular",
    // ref на бэке ограничен 64 символами (PlanItemIn + String(64)) — длинное юрнаименование
    // без усечения даёт 422 на ВЕСЬ снапшот; полное имя остаётся в title.
    ref: r.counterparty.slice(0, 64), // ponytail: уникальность в рамках постоянных клиентов владельца
    title: r.counterparty,
    when_label: regularWhenLabel(r),
    revenue: r.avg_check,
    gross: r.gross ?? 0,
    probability: r.probability,
    enabled: r.in_month,
  }));
  return [...committed, ...regulars];
}

/** Калькулятор новых по действиям: заявки/звонки × конверсия → сделки → выручка → вал. прибыль. */
export function calcActivity(input: ActivityInput): ActivityResult {
  const dealsFromLeads = (input.leads * input.leadConvPct) / 100;
  const dealsFromCalls = (input.calls * input.callConvPct) / 100;
  const deals = dealsFromLeads + dealsFromCalls;
  const revenue = deals * input.avgCheck;
  const gross = (revenue * input.marginPct) / 100;
  return { deals, revenue, gross };
}

/** Суммы enabled-строк по источнику; s3 — калькулятор активности (передаётся отдельно,
 * т.к. это не строка из toDrafts, а расчёт). */
export function assemble(
  drafts: PlanItemDraft[],
  activityGross: number,
): { s1: number; s2: number; s3: number; total: number } {
  let s1 = 0;
  let s2 = 0;
  for (const d of drafts) {
    if (!d.enabled) continue;
    if (d.source === "committed") s1 += d.gross;
    else if (d.source === "regular") s2 += d.gross;
  }
  const s3 = activityGross;
  return { s1, s2, s3, total: s1 + s2 + s3 };
}

/** Вердикт против базы РОПа. null — база ещё не согласована/не введена (нет с чем сравнивать). */
export function verdictOf(base: number | null, total: number): { ok: boolean; diff: number } | null {
  if (base == null) return null;
  const diff = total - base;
  return { ok: diff >= 0, diff };
}

/** Обратный счёт: сколько ещё новых сделок/заявок/звонков нужно, чтобы закрыть дефицит.
 * null — либо дефицита нет, либо чек/маржа нулевые (прибыль со сделки не считается вовсе).
 * needLeads/needCalls — null персонально, если соответствующая конверсия нулевая. */
export function reverseCount(
  deficit: number,
  input: { leadConvPct: number; callConvPct: number; avgCheck: number; marginPct: number },
): { needDeals: number; needLeads: number | null; needCalls: number | null } | null {
  if (deficit <= 0) return null;
  const perDealGross = (input.avgCheck * input.marginPct) / 100;
  if (perDealGross <= 0) return null; // защита от деления на ноль
  const needDeals = Math.ceil(deficit / perDealGross);
  const needLeads = input.leadConvPct > 0 ? Math.ceil(needDeals / (input.leadConvPct / 100)) : null;
  const needCalls = input.callConvPct > 0 ? Math.ceil(needDeals / (input.callConvPct / 100)) : null;
  return { needDeals, needLeads, needCalls };
}

/** "YYYY-MM" следующего календарного месяца от даты d (планы строят наперёд). */
export function nextMonthKey(d: Date): string {
  const next = new Date(d.getFullYear(), d.getMonth() + 1, 1);
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
}

/** Метрики PlanTarget из собранного плана (см. deal-plan-editor.tsx — те же ключи метрик). */
export function metricsFromPlan(args: {
  totalGross: number;
  activity: ActivityInput & ActivityResult;
}): { metric: string; target: number }[] {
  const { totalGross, activity } = args;
  return [
    { metric: "gross_profit", target: totalGross },
    { metric: "new_deals_count", target: Math.round(activity.deals) },
    { metric: "cold_calls", target: activity.calls },
    { metric: "leads", target: activity.leads },
    { metric: "new_deals_amount", target: activity.revenue },
  ];
}

/** Накладывает сохранённый снапшот (enabled/gross) на свежие драфты по ключу (source, ref).
 * ponytail: строки, исчезнувшие из источников, теряются — снапшот пересобирается заново. */
export function mergeSaved(drafts: PlanItemDraft[], savedItems: PlanItemOut[]): PlanItemDraft[] {
  const bySavedKey = new Map(savedItems.map((s) => [`${s.source}:${s.ref}`, s]));
  return drafts.map((d) => {
    const saved = bySavedKey.get(`${d.source}:${d.ref}`);
    if (!saved) return d;
    return { ...d, enabled: saved.enabled, gross: saved.gross };
  });
}
