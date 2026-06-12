// Домен «Планирование · план/факт» производства поверх backend-API `/production/plan`.
// Чистые функции (loadTone, fmtNh) тестируются без React;
// SSR-загрузка ходит на BACKEND_URL, клиентские мутации — через прокси `/api`.

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

export interface PlanCell {
  month: number; // 1..12
  plan_qty: number;
  plan_nh: number; // plan_qty × norm_nh (считает бэк)
  fact_qty: number;
  fact_nh: number; // fact_qty × norm_nh (считает бэк)
}

export interface PlanRow {
  product: string;
  norm_nh: number; // н.ч/шт из утверждённой нормы (0 если нет)
  months: PlanCell[]; // всегда 12 элементов
  year_qty: number;
  year_nh: number;
}

export interface PlanTotals {
  month_nh: number[]; // план н.ч по месяцам (12)
  fact_nh: number[]; // факт н.ч по месяцам (12)
  load_pct: number[]; // plan_nh / capacity_nh * 100 (12)
  year_nh: number;
  plan_ytd: number;
  fact_ytd: number;
  peak_month: number; // 0-based индекс
  low_month: number;
}

export interface PlanBoard {
  year: number;
  capacity_nh: number; // мощность цеха н.ч/мес (workers × 176)
  rows: PlanRow[];
  totals: PlanTotals;
}

export interface PlanCellUpdate {
  year: number;
  product: string;
  month: number;
  plan_qty: number;
}

export interface PlanPositionUpsert {
  year: number;
  product: string;
  monthly: number[]; // ровно 12 значений
}

/** Цвет загрузки по порогам: >100 → red, ≥70 → amber, else → green */
export function loadTone(pct: number): string {
  if (pct > 100) return "bg-red-50 text-red-600";
  if (pct >= 70) return "bg-amber-50 text-amber-600";
  return "bg-green-50 text-green-600";
}

/** Форматировать н.ч: 1 знак после запятой, разделитель — запятая */
export function fmtNh(nh: number): string {
  return nh.toFixed(1).replace(".", ",");
}

// ===== API =====

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

/** Доска планирования для SSR (server component); при недоступности бэка — null. */
export async function fetchPlanServer(year?: number, roles?: string): Promise<PlanBoard | null> {
  try {
    const yr = year ?? new Date().getFullYear();
    const res = await fetch(`${BASE}/production/plan?year=${yr}`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return null;
    return (await res.json()) as PlanBoard;
  } catch {
    return null;
  }
}

/** Доска планирования (клиент, через прокси /api). */
export async function fetchPlan(year?: number): Promise<PlanBoard | null> {
  try {
    const yr = year ?? new Date().getFullYear();
    const res = await fetch(`/api/production/plan?year=${yr}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as PlanBoard;
  } catch {
    return null;
  }
}

/** Upsert одной ячейки (год+изделие+месяц). Возвращает обновлённый board. */
export async function putPlanCell(update: PlanCellUpdate): Promise<PlanBoard | null> {
  try {
    const res = await fetch("/api/production/plan/cell", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    });
    if (!res.ok) return null;
    return (await res.json()) as PlanBoard;
  } catch {
    return null;
  }
}

/** Создать/заменить позицию на год целиком (12 ячеек). */
export async function upsertPosition(data: PlanPositionUpsert): Promise<PlanBoard | null> {
  try {
    const res = await fetch("/api/production/plan/position", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) return null;
    return (await res.json()) as PlanBoard;
  } catch {
    return null;
  }
}

/** Удалить все ячейки позиции за год. true — успех. */
export async function deletePosition(year: number, product: string): Promise<boolean> {
  try {
    const res = await fetch(
      `/api/production/plan/position?year=${year}&product=${encodeURIComponent(product)}`,
      { method: "DELETE" },
    );
    return res.ok;
  } catch {
    return false;
  }
}
