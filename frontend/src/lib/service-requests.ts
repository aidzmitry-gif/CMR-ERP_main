import type { FunnelCard, FunnelStage } from "@/lib/types";

export const SERVICE_STATUSES = [
  { id: "new", title: "Новые", color: "#3B82F6" },
  { id: "in_progress", title: "В работе", color: "#8B5CF6" },
  { id: "done", title: "Закрытые", color: "#10B981" },
] as const;
export const SERVICE_PRIORITIES = [
  { value: "normal", label: "Обычный" }, { value: "high", label: "Высокий" },
  { value: "urgent", label: "Срочный" }, { value: "low", label: "Низкий" },
] as const;

export type ServiceRequestRow = {
  id: number; counterparty_id: number | null; deal_id: number | null;
  title: string; description: string; status: string; priority: string; created_at: string;
};
export type ServiceRequestDraft = { title: string; description: string; priority: string };
export class ServiceRequestError extends Error {
  constructor(public readonly kind: "auth" | "read" | "rejected" | "uncertain") {
    super(kind);
  }
}

const isId = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0;
const nullableId = (value: unknown) => value === null || isId(value);
const statusAllowed = (value: string) => SERVICE_STATUSES.some((s) => s.id === value);
const priorityAllowed = (value: string) => SERVICE_PRIORITIES.some((p) => p.value === value);
function isRow(value: unknown): value is ServiceRequestRow {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return isId(row.id) && nullableId(row.counterparty_id) && nullableId(row.deal_id)
    && typeof row.title === "string" && typeof row.description === "string"
    && typeof row.status === "string" && !!row.status.trim()
    && typeof row.priority === "string" && typeof row.created_at === "string";
}

export async function loadServiceRequests(signal?: AbortSignal): Promise<ServiceRequestRow[]> {
  try {
    const response = await fetch("/api/service/requests", { cache: "no-store", signal });
    if (response.status === 401 || response.status === 403) throw new ServiceRequestError("auth");
    if (!response.ok) throw new ServiceRequestError("read");
    const rows: unknown = await response.json();
    if (!Array.isArray(rows) || !rows.every(isRow) || new Set(rows.map((r) => r.id)).size !== rows.length) {
      throw new ServiceRequestError("read");
    }
    return rows;
  } catch (error) {
    if (error instanceof ServiceRequestError) throw error;
    throw new ServiceRequestError("read");
  }
}

async function write(path: string, method: "POST" | "PATCH", body: object): Promise<ServiceRequestRow> {
  try {
    const response = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (response.status === 401 || response.status === 403) throw new ServiceRequestError("auth");
    if (!response.ok) throw new ServiceRequestError(response.status >= 400 && response.status < 500 && response.status !== 408 ? "rejected" : "uncertain");
    const row: unknown = await response.json();
    if (!isRow(row)) throw new ServiceRequestError("uncertain");
    return row;
  } catch (error) {
    if (error instanceof ServiceRequestError) throw error;
    throw new ServiceRequestError("uncertain");
  }
}

export async function createServiceRequest(draft: ServiceRequestDraft): Promise<ServiceRequestRow> {
  const title = draft.title.trim();
  if (!title || title.length > 255 || !priorityAllowed(draft.priority)) throw new ServiceRequestError("rejected");
  const row = await write("/api/service/requests", "POST", { title, description: draft.description, priority: draft.priority });
  if (row.title !== title || row.description !== draft.description || row.priority !== draft.priority || row.status !== "new") {
    throw new ServiceRequestError("uncertain");
  }
  return row;
}

export async function updateServiceRequest(id: number, patch: { status?: string; priority?: string }): Promise<ServiceRequestRow> {
  if (!isId(id) || (patch.status === undefined && patch.priority === undefined)
    || (patch.status !== undefined && !statusAllowed(patch.status))
    || (patch.priority !== undefined && !priorityAllowed(patch.priority))) throw new ServiceRequestError("rejected");
  const body = { ...(patch.status !== undefined ? { status: patch.status } : {}), ...(patch.priority !== undefined ? { priority: patch.priority } : {}) };
  const row = await write(`/api/service/requests/${id}`, "PATCH", body);
  if (row.id !== id || (patch.status !== undefined && row.status !== patch.status)
    || (patch.priority !== undefined && row.priority !== patch.priority)) throw new ServiceRequestError("uncertain");
  return row;
}

export function serviceCard(row: ServiceRequestRow): FunnelCard {
  return {
    id: row.id, code: `SR-${row.id}`, title: row.title, subtitle: row.description, amount: null,
    priority: SERVICE_PRIORITIES.find((p) => p.value === row.priority)?.label ?? row.priority,
    flag: "", status_tag: "", owner: "", date: row.created_at.slice(0, 16).replace("T", " "),
    progress: null, next_step: "", insight: "", tags: [],
  };
}

export function serviceStages(rows: ServiceRequestRow[]): FunnelStage[] {
  const statuses = [...SERVICE_STATUSES.map((s) => ({ ...s, id: s.id as string })),
    ...[...new Set(rows.map((r) => r.status))].filter((id) => !statusAllowed(id))
      .map((id) => ({ id, title: `Другой статус: ${id}`, color: "#64748B" }))];
  return statuses.map((s) => {
    const cards = rows.filter((r) => r.status === s.id).map(serviceCard);
    return { ...s, cards, count: cards.length, sum: 0 };
  });
}
