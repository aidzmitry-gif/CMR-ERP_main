// Домен «Спецификации · BOM» производства поверх backend-API `/production/boms`.
// Чистые функции (статусы, обеспеченность, счётчики) тестируются без React;
// SSR-загрузка ходит на BACKEND_URL, клиентские мутации — через прокси `/api`.

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export type BomStatus = "draft" | "approved";
export type ItemStatus = "ok" | "short";

export interface Bom {
  id: number;
  product: string;
  version: string;
  status: BomStatus;
  note: string;
  item_count: number;
  coverage: number; // % обеспеченных позиций
}

export interface BomItem {
  id: number;
  bom_id: number;
  component: string;
  norm_qty: number;
  unit: string;
  stock: number;
  reserved: number;
  status: ItemStatus; // ok | short — доступно ≥ норма
}

export interface BomDetail extends Bom {
  items: BomItem[];
}

export interface BomInput {
  product: string;
  version?: string;
  note?: string;
}

export interface BomItemInput {
  component: string;
  norm_qty?: number;
  unit?: string;
  stock?: number;
  reserved?: number;
}

const BOM_STATUS_LABELS: Record<BomStatus, string> = {
  draft: "Черновик",
  approved: "Утверждена",
};

const ITEM_STATUS_LABELS: Record<ItemStatus, string> = {
  ok: "В наличии",
  short: "Дефицит",
};

export function bomStatusLabel(status: BomStatus): string {
  return BOM_STATUS_LABELS[status] ?? status;
}

export function itemStatusLabel(status: ItemStatus): string {
  return ITEM_STATUS_LABELS[status] ?? status;
}

/** Доступное количество позиции: склад минус резерв (может быть < 0). */
export function available(item: Pick<BomItem, "stock" | "reserved">): number {
  return item.stock - item.reserved;
}

/** Тон бейджа обеспеченности по порогам: ≥100% — ok, ≥80% — warn, иначе — bad. */
export function coverageTone(pct: number): string {
  if (pct >= 100) return "bg-green-50 text-green-600";
  if (pct >= 80) return "bg-amber-50 text-amber-600";
  return "bg-red-50 text-red-600";
}

/** Количество дефицитных позиций в раскрытом составе. */
export function shortItemCount(items: BomItem[]): number {
  return items.filter((i) => i.status === "short").length;
}

export interface BomCounts {
  total: number;
  approved: number;
  draft: number;
}

export function bomCounts(boms: Bom[]): BomCounts {
  return {
    total: boms.length,
    approved: boms.filter((b) => b.status === "approved").length,
    draft: boms.filter((b) => b.status === "draft").length,
  };
}

// ===== API =====

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

/** Список спецификаций для SSR (server component); при недоступности бэка — пусто. */
export async function fetchBomsServer(roles?: string): Promise<Bom[]> {
  try {
    const res = await fetch(`${BASE}/production/boms`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return [];
    return (await res.json()) as Bom[];
  } catch {
    return [];
  }
}

/** Список спецификаций (клиент, через прокси /api). */
export async function fetchBoms(): Promise<Bom[]> {
  try {
    const res = await fetch("/api/production/boms", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as Bom[];
  } catch {
    return [];
  }
}

/** Спецификация с раскрытым составом (клиент). null — недоступна. */
export async function fetchBom(id: number): Promise<BomDetail | null> {
  try {
    const res = await fetch(`/api/production/boms/${id}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as BomDetail;
  } catch {
    return null;
  }
}

export async function createBom(input: BomInput): Promise<Bom | null> {
  try {
    const res = await fetch("/api/production/boms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return (await res.json()) as Bom;
  } catch {
    return null;
  }
}

export async function updateBom(id: number, patch: Partial<BomInput>): Promise<Bom | null> {
  try {
    const res = await fetch(`/api/production/boms/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) return null;
    return (await res.json()) as Bom;
  } catch {
    return null;
  }
}

/** Утвердить спецификацию. false — отказ бэка (напр. 409 для пустого состава). */
export async function approveBom(id: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/production/boms/${id}/approve`, { method: "POST" });
    return res.ok;
  } catch {
    return false;
  }
}

export async function deleteBom(id: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/production/boms/${id}`, { method: "DELETE" });
    return res.ok;
  } catch {
    return false;
  }
}

/** Добавить позицию в состав (возвращает BOM в draft на бэке). */
export async function addBomItem(bomId: number, input: BomItemInput): Promise<boolean> {
  try {
    const res = await fetch(`/api/production/boms/${bomId}/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function updateBomItem(id: number, patch: Partial<BomItemInput>): Promise<boolean> {
  try {
    const res = await fetch(`/api/production/bom-items/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function deleteBomItem(id: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/production/bom-items/${id}`, { method: "DELETE" });
    return res.ok;
  } catch {
    return false;
  }
}
