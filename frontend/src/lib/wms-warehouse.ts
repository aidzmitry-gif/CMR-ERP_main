// Домен операционного склада (приёмка/QC, задачи, сверка, low-stock, цикл-каунт, дашборд)
// поверх backend-API `/wms`. 🔴 1С = истина остатка; WMS дублирует движения и читает 1С
// через шлюз. Чистые функции (лейблы/severity) тестируются без React.

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

// ---- Типы ----
export interface ReceiptLine {
  id: number;
  sku_code: string;
  sku_title: string;
  expected_qty: number;
  accepted_qty: number | null;
  rejected_qty: number | null;
  reject_reason: string;
  location_id: number | null;
  batch_ref: string;
}
export interface Receipt {
  id: number;
  number: string;
  source: string;
  entity_ref: string;
  warehouse: string;
  status: string; // pending_qc | accepted | rejected | putaway_done
  counterparty: string;
  created_at: string | null;
  decided_at: string | null;
  decided_by: string;
}
export interface ReceiptDetail extends Receipt {
  qc_revision: string;
  lines: ReceiptLine[];
}

export interface WmsTask {
  id: number;
  organization_id?: number | null;
  kind: string; // putaway | pick
  status: string; // open | in_progress | done | canceled
  sku_code: string;
  qty: number;
  warehouse: string;
  from_location_id: number | null;
  to_location_id: number | null;
  doc_ref: string;
  assignee: string;
  priority: string;
  note: string;
  created_at: string | null;
  done_at: string | null;
}

export interface ReconRow {
  sku_code: string;
  title: string;
  warehouse: string;
  wms_qty: number;
  onec_qty: number | null;
  diff: number | null;
  diff_value: number | null;
}
export interface Reconciliation {
  organization_id: number;
  rows: ReconRow[];
  gateway: boolean;
  total_abs_diff_value: number | null;
  source_unavailable_reason: "organization_stock_source_unverified" | "stock_gateway_unavailable" | null;
}

export interface AlertRow {
  sku_code: string;
  title: string;
  warehouse: string;
  free_qty: number;
  min_qty: number;
  deficit: number;
  reorder_qty: number;
  severity: string; // out_of_stock | below_min
}
export interface Alerts {
  rows: AlertRow[];
  gateway: boolean;
}

export interface StockThreshold {
  sku_code: string;
  warehouse: string;
  min_qty: number;
  active: boolean;
}

export interface CyclePlan {
  id: number;
  warehouse: string;
  zone: string | null;
  cadence_days: number;
  next_due_date: string | null;
  last_run_at: string | null;
  active: boolean;
  abc_class: string | null;
}

export interface Dashboard {
  organization_id: number;
  report_date: string;
  period_start: string;
  period_end: string;
  period_basis: "stored_registration_date";
  receipts_pending_qc: number;
  tasks_putaway_open: number;
  tasks_pick_open: number;
  inventories_open: number;
  movement_rows_today_in: number;
  movement_rows_today_out: number;
  alerts_count: number | null;
  alerts_deficit_value: number | null;
  inventory_value: number | null;
  recon_max_diff_value: number | null;
  recon_total_diff_value: number | null;
  valuation_unavailable_reason: "organization_valuation_unavailable" | null;
  movements_today_in: number | null;
  movements_today_out: number | null;
  quantity_unavailable_reason: "unit_snapshot_unavailable";
  gateway: boolean;
}

// ---- Чистые помощники (тестируются) ----
const SEVERITY_LABELS: Record<string, string> = {
  out_of_stock: "Нет в наличии",
  below_min: "Ниже минимума",
};
export function severityLabel(s: string): string {
  return SEVERITY_LABELS[s] ?? s;
}

const TASK_KIND_LABELS: Record<string, string> = { putaway: "Размещение", pick: "Подбор" };
export function taskKindLabel(k: string): string {
  return TASK_KIND_LABELS[k] ?? k;
}

const TASK_STATUS_LABELS: Record<string, string> = {
  open: "Открыта",
  in_progress: "В работе",
  done: "Выполнена",
  canceled: "Отменена",
};
export function taskStatusLabel(s: string): string {
  return TASK_STATUS_LABELS[s] ?? s;
}

const RECEIPT_STATUS_LABELS: Record<string, string> = {
  pending_qc: "Ожидает QC",
  accepted: "Принято",
  rejected: "Отклонено",
  putaway_done: "Размещено",
};
export function receiptStatusLabel(s: string): string {
  return RECEIPT_STATUS_LABELS[s] ?? s;
}

