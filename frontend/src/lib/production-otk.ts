// Домен «ОТК · контроль качества» поверх backend-API `/production/qc/*`.
// Решения accept|rework|scrap; брак на бэке публикует production.scrap (претензия в закупки).

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export type QcDecision = "accept" | "rework" | "scrap";

export interface QcRecord {
  id: number;
  order_code: string;
  product: string;
  decision: QcDecision;
  reason: string;
  inspector: string;
}

export interface QcInput {
  decision: QcDecision;
  order_code?: string;
  product?: string;
  reason?: string;
  inspector?: string;
}

export interface QcStats {
  accepted: number;
  rework: number;
  scrap: number;
  total: number;
  pass_rate: number;
}

const EMPTY_STATS: QcStats = { accepted: 0, rework: 0, scrap: 0, total: 0, pass_rate: 0 };

const DECISION_LABELS: Record<QcDecision, string> = {
  accept: "Принять",
  rework: "Доработка",
  scrap: "Брак",
};

export function decisionLabel(decision: QcDecision): string {
  return DECISION_LABELS[decision] ?? decision;
}

// Преднабор причин доработки/брака (как на экране-прототипе ОТК).
export const REWORK_REASONS: string[] = [
  "Пайка БМС · непропай / перемычка",
  "Сварной шов · прожог / отрыв",
  "Не держит ёмкость · повторный прогон",
  "Разброс ячеек · балансировка",
  "Корпус / крышка · зазор, клей",
  "Маркировка · этикетка / паспорт",
];

/** Pass-rate в проценты с запятой: 96 → «96%», 95.5 → «95,5%». */
export function formatPassRate(value: number): string {
  return `${String(value).replace(".", ",")}%`;
}

// ===== API =====

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

export async function fetchDecisionsServer(roles?: string): Promise<QcRecord[]> {
  try {
    const res = await fetch(`${BASE}/production/qc/decisions`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return [];
    return (await res.json()) as QcRecord[];
  } catch {
    return [];
  }
}

export async function fetchStatsServer(roles?: string): Promise<QcStats> {
  try {
    const res = await fetch(`${BASE}/production/qc/stats`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return EMPTY_STATS;
    return (await res.json()) as QcStats;
  } catch {
    return EMPTY_STATS;
  }
}

export async function fetchDecisions(): Promise<QcRecord[]> {
  try {
    const res = await fetch("/api/production/qc/decisions", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as QcRecord[];
  } catch {
    return [];
  }
}

export async function fetchStats(): Promise<QcStats> {
  try {
    const res = await fetch("/api/production/qc/stats", { cache: "no-store" });
    if (!res.ok) return EMPTY_STATS;
    return (await res.json()) as QcStats;
  } catch {
    return EMPTY_STATS;
  }
}

export async function createDecision(input: QcInput): Promise<QcRecord | null> {
  try {
    const res = await fetch("/api/production/qc/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return (await res.json()) as QcRecord;
  } catch {
    return null;
  }
}
