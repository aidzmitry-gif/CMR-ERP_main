// Домен «Нормы и нормативы» производства поверх backend-API `/production/norms`.
// Чистые функции (формат н.ч, статусы, фильтр, счётчики) тестируются без React;
// SSR-загрузка ходит на BACKEND_URL, клиентские мутации — через прокси `/api`.

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export type NormKind = "product" | "operation";
export type NormStatus = "none" | "pending" | "approved";

export interface Norm {
  id: number;
  kind: NormKind;
  title: string;
  nh: number;
  status: NormStatus;
  note: string;
}

export interface NormInput {
  title: string;
  kind?: NormKind;
  nh?: number;
  note?: string;
}

const STATUS_LABELS: Record<NormStatus, string> = {
  none: "Нет нормы",
  pending: "На утверждении",
  approved: "Утверждена",
};

const KIND_LABELS: Record<NormKind, string> = {
  product: "Изделие",
  operation: "Операция",
};

export function normStatusLabel(status: NormStatus): string {
  return STATUS_LABELS[status] ?? status;
}

export function normKindLabel(kind: NormKind): string {
  return KIND_LABELS[kind] ?? kind;
}

/** Нормо-часы в русском формате: 10 → «10», 7.5 → «7,5», 0 → «—». */
export function formatNh(nh: number): string {
  if (!nh) return "—";
  const text = (Math.round(nh * 10) / 10).toFixed(1).replace(".", ",");
  return text.endsWith(",0") ? text.slice(0, -2) : text;
}

export function filterByKind(norms: Norm[], kind: NormKind): Norm[] {
  return norms.filter((n) => n.kind === kind);
}

export interface NormCounts {
  total: number;
  pending: number;
  none: number;
  approved: number;
}

export function normCounts(norms: Norm[]): NormCounts {
  return {
    total: norms.length,
    pending: norms.filter((n) => n.status === "pending").length,
    none: norms.filter((n) => n.status === "none").length,
    approved: norms.filter((n) => n.status === "approved").length,
  };
}

// ===== API =====

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

/** Справочник норм для SSR (server component); при недоступности бэка — пусто. */
export async function fetchNormsServer(roles?: string): Promise<Norm[]> {
  try {
    const res = await fetch(`${BASE}/production/norms`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return [];
    return (await res.json()) as Norm[];
  } catch {
    return [];
  }
}

/** Справочник норм (клиент, через прокси /api). */
export async function fetchNorms(kind?: NormKind): Promise<Norm[]> {
  try {
    const q = kind ? `?kind=${kind}` : "";
    const res = await fetch(`/api/production/norms${q}`, { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as Norm[];
  } catch {
    return [];
  }
}

export async function createNorm(input: NormInput): Promise<Norm | null> {
  try {
    const res = await fetch("/api/production/norms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return (await res.json()) as Norm;
  } catch {
    return null;
  }
}

export async function updateNorm(id: number, patch: Partial<NormInput>): Promise<Norm | null> {
  try {
    const res = await fetch(`/api/production/norms/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) return null;
    return (await res.json()) as Norm;
  } catch {
    return null;
  }
}

/** Утвердить норму. false — отказ бэка (напр. 409 для нормы без значения). */
export async function approveNorm(id: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/production/norms/${id}/approve`, { method: "POST" });
    return res.ok;
  } catch {
    return false;
  }
}

export async function deleteNorm(id: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/production/norms/${id}`, { method: "DELETE" });
    return res.ok;
  } catch {
    return false;
  }
}
