// Домен «Инвентаризация» поверх backend-API `/wms/inventory`.
// Документ читает ожидаемое из 1С (через шлюз), фиксирует факт пересчёта и расхождение.
// WMS НЕ источник истины остатка (1С — истина, фаза 1): в 1С не пишем.
// Чистые функции (статусы, тон расхождения) тестируются без React.

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

export type InventoryStatus = "open" | "done" | "canceled";

export interface InventoryCount {
  id: number;
  number: string;
  warehouse: string;
  status: InventoryStatus;
  note: string;
  created_at: string | null;
  completed_at: string | null;
}

export interface InventoryLine {
  id: number;
  sku_code: string;
  sku_title: string;
  unit: string;
  expected_qty: number;
  counted_qty: number | null;
  unit_cost: number | null;
  variance: number | null; // факт − ожидаемое
  variance_value: number | null; // variance × себес (деньги)
  note: string;
}

export interface InventorySummary {
  lines: number;
  counted: number;
  shortages: number;
  surpluses: number;
  shortage_value: number;
  surplus_value: number;
  net_value: number;
}

export interface InventoryDetail extends InventoryCount {
  lines: InventoryLine[];
  summary: InventorySummary;
}

const STATUS_LABELS: Record<InventoryStatus, string> = {
  open: "Идёт пересчёт",
  done: "Проведена",
  canceled: "Отменена",
};

export function inventoryStatusLabel(status: InventoryStatus): string {
  return STATUS_LABELS[status] ?? status;
}

/** Тон строки по расхождению: недостача (red) / излишек (amber) / совпало (green) / нет факта. */
export function varianceTone(variance: number | null): "none" | "ok" | "short" | "over" {
  if (variance === null) return "none";
  if (variance < 0) return "short";
  if (variance > 0) return "over";
  return "ok";
}

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

// ===== SSR (server components) =====

export async function fetchInventoryListServer(roles?: string): Promise<InventoryCount[]> {
  try {
    const res = await fetch(`${BASE}/wms/inventory`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return [];
    return (await res.json()) as InventoryCount[];
  } catch {
    return [];
  }
}

export async function fetchInventoryDetailServer(
  id: string,
  roles?: string,
): Promise<InventoryDetail | null> {
  try {
    const res = await fetch(`${BASE}/wms/inventory/${id}`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return null;
    return (await res.json()) as InventoryDetail;
  } catch {
    return null;
  }
}

// ===== Клиент (через прокси /api) =====

export async function createInventory(warehouse: string, note = ""): Promise<InventoryCount | null> {
  try {
    const res = await fetch("/api/wms/inventory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ warehouse, note }),
    });
    if (!res.ok) return null;
    return (await res.json()) as InventoryCount;
  } catch {
    return null;
  }
}

export async function fetchInventoryDetail(id: number): Promise<InventoryDetail | null> {
  try {
    const res = await fetch(`/api/wms/inventory/${id}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as InventoryDetail;
  } catch {
    return null;
  }
}

/** Заполнить документ ожидаемыми остатками склада из 1С. Возвращает обновлённый detail. */
export async function populateInventory(id: number): Promise<InventoryDetail | null> {
  try {
    const res = await fetch(`/api/wms/inventory/${id}/populate`, { method: "POST" });
    if (!res.ok) return null;
    return (await res.json()) as InventoryDetail;
  } catch {
    return null;
  }
}

export async function updateInventoryLine(
  lineId: number,
  patch: { counted_qty?: number | null; note?: string },
): Promise<boolean> {
  try {
    const res = await fetch(`/api/wms/inventory/lines/${lineId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function addInventoryLine(
  id: number,
  skuCode: string,
  countedQty?: number,
): Promise<boolean> {
  try {
    const res = await fetch(`/api/wms/inventory/${id}/lines`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sku_code: skuCode, counted_qty: countedQty ?? null }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function completeInventory(id: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/wms/inventory/${id}/complete`, { method: "POST" });
    return res.ok;
  } catch {
    return false;
  }
}
