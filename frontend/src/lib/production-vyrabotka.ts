// Домен «Выработка и оценка» поверх backend-API `/production/workers` и `/production/payroll`.
// Расчёт ЗП делает бэкенд (оклад × дни/22 + выработка н.ч × 6,25 BYN); фронт отображает.

import { formatNh } from "@/lib/production-norms";

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

export { formatNh };

export interface Worker {
  id: number;
  name: string;
  salary: number;
  days_worked: number;
  nh_output: number;
}

export interface WorkerInput {
  name: string;
  salary?: number;
  days_worked?: number;
  nh_output?: number;
}

export interface PayrollRow {
  id: number;
  name: string;
  nh_output: number;
  base: number;        // оклад × дни / 22
  premium: number;     // выработка × 6,25
  total: number;       // base + premium
  contribution: number;  // стоимость выработки (для рейтинга вклада)
}

export interface Payroll {
  rows: PayrollRow[];  // отсортированы по вкладу (лидеры первыми)
  total_nh: number;
  total_base: number;
  total_premium: number;
  total_payroll: number;
}

const EMPTY_PAYROLL: Payroll = {
  rows: [],
  total_nh: 0,
  total_base: 0,
  total_premium: 0,
  total_payroll: 0,
};

/** Сумма в BYN, русский формат: 910 → «910 BYN», 910.5 → «910,5 BYN». */
export function formatByn(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  const text = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(rounded);
  return `${text} BYN`;
}

/** Доля вклада сборщика в общую стоимость выработки, %. */
export function contributionShare(row: PayrollRow, totalContribution: number): number {
  if (!totalContribution) return 0;
  return Math.round((row.contribution / totalContribution) * 1000) / 10;
}

export function totalContribution(rows: PayrollRow[]): number {
  return rows.reduce((sum, r) => sum + r.contribution, 0);
}

// ===== API =====

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

export async function fetchPayrollServer(roles?: string): Promise<Payroll> {
  try {
    const res = await fetch(`${BASE}/production/payroll`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return EMPTY_PAYROLL;
    return (await res.json()) as Payroll;
  } catch {
    return EMPTY_PAYROLL;
  }
}

export async function fetchPayroll(): Promise<Payroll> {
  try {
    const res = await fetch("/api/production/payroll", { cache: "no-store" });
    if (!res.ok) return EMPTY_PAYROLL;
    return (await res.json()) as Payroll;
  } catch {
    return EMPTY_PAYROLL;
  }
}

export async function fetchWorkers(): Promise<Worker[]> {
  try {
    const res = await fetch("/api/production/workers", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as Worker[];
  } catch {
    return [];
  }
}

export async function createWorker(input: WorkerInput): Promise<Worker | null> {
  try {
    const res = await fetch("/api/production/workers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return (await res.json()) as Worker;
  } catch {
    return null;
  }
}

export async function updateWorker(
  id: number,
  patch: Partial<WorkerInput>,
): Promise<Worker | null> {
  try {
    const res = await fetch(`/api/production/workers/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) return null;
    return (await res.json()) as Worker;
  } catch {
    return null;
  }
}
