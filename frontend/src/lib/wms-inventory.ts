const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export type InventoryStatus = "open" | "done" | "canceled";

export interface InventoryProvenance {
  organization_id: number | null;
  expected_source: string | null;
  source_evidence: string | null;
  journal_confirmed_by: string | null;
  journal_confirmed_at: string | null;
}

export interface InventoryConfirmation {
  expected_source: "wms_physical";
  source_evidence: string;
  journal_complete: true;
}

export interface InventoryCreate extends InventoryConfirmation {
  organization_id: number;
  warehouse: string;
  note?: string;
}

export interface InventoryOrganization { id: number; name: string; unp: string }

export interface InventoryCount extends InventoryProvenance {
  snapshot_version: string | null;
  snapshot_cutoff: number | null;
  snapshot_at: string | null;
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
  shortage_value: number | null;
  surplus_value: number | null;
  net_value: number | null;
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

export class InventoryRequestError extends Error {
  constructor(message: string, public readonly status: number | null = null) {
    super(message);
    this.name = "InventoryRequestError";
  }
}

export function inventoryErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Не удалось выполнить запрос. Повторите попытку.";
}

export async function inventoryRequest<T>(url: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new InventoryRequestError("Ошибка сети. Результат запроса неизвестен; обновите документ перед повтором.");
  }
  if (!response.ok) {
    const labels: Record<number, string> = {
      403: "Нет доступа к юрлицу.",
      404: "Документ не найден.",
      409: "Операция отклонена: проверьте документ и снимок; при изменении журнала создайте новый пересчёт.",
      422: "Проверьте заполнение полей.",
      503: "Сервис временно недоступен. Повторите запрос позже.",
    };
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? ` ${body.detail}` : "";
    throw new InventoryRequestError((labels[response.status] ?? `Ошибка запроса (${response.status}).`) + detail, response.status);
  }
  try { return await response.json() as T; }
  catch { throw new InventoryRequestError("Сервис вернул некорректный ответ. Обновите документ."); }
}

export function inventoryJson(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export function organizationQuery(organizationId?: number | null): string {
  return organizationId == null ? "" : `?organization_id=${organizationId}`;
}

export function fetchInventoryOrganizationsServer(headers: Record<string, string>) {
  return inventoryRequest<InventoryOrganization[]>(`${BASE}/wms/receipt-organizations`, { cache: "no-store", headers });
}

export function fetchInventoryListServer(headers: Record<string, string>, organizationId?: number | null) {
  return inventoryRequest<InventoryCount[]>(`${BASE}/wms/inventory${organizationQuery(organizationId)}`, { cache: "no-store", headers });
}

export function fetchInventoryDetailServer(id: string, headers: Record<string, string>) {
  return inventoryRequest<InventoryDetail>(`${BASE}/wms/inventory/${encodeURIComponent(id)}`, { cache: "no-store", headers });
}

export function fetchInventoryList(organizationId: number) {
  return inventoryRequest<InventoryCount[]>(`/api/wms/inventory${organizationQuery(organizationId)}`, { cache: "no-store" });
}

export function createInventory(input: InventoryCreate) {
  return inventoryRequest<InventoryCount>("/api/wms/inventory", inventoryJson("POST", input));
}

export function fetchInventoryDetail(id: number) {
  return inventoryRequest<InventoryDetail>(`/api/wms/inventory/${id}`, { cache: "no-store" });
}

export function populateInventory(id: number) {
  return inventoryRequest<InventoryDetail>(`/api/wms/inventory/${id}/populate`, { method: "POST" });
}

export function updateInventoryLine(lineId: number, patch: { counted_qty?: number; note?: string }) {
  return inventoryRequest<InventoryLine>(`/api/wms/inventory/lines/${lineId}`, inventoryJson("PATCH", patch));
}

export function addInventoryLine(id: number, skuCode: string, countedQty?: number) {
  return inventoryRequest<InventoryLine>(`/api/wms/inventory/${id}/lines`, inventoryJson("POST", { sku_code: skuCode, counted_qty: countedQty }));
}

export function completeInventory(id: number) {
  return inventoryRequest<InventoryCount>(`/api/wms/inventory/${id}/complete`, { method: "POST" });
}
