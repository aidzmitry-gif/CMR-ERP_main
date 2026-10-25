// Домен операционного склада поверх backend-API `/wms` (движения/операции/ячейки/остаток).
// Физические движения ERP. Полнота начальных остатков и сверка подтверждаются отдельно.

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export interface StockMovement {
  id: number;
  organization_id?: number | null;
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
  organization_id?: number;
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

export const REASON_LABELS: Record<string, string> = {
  receipt: "Приёмка",
  shipment: "Отгрузка",
  reserve: "Резерв",
  release: "Снятие резерва",
  transfer: "Перемещение",
  adjustment: "Коррекция",
  pick: "Подбор",
  pack: "Упаковка",
};

export function reasonLabel(reason: string): string {
  if (!reason) return "—";
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

export async function fetchMovementsServer(roles?: string, authHeaders?: Record<string, string>): Promise<StockMovement[]> {
  const res = await fetch(`${BASE}/wms/movements`, { cache: "no-store", headers: authHeaders ?? roleHeaders(roles) });
  if (!res.ok) throw new Error("Не удалось загрузить журнал движений");
  return (await res.json()) as StockMovement[];
}

export async function fetchBalancesServer(roles?: string, authHeaders?: Record<string, string>): Promise<Balances> {
  const res = await fetch(`${BASE}/wms/balances`, { cache: "no-store", headers: authHeaders ?? roleHeaders(roles) });
  if (!res.ok) throw new Error("Не удалось загрузить остатки");
  return (await res.json()) as Balances;
}

export async function fetchLocationsServer(roles?: string, authHeaders?: Record<string, string>): Promise<WmsLocation[]> {
  try {
    const res = await fetch(`${BASE}/wms/locations`, { cache: "no-store", headers: authHeaders ?? roleHeaders(roles) });
    if (!res.ok) return [];
    return (await res.json()) as WmsLocation[];
  } catch {
    return [];
  }
}

// ===== Клиент (через прокси /api) =====

const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

export async function fetchMovements(organizationId?: number): Promise<StockMovement[]> {
  if (organizationId !== undefined && (!Number.isSafeInteger(organizationId) || organizationId <= 0))
    throw new Error("Юрлицо движений не подтверждено");
  const scope = organizationId === undefined ? "" : `?organization_id=${organizationId}`;
  const res = await fetch(`/api/wms/movements${scope}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Не удалось загрузить журнал движений");
  const data: unknown = await res.json();
  if (organizationId !== undefined && (!Array.isArray(data) || data.some(row => !record(row)
    || row.organization_id !== organizationId || !Number.isSafeInteger(row.id) || Number(row.id) <= 0
    || typeof row.sku_code !== "string" || !row.sku_code.trim() || typeof row.warehouse !== "string" || !row.warehouse.trim()
    || !["in", "out"].includes(String(row.kind)) || typeof row.qty !== "number" || !Number.isFinite(row.qty) || row.qty <= 0
    || [row.reason, row.batch_ref, row.doc_ref, row.note].some(value => typeof value !== "string")
    || !(row.created_at === null || typeof row.created_at === "string")
    || !(row.location_id === null || (Number.isSafeInteger(row.location_id) && Number(row.location_id) > 0)))))
    throw new Error("Журнал вернул некорректные движения или другое юрлицо");
  return data as StockMovement[];
}

export async function fetchBalances(): Promise<Balances> {
  const res = await fetch("/api/wms/balances", { cache: "no-store" });
  if (!res.ok) throw new Error("Не удалось загрузить остатки");
  return (await res.json()) as Balances;
}

export async function fetchLocations(warehouse?: string): Promise<WmsLocation[]> {
  try {
    if (warehouse !== undefined && !warehouse.trim()) throw new Error("Выберите склад для загрузки ячеек");
    const scope = warehouse === undefined ? "" : `?warehouse=${encodeURIComponent(warehouse)}&active=true`;
    const res = await fetch(`/api/wms/locations${scope}`, { cache: "no-store" });
    if (!res.ok) throw new Error("Не удалось загрузить ячейки склада");
    const data: unknown = await res.json();
    if (warehouse !== undefined && (!Array.isArray(data) || data.some(row => !record(row)
      || row.warehouse !== warehouse || !Number.isSafeInteger(row.id) || Number(row.id) <= 0
      || typeof row.zone !== "string" || typeof row.code !== "string" || typeof row.title !== "string" || row.is_active !== true)))
      throw new Error("Сервис вернул некорректные ячейки или другой склад");
    return data as WmsLocation[];
  } catch (error) {
    if (warehouse !== undefined) throw error;
    return [];
  }
}

export type OperationWarehouse = {
  id: number; organization_id: number; name: string; title: string;
  is_active: boolean; wms_enabled: boolean; prohibit_negative_stock: boolean;
};
export type OperationWarehousePage = { organization_id: number; items: OperationWarehouse[]; truncated: boolean };

export async function fetchOperationWarehouses(organizationId: number, search = ""): Promise<OperationWarehousePage> {
  if (!Number.isSafeInteger(organizationId) || organizationId <= 0) throw new Error("Юрлицо складов не подтверждено");
  const response = await fetch(`/api/wms/organizations/${organizationId}/warehouse-options?q=${encodeURIComponent(search.trim())}`,
    { cache: "no-store" });
  if (!response.ok) throw new Error("Не удалось загрузить справочник складов");
  const data: unknown = await response.json();
  if (!record(data) || data.organization_id !== organizationId || !Array.isArray(data.items)
    || data.items.length > 50 || typeof data.truncated !== "boolean" || data.items.some(row => !record(row)
      || !Number.isSafeInteger(row.id) || Number(row.id) <= 0 || row.organization_id !== organizationId
      || typeof row.name !== "string" || !row.name.trim() || typeof row.title !== "string" || !row.title.trim()
      || row.is_active !== true || typeof row.wms_enabled !== "boolean" || typeof row.prohibit_negative_stock !== "boolean")
    || new Set(data.items.map(row => row.id)).size !== data.items.length
    || new Set(data.items.map(row => row.name)).size !== data.items.length)
    throw new Error("Справочник вернул некорректные склады или другое юрлицо");
  return data as OperationWarehousePage;
}

export interface OpInput {
  organization_id: number;
  sku_code: string;
  qty: number;
  warehouse: string;
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

export const shipment = (i: OpInput) => postOp("shipment", i);
export const adjustment = (i: OpInput) => postOp("adjustment", i);
export const transfer = (i: {
  organization_id: number;
  sku_code: string;
  qty: number;
  warehouse: string;
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