/** Состояние срока плана цикл-каунта по дате (для бейджа «просрочено/сегодня/предстоит»). */
export function dueState(nextDue: string | null, todayIso: string): "overdue" | "today" | "upcoming" | "none" {
  if (!nextDue) return "none";
  if (nextDue < todayIso) return "overdue";
  if (nextDue === todayIso) return "today";
  return "upcoming";
}

/** Русский плюрал для «позиция» (1 позиция / 2 позиции / 5 позиций). */
function pluralPositions(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "позиция";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "позиции";
  return "позиций";
}

/** Текст тоста об успешной отправке сигнала дозаказа в закупки (WMS-R3-2). */
export function alertsEmitMessage(n: number): string {
  return `Сигнал отправлен в закупки, ${n} ${pluralPositions(n)}`;
}

/** Можно ли слать сигнал: шлюз 1С подключён и есть нарушенные пороги (иначе кнопка disabled). */
export function canEmitAlerts(a: Alerts): boolean {
  return a.gateway && a.rows.length > 0;
}

// ---- Fetch helpers ----
function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}
async function ssr<T>(path: string, roles: string | undefined, fallback: T, authHeaders?: Record<string, string>): Promise<T> {
  try {
    const res = await fetch(`${BASE}${path}`, { cache: "no-store", headers: authHeaders ?? roleHeaders(roles) });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}
async function api<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`/api${path}`, { cache: "no-store" });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}
async function post(path: string, body?: unknown): Promise<boolean> {
  try {
    const res = await fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ---- SSR ----
const dashboardRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

/** A service connection cannot qualify company ownership or replace unknown figures with zero. */
function parseDashboard(data: unknown, organizationId: number): Dashboard | null {
  if (!dashboardRecord(data) || data.organization_id !== organizationId || typeof data.gateway !== "boolean") return null;
  const counters = ["receipts_pending_qc", "tasks_putaway_open", "tasks_pick_open", "inventories_open",
    "movement_rows_today_in", "movement_rows_today_out"];
  if (counters.some(key => !Number.isSafeInteger(data[key]) || Number(data[key]) < 0)) return null;
  if (typeof data.report_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(data.report_date)
    || data.period_basis !== "stored_registration_date" || typeof data.period_start !== "string" || typeof data.period_end !== "string") return null;
  const start = Date.parse(data.report_date + "T00:00:00Z");
  if (!Number.isFinite(start) || new Date(start).toISOString().slice(0, 10) !== data.report_date
    || data.period_start !== data.report_date + "T00:00:00"
    || data.period_end !== new Date(start + 86400000).toISOString().slice(0, 10) + "T00:00:00") return null;
  const money = ["alerts_count", "alerts_deficit_value", "inventory_value", "recon_max_diff_value", "recon_total_diff_value"];
  if (data.valuation_unavailable_reason === "organization_valuation_unavailable") {
    if (money.some(key => data[key] !== null)) return null;
  } else if (data.valuation_unavailable_reason !== null || !data.gateway
    || money.some(key => typeof data[key] !== "number" || !Number.isFinite(data[key]) || Number(data[key]) < 0)
    || !Number.isSafeInteger(data.alerts_count)) return null;
  if (data.movements_today_in !== null || data.movements_today_out !== null
    || data.quantity_unavailable_reason !== "unit_snapshot_unavailable") return null;
  return data as unknown as Dashboard;
}

async function dashboardRead(organizationId: number, url: string, init: RequestInit): Promise<Dashboard | null> {
  if (!Number.isSafeInteger(organizationId) || organizationId <= 0) return null;
  try {
    const response = await fetch(url, init);
    return response.ok ? parseDashboard(await response.json(), organizationId) : null;
  } catch { return null; }
}

export const fetchDashboardServer = (organizationId: number, roles?: string, authHeaders?: Record<string, string>) =>
  dashboardRead(organizationId, BASE + "/wms/dashboard?organization_id=" + organizationId,
    { cache: "no-store", headers: authHeaders ?? roleHeaders(roles) });

export const fetchDashboard = (organizationId: number, signal?: AbortSignal) =>
  dashboardRead(organizationId, "/api/wms/dashboard?organization_id=" + organizationId, { cache: "no-store", signal });
export async function fetchReceiptsServer(r?: string, authHeaders?: Record<string, string>): Promise<Receipt[]> {
  const response = await fetch(`${BASE}/wms/receipts`, { cache: "no-store", headers: authHeaders ?? roleHeaders(r) });
  if (!response.ok) throw new Error(`Receipt list unavailable (${response.status})`);
  return response.json();
}
export async function fetchReceiptServer(id: string, r?: string, authHeaders?: Record<string, string>): Promise<ReceiptDetail | null> {
  const response = await fetch(`${BASE}/wms/receipts/${id}`, { cache: "no-store", headers: authHeaders ?? roleHeaders(r) });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Receipt unavailable (${response.status})`);
  return response.json();
}
export async function fetchTasksServer(r?: string, authHeaders?: Record<string, string>): Promise<WmsTask[]> {
  const response = await fetch(`${BASE}/wms/tasks`, { cache: "no-store", headers: authHeaders ?? roleHeaders(r) });
  if (!response.ok) throw new Error(`Warehouse tasks unavailable (${response.status})`);
  return response.json();
}
async function reconciliationRead(organizationId: number, url: string, init: RequestInit): Promise<Reconciliation | null> {
  if (!Number.isSafeInteger(organizationId) || organizationId <= 0) return null;
  try {
    const response = await fetch(url, init);
    if (!response.ok) return null;
    const data: unknown = await response.json();
    // The legacy source is unqualified. Reject money/1C quantities until a
    // separately verified company-source contract replaces this response.
    if (!dashboardRecord(data) || data.organization_id !== organizationId || data.gateway !== false
      || typeof data.source_unavailable_reason !== "string"
      || !["organization_stock_source_unverified", "stock_gateway_unavailable"].includes(data.source_unavailable_reason)
      || data.total_abs_diff_value !== null || !Array.isArray(data.rows)) return null;
    if (!data.rows.every(row => dashboardRecord(row)
      && typeof row.sku_code === "string" && row.sku_code.trim() !== ""
      && typeof row.title === "string" && typeof row.warehouse === "string" && row.warehouse.trim() !== ""
      && typeof row.wms_qty === "number" && Number.isFinite(row.wms_qty)
      && row.onec_qty === null && row.diff === null && row.diff_value === null)) return null;
    return data as unknown as Reconciliation;
  } catch { return null; }
}
export const fetchReconServer = (organizationId: number, r?: string, authHeaders?: Record<string, string>) =>
  reconciliationRead(organizationId, `${BASE}/wms/reconciliation?organization_id=${organizationId}`,
    { cache: "no-store", headers: authHeaders ?? roleHeaders(r) });
export const fetchRecon = (organizationId: number, signal?: AbortSignal) =>
  reconciliationRead(organizationId, `/api/wms/reconciliation?organization_id=${organizationId}`,
    { cache: "no-store", signal });
export const fetchAlertsServer = (r?: string) =>
  ssr<Alerts>("/wms/alerts", r, { rows: [], gateway: false });
export const fetchCyclePlansServer = (r?: string) => ssr<CyclePlan[]>("/wms/cycle-plans", r, []);
export const fetchThresholdsServer = (r?: string) => ssr<StockThreshold[]>("/wms/thresholds", r, []);

// ---- Client ----
export const fetchReceipt = (id: number) => api<ReceiptDetail | null>(`/wms/receipts/${id}`, null);
export async function fetchTasks(): Promise<WmsTask[]> {
  const response = await fetch("/api/wms/tasks", { cache: "no-store" });
  if (!response.ok) throw new Error("Не удалось загрузить складские задания. Проверьте доступ к юрлицу и повторите запрос.");
  return response.json();
}
export const qcReceipt = (id: number, decisions: unknown[], decidedBy = "", expectedRevision?: string) =>
  post(`/wms/receipts/${id}/qc`, { decisions, decided_by: decidedBy, expected_revision: expectedRevision });
export const acceptReceipt = (id: number) => post(`/wms/receipts/${id}/accept`);
export const patchTask = (id: number, patch: Record<string, unknown>) =>
  fetch(`/api/wms/tasks/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
  }).then((r) => r.ok).catch(() => false);
export const createCyclePlan = (body: Record<string, unknown>) => post("/wms/cycle-plans", body);
export const fetchCyclePlans = () => api<CyclePlan[]>("/wms/cycle-plans", []);

/** Опубликовать сигнал дозаказа `wms.stock.low` по нарушенным порогам → Закупки (WMS-R3-2).
 *  Возвращает число отправленных позиций или null (ошибка/шлюз 503 — баннер на фронте). */
export async function emitAlerts(): Promise<{ emitted: number } | null> {
  try {
    const res = await fetch(`/api/wms/alerts/emit`, { method: "POST" });
    if (!res.ok) return null;
    return (await res.json()) as { emitted: number };
  } catch {
    return null;
  }
}

/** Запустить пересчёт по плану → возвращает созданный документ инвентаризации (для перехода). */
export async function runCyclePlan(id: number): Promise<{ id: number } | null> {
  try {
    const res = await fetch(`/api/wms/cycle-plans/${id}/run`, { method: "POST" });
    if (!res.ok) return null;
    return (await res.json()) as { id: number };
  } catch {
    return null;
  }
}
