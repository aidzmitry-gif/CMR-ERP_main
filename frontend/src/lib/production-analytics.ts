// Домен «Аналитика производства» — read-model поверх backend-API `/production/analytics`.
// Чистые функции (fmtNh, fmtPct, fmtByn, kpiTone) тестируются без React;
// SSR-загрузка ходит на BACKEND_URL, клиентские запросы — через прокси `/api`.

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

export interface MonthPlanFact {
  month: number;
  plan_nh: number;
  fact_nh: number;
}

export interface ScrapReason {
  reason: string;
  count: number;
}

export interface TeamMember {
  name: string;
  nh_output: number;
  share_pct: number;
}

export interface TopProduct {
  product: string;
  fact_nh: number;
}

export interface AnalyticsData {
  vyrabotka_fact_nh: number; // Σ fact_nh за год
  vyrabotka_plan_nh: number; // Σ plan_nh YTD
  efficiency_pct: number; // выработка н.ч ÷ (days_worked × 8) × 100
  fpy_pct: number; // accept ÷ (accept+rework+scrap) × 100
  pass_rate_pct: number; // (accept+rework) ÷ всего × 100
  scrap_pct: number; // scrap ÷ всего × 100
  premium_fot_byn: number; // Σ (nh_output × PREMIUM_RATE)
  plan_fact_by_month: MonthPlanFact[]; // 12 месяцев
  scrap_reasons: ScrapReason[]; // причины брака desc
  team_contribution: TeamMember[]; // вклад сборщиков
  top_products: TopProduct[]; // топ изделий по факту desc
}

/** Форматировать н.ч: 1 знак после запятой, запятая как разделитель */
export function fmtNh(nh: number): string {
  return nh.toFixed(1).replace(".", ",");
}

/** Форматировать процент: 1 знак, знак % */
export function fmtPct(pct: number): string {
  return pct.toFixed(1).replace(".", ",") + "%";
}

/** Форматировать BYN: 2 знака после запятой */
export function fmtByn(val: number): string {
  const parts = val.toFixed(2).split(".");
  const int = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${int},${parts[1]} р.`;
}

/**
 * Цвет KPI-показателя.
 * "high" — чем выше тем лучше (efficiency, fpy, pass_rate): ≥80 green, ≥60 amber, else red.
 * "low"  — чем ниже тем лучше (scrap_pct): ≤5 green, ≤15 amber, else red.
 */
export function kpiTone(type: "high" | "low", pct: number): string {
  if (type === "high") {
    if (pct >= 80) return "text-green-600";
    if (pct >= 60) return "text-amber-600";
    return "text-red-600";
  }
  if (pct <= 5) return "text-green-600";
  if (pct <= 15) return "text-amber-600";
  return "text-red-600";
}

// ===== API =====

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

/** Аналитика для SSR (server component); при недоступности бэка — null. */
export async function fetchAnalyticsServer(
  year?: number,
  roles?: string,
): Promise<AnalyticsData | null> {
  try {
    const yr = year ?? new Date().getFullYear();
    const res = await fetch(`${BASE}/production/analytics?year=${yr}`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return null;
    return (await res.json()) as AnalyticsData;
  } catch {
    return null;
  }
}

/** Аналитика (клиент, через прокси /api). */
export async function fetchAnalytics(year?: number): Promise<AnalyticsData | null> {
  try {
    const yr = year ?? new Date().getFullYear();
    const res = await fetch(`/api/production/analytics?year=${yr}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as AnalyticsData;
  } catch {
    return null;
  }
}
