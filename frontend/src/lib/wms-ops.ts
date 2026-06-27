// Домен операционного склада поверх backend-API `/wms` (движения/операции/ячейки/остаток).
// 🔴 WMS НЕ источник истины остатка: 1С — истина, журнал ДУБЛИРУЕТ движения; оперативный
// остаток = знаковая сумма (in − out), его СВЕРЯЮТ с 1С. Чистые функции тестируются без React.

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

export interface StockMovement {
  id: number;
  sku_code: string;
  warehouse: string;
  kind: "in" | "out";
  qty: number;
  reason: string;
  location_id: number | null;
  batch_ref: string;
  doc_ref: string;
  note: string;
  created_at: string | null;
}

export interface WmsLocation {
  id: number;
  warehouse: string;
  zone: string;
  code: string;
  title: string;
  is_active: boolean;
}

export interface BalanceRow {
  sku_code: string;
  sku_title: string;
  warehouse: string;
  location_id: number | null;
  location_code: string;
  batch_ref: string;
  qty: number;
}

export interface Balances {
  rows: BalanceRow[];
  sku_count: number;
}

const REASON_LABELS: Record<string, string> = {
  receipt: "Приёмка",
  shipment: "Отгрузка",
  reserve: "Резерв",
  release: "Снятие резерва",
  transfer: "Перемещение",
  adjustment: "Коррекция",
  "": "—",
};

export function reasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason;
}

/** Подпись адреса хранения: «зона · код» / только код / «—». */
export function locationLabel(loc: Pick<WmsLocation, "zone" | "code">): string {
  if (!loc.code) return "—";
  return loc.zone ? `${loc.zone} · ${loc.code}` : loc.code;
}

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

// ===== SSR =====

export async function fetchMovementsServer(roles?: string): Promise<StockMovement[]> {
  try {
    const res = await fetch(`${BASE}/wms/movements`, { cache: "no-store", headers: roleHeaders(roles) });
    if (!res.ok) return [];
    return (await res.json()) as StockMovement[];
  } catch {
    return [];
  }
}

export async function fetchBalancesServer(roles?: string): Promise<Balances> {
  try {
    const res = await fetch(`${BASE}/wms/balances`, { cache: "no-store", headers: roleHeaders(roles) });
    if (!res.ok) return { rows: [], sku_count: 0 };
    return (await res.json()) as Balances;
  } catch {
    return { rows: [], sku_count: 0 };
  }
}

export async function fetchLocationsServer(roles?: string): Promise<WmsLocation[]> {
  try {
    const res = await fetch(`${BASE}/wms/locations`, { cache: "no-store", headers: roleHeaders(roles) });
    if (!res.ok) return [];
    return (await res.json()) as WmsLocation[];
  } catch {
    return [];
  }
}

// ===== Клиент (через прокси /api) =====

export async function fetchMovements(): Promise<StockMovement[]> {
  try {
    const res = await fetch("/api/wms/movements", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as StockMovement[];
  } catch {
    return [];
  }
}

export async function fetchBalances(): Promise<Balances> {
  try {
    const res = await fetch("/api/wms/balances", { cache: "no-store" });
    if (!res.ok) return { rows: [], sku_count: 0 };
    return (await res.json()) as Balances;
  } catch {
    return { rows: [], sku_count: 0 };
  }
}

export async function fetchLocations(): Promise<WmsLocation[]> {
  try {
    const res = await fetch("/api/wms/locations", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as WmsLocation[];
  } catch {
    return [];
  }
}

export interface OpInput {
  sku_code: string;
  qty: number;
  warehouse?: string;
  location_id?: number | null;
  batch_ref?: string;
  note?: string;
}

async function postOp(path: string, body: unknown): Promise<boolean> {
  try {
    const res = await fetch(`/api/wms/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export const receipt = (i: OpInput) => postOp("receipt", i);
export const shipment = (i: OpInput) => postOp("shipment", i);
export const adjustment = (i: OpInput) => postOp("adjustment", i);
export const transfer = (i: {
  sku_code: string;
  qty: number;
  warehouse?: string;
  from_location_id?: number | null;
  to_location_id?: number | null;
  batch_ref?: string;
  note?: string;
}) => postOp("transfer", i);

export async function createLocation(i: {
  warehouse: string;
  zone?: string;
  code: string;
  title?: string;
}): Promise<boolean> {
  return postOp("locations", i);
}
