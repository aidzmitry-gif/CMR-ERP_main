// Домен операционного склада (приёмка/QC, задачи, сверка, low-stock, цикл-каунт, дашборд)
// поверх backend-API `/wms`. 🔴 1С = истина остатка; WMS дублирует движения и читает 1С
// через шлюз. Чистые функции (лейблы/severity) тестируются без React.

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

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
  lines: ReceiptLine[];
}

export interface WmsTask {
  id: number;
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
  onec_qty: number;
  diff: number;
  diff_value: number | null;
}
export interface Reconciliation {
  rows: ReconRow[];
  gateway: boolean;
  total_abs_diff_value: number;
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
  receipts_pending_qc: number;
  tasks_putaway_open: number;
  tasks_pick_open: number;
  alerts_count: number;
  inventories_open: number;
  recon_max_diff_value: number;
  recon_total_diff_value: number;
  movements_today_in: number;
  movements_today_out: number;
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

// ---- Fetch helpers ----
function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}
async function ssr<T>(path: string, roles: string | undefined, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${BASE}${path}`, { cache: "no-store", headers: roleHeaders(roles) });
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
export const fetchDashboardServer = (r?: string) =>
  ssr<Dashboard>("/wms/dashboard", r, {
    receipts_pending_qc: 0, tasks_putaway_open: 0, tasks_pick_open: 0, alerts_count: 0,
    inventories_open: 0, recon_max_diff_value: 0, recon_total_diff_value: 0,
    movements_today_in: 0, movements_today_out: 0, gateway: false,
  });
export const fetchReceiptsServer = (r?: string) => ssr<Receipt[]>("/wms/receipts", r, []);
export const fetchReceiptServer = (id: string, r?: string) =>
  ssr<ReceiptDetail | null>(`/wms/receipts/${id}`, r, null);
export const fetchTasksServer = (r?: string) => ssr<WmsTask[]>("/wms/tasks", r, []);
export const fetchReconServer = (r?: string) =>
  ssr<Reconciliation>("/wms/reconciliation", r, { rows: [], gateway: false, total_abs_diff_value: 0 });
export const fetchAlertsServer = (r?: string) =>
  ssr<Alerts>("/wms/alerts", r, { rows: [], gateway: false });
export const fetchCyclePlansServer = (r?: string) => ssr<CyclePlan[]>("/wms/cycle-plans", r, []);

// ---- Client ----
export const fetchReceipt = (id: number) => api<ReceiptDetail | null>(`/wms/receipts/${id}`, null);
export const fetchTasks = () => api<WmsTask[]>("/wms/tasks", []);
export const qcReceipt = (id: number, decisions: unknown[], decidedBy = "") =>
  post(`/wms/receipts/${id}/qc`, { decisions, decided_by: decidedBy });
export const acceptReceipt = (id: number) => post(`/wms/receipts/${id}/accept`);
export const patchTask = (id: number, patch: Record<string, unknown>) =>
  fetch(`/api/wms/tasks/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
  }).then((r) => r.ok).catch(() => false);
export const createCyclePlan = (body: Record<string, unknown>) => post("/wms/cycle-plans", body);
export const fetchCyclePlans = () => api<CyclePlan[]>("/wms/cycle-plans", []);

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
