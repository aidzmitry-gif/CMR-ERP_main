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
  organization_id: number;
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
  return locationRows(await locationRequest(`${BASE}/wms/locations`, { cache: "no-store", headers: authHeaders ?? roleHeaders(roles) }));
}

// ===== Клиент (через прокси /api) =====

export async function fetchMovements(): Promise<StockMovement[]> {
  const res = await fetch("/api/wms/movements", { cache: "no-store" });
  if (!res.ok) throw new Error("Не удалось загрузить журнал движений");
  return (await res.json()) as StockMovement[];
}

export async function fetchBalances(): Promise<Balances> {
  const res = await fetch("/api/wms/balances", { cache: "no-store" });
  if (!res.ok) throw new Error("Не удалось загрузить остатки");
  return (await res.json()) as Balances;
}

export async function fetchLocations(organizationId?: number): Promise<WmsLocation[]> {
  const query = organizationId == null ? "" : `?organization_id=${positiveId(organizationId)}`;
  const rows = locationRows(await locationRequest(`/api/wms/locations${query}`, { cache: "no-store" }));
  if (organizationId != null && rows.some((row) => row.organization_id !== organizationId)) throw invalidLocations();
  return rows;
}

export class LocationRequestError extends Error {
  constructor(message: string, public readonly status: number | null = null, public readonly resultUnknown = false) {
    super(message);
    this.name = "LocationRequestError";
  }
}

const invalidLocations = () => new LocationRequestError("Не удалось подтвердить данные ячеек. Обновите список.");

function positiveId(value: number): number {
  if (!Number.isSafeInteger(value) || value <= 0) throw invalidLocations();
  return value;
}

function isLocation(value: unknown): value is WmsLocation {
  if (!value || typeof value !== "object") return false;
  const row = value as WmsLocation;
  return Number.isSafeInteger(row.id) && row.id > 0 && Number.isSafeInteger(row.organization_id) && row.organization_id > 0
    && typeof row.warehouse === "string" && !!row.warehouse.trim() && typeof row.code === "string" && !!row.code.trim()
    && typeof row.zone === "string" && typeof row.title === "string" && typeof row.is_active === "boolean";
}

function locationRows(value: unknown): WmsLocation[] {
  if (!Array.isArray(value) || !value.every(isLocation)) throw invalidLocations();
  return value;
}

async function locationRequest(url: string, options: RequestInit): Promise<unknown> {
  const write = options.method === "POST";
  let res: Response;
  try {
    res = await fetch(url, options);
  } catch {
    throw new LocationRequestError(write ? "Результат сохранения неизвестен. Обновите список и проверьте ячейку перед повтором." : "Не удалось загрузить данные. Проверьте соединение и повторите загрузку.", null, write);
  }
  if (!res.ok) {
    const message = res.status === 401 ? "Сессия истекла. Войдите в ERP заново."
      : res.status === 403 ? "Нет доступа к выбранной компании или операции."
        : res.status === 404 ? "Ячейка не найдена."
          : res.status === 422 || res.status === 409 ? "Операция отклонена. Проверьте компанию, склад и поля ячейки."
            : write ? "Результат сохранения неизвестен. Обновите список и проверьте ячейку перед повтором." : "Не удалось загрузить данные ячеек. Повторите загрузку.";
    throw new LocationRequestError(message, res.status, write && res.status >= 500);
  }
  try {
    return await res.json();
  } catch {
    throw new LocationRequestError(write ? "Результат сохранения неизвестен. Обновите список перед повтором." : "Не удалось прочитать данные ячеек.", res.status, write);
  }
}

export interface LocationOrganization { id: number; name: string }

export async function fetchLocationOrganizations(authHeaders?: Record<string, string>): Promise<LocationOrganization[]> {
  const url = authHeaders ? `${BASE}/wms/receipt-organizations` : "/api/wms/receipt-organizations";
  const data = await locationRequest(url, { cache: "no-store", ...(authHeaders ? { headers: authHeaders } : {}) });
  if (!Array.isArray(data) || !data.every((row) => row && Number.isSafeInteger(row.id) && row.id > 0 && typeof row.name === "string" && row.name.trim())) throw invalidLocations();
  return data;
}

export async function fetchLocation(id: number): Promise<WmsLocation | null> {
  try {
    const row = await locationRequest(`/api/wms/locations/${positiveId(id)}`, { cache: "no-store" });
    if (!isLocation(row) || row.id !== id) throw invalidLocations();
    return row;
  } catch (error) {
    if (error instanceof LocationRequestError && error.status === 404) return null;
    throw error;
  }
}

export async function fetchLocationWarehouses(organizationId: number, term = ""): Promise<{ items: { organization_id: number; name: string }[]; truncated: boolean }> {
  const data = await locationRequest(`/api/wms/organizations/${positiveId(organizationId)}/warehouse-options?q=${encodeURIComponent(term.trim())}`, { cache: "no-store" }) as { organization_id?: number; items?: { organization_id: number; name: string }[]; truncated?: boolean };
  if (!data || data.organization_id !== organizationId || !Array.isArray(data.items) || typeof data.truncated !== "boolean"
    || !data.items.every((row) => row.organization_id === organizationId && typeof row.name === "string" && row.name.trim())) throw invalidLocations();
  return { items: data.items, truncated: data.truncated };
}

export interface OpInput {
  organization_id: number;
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

export const shipment = (i: OpInput) => postOp("shipment", i);
export const adjustment = (i: OpInput) => postOp("adjustment", i);
export const transfer = (i: {
  organization_id: number;
  sku_code: string;
  qty: number;
  warehouse?: string;
  from_location_id?: number | null;
  to_location_id?: number | null;
  batch_ref?: string;
  note?: string;
}) => postOp("transfer", i);

export async function createLocation(i: {
  organization_id: number;
  warehouse: string;
  zone?: string;
  code: string;
  title?: string;
}): Promise<WmsLocation> {
  positiveId(i.organization_id);
  if (!i.warehouse.trim() || !i.code.trim()) throw invalidLocations();
  const row = await locationRequest("/api/wms/locations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(i) });
  if (!isLocation(row) || row.organization_id !== i.organization_id || row.warehouse !== i.warehouse || row.code !== i.code) {
    throw new LocationRequestError("Результат сохранения неизвестен. Обновите список перед повтором.", null, true);
  }
  return row;
}
