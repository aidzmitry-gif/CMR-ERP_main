export type WorkEmployee = { id: number; full_name: string; department: string; position: string; status: string };
export type WorkSession = { id: number; employee_id: number; work_date: string; started_at: string;
  ended_at: string | null; elapsed_seconds: number; present: boolean; last_seen_at: string };
export type WorkPolicy = { id: number; daily_minutes: number; weekmask: number; start_minute: number | null;
  manager_id: number; effective_from: string; reference: string };
export type WorkContext = { server_now: string; today: string; timezone: string; employee: WorkEmployee;
  session: WorkSession | null; policy: WorkPolicy | null; can_configure: boolean;
  time_rule: "between_buttons"; presence_affects_hours: false };
export type WorkBoard = { server_now: string; items: { employee: WorkEmployee; session: WorkSession | null; present: boolean; last_seen_at: string | null }[];
  presence_affects_hours: false };
export type WorkDay = { id: number; employee_id: number; date: string; worked_seconds: number;
  norm_minutes: number; credited_minutes: number; extra_minutes: number; code: string | null;
  approval_status: "pending" | "approved" | "rejected" | null; can_decide: boolean;
  source: "absence" | "explicit_buttons" };
export type WorkSheet = { period: string; employees: WorkEmployee[]; items: WorkDay[];
  can_configure: boolean; payroll_posted: false };
export type WorkSettings = { employees: WorkEmployee[]; managers: { id: number; full_name: string; employee_id: number }[] };
export type WorkPending = { employee_id: number; request_key: string; action: "start" | "end"; session_id?: number };

export class WorktimeError extends Error {
  constructor(message: string, public readonly rejected: boolean) { super(message); }
}

export async function worktimeRequest<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/hr/${path}`, { cache: "no-store",
    ...(body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new WorktimeError(typeof data?.detail === "string" ? data.detail
    : `Запрос учёта времени не выполнен (${response.status})`, [400, 401, 403, 404, 409, 422].includes(response.status));
  if (!data || typeof data !== "object") throw new Error("Получен неполный ответ учёта времени");
  return data as T;
}

export function validWorkSession(value: unknown, employeeId: number): value is WorkSession {
  const row = value as WorkSession | null;
  return !!row && Number.isSafeInteger(row.id) && row.id > 0 && row.employee_id === employeeId
    && typeof row.started_at === "string" && Number.isFinite(Date.parse(row.started_at))
    && (row.ended_at === null || typeof row.ended_at === "string" && Number.isFinite(Date.parse(row.ended_at)))
    && Number.isFinite(row.elapsed_seconds) && row.elapsed_seconds >= 0 && typeof row.present === "boolean";
}

export function readPending(value: string | null, employeeId: number): WorkPending | null {
  if (!value) return null;
  try {
    const row = JSON.parse(value) as WorkPending;
    return row.employee_id === employeeId && /^[0-9a-f-]{36}$/i.test(row.request_key)
      && (row.action === "start" || row.action === "end" && Number.isSafeInteger(row.session_id) && Number(row.session_id) > 0)
      ? row : null;
  } catch { return null; }
}

export function clockLabel(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  return [Math.floor(value / 3600), Math.floor(value / 60) % 60, value % 60].map(n => String(n).padStart(2, "0")).join(":");
}

export function minutesLabel(minutes: number): string {
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}
