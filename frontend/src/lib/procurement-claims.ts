// Домен «Претензии поставщикам» закупок поверх backend-API `/procurement/claims`.
// Претензии открываются автоматически при браке в производстве (production.scrap);
// закупщик назначает поставщика и закрывает их. Чистые функции тестируются без React;
// SSR — на BACKEND_URL, клиентские мутации — через прокси `/api`.

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export type ClaimStatus = "open" | "resolved" | "rejected";

export interface Claim {
  id: number;
  supplier: string;
  supplier_id: number | null;
  item: string;
  reason: string;
  order_code: string;
  claim_type: string; // брак / недопоставка / пересорт / срок
  qty_affected: number;
  amount_byn: number | null;
  resolution: string;
  status: ClaimStatus;
  source: string;
  entity_ref: string;
}

export interface ClaimPatch {
  supplier?: string;
  supplier_id?: number | null;
  status?: ClaimStatus;
  resolution?: string;
}

export interface ClaimInput {
  supplier?: string;
  supplier_id?: number | null;
  item?: string;
  reason?: string;
  order_code?: string;
  claim_type?: string;
  qty_affected?: number;
  amount_byn?: number | null;
}

/** Типы претензий (для фильтра/формы). Свободные значения — лейбл совпадает со значением. */
export const CLAIM_TYPES = ["брак", "недопоставка", "пересорт", "срок"] as const;

export function claimTypeLabel(t: string): string {
  return t || "—";
}

const STATUS_LABELS: Record<ClaimStatus, string> = {
  open: "Открыта",
  resolved: "Решена",
  rejected: "Отклонена",
};

const STATUS_TONES: Record<ClaimStatus, string> = {
  open: "bg-amber-50 text-amber-600",
  resolved: "bg-green-50 text-green-600",
  rejected: "bg-slate-100 text-slate-500",
};

export function claimStatusLabel(status: ClaimStatus): string {
  return STATUS_LABELS[status] ?? status;
}

export function claimStatusTone(status: ClaimStatus): string {
  return STATUS_TONES[status] ?? "bg-slate-100 text-slate-500";
}

/** Источник претензии: `production` — брак на сборке (автопретензия из ОТК). */
export function sourceLabel(source: string): string {
  return source === "production" ? "Брак производства" : source || "—";
}

export interface ClaimCounts {
  total: number;
  open: number;
  resolved: number;
  withoutSupplier: number; // открытые без назначенного поставщика
}

export function claimCounts(claims: Claim[]): ClaimCounts {
  return {
    total: claims.length,
    open: claims.filter((c) => c.status === "open").length,
    resolved: claims.filter((c) => c.status === "resolved").length,
    withoutSupplier: claims.filter((c) => c.status === "open" && !c.supplier.trim()).length,
  };
}

// ===== API =====

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

/** Претензии для SSR (server component); при недоступности бэка — пусто. */
export async function fetchClaimsServer(roles?: string): Promise<Claim[]> {
  try {
    const res = await fetch(`${BASE}/procurement/claims`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return [];
    return (await res.json()) as Claim[];
  } catch {
    return [];
  }
}

/** Претензии (клиент, через прокси /api). */
export async function fetchClaims(): Promise<Claim[]> {
  try {
    const res = await fetch("/api/procurement/claims", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as Claim[];
  } catch {
    return [];
  }
}

/** Назначить поставщика / урегулировать претензию. null — отказ бэка. */
export async function updateClaim(id: number, patch: ClaimPatch): Promise<Claim | null> {
  try {
    const res = await fetch(`/api/procurement/claims/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) return null;
    return (await res.json()) as Claim;
  } catch {
    return null;
  }
}

/** Завести претензию вручную (закупщик). null — отказ бэка. */
export async function createClaim(input: ClaimInput): Promise<Claim | null> {
  try {
    const res = await fetch("/api/procurement/claims", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return (await res.json()) as Claim;
  } catch {
    return null;
  }
}

/** Фильтр претензий по статусу/типу/строке (для UI). */
export function filterClaims(
  claims: Claim[],
  opts: { status?: ClaimStatus | "all"; type?: string; query?: string },
): Claim[] {
  const q = (opts.query ?? "").trim().toLowerCase();
  return claims.filter((c) => {
    if (opts.status && opts.status !== "all" && c.status !== opts.status) return false;
    if (opts.type && opts.type !== "all" && c.claim_type !== opts.type) return false;
    if (!q) return true;
    return (
      c.item.toLowerCase().includes(q) ||
      c.order_code.toLowerCase().includes(q) ||
      c.supplier.toLowerCase().includes(q)
    );
  });
}
