/** Read-only activity of a lead's linked deal; the API enforces deal visibility. */
export type ActivityTask = {
  id: number; deal_id: number; title: string; kind: string;
  due_at: string | null; status: "open" | "done" | "canceled"; overdue: boolean;
};
export type ActivityMessage = {
  id: number; channel: string; direction: string; author: string;
  text: string; created_at: string;
};
export type ActivityResult<T> =
  | { status: "ok"; rows: T[] }
  | { status: "error"; reason: "access" | "missing" | "request" | "malformed" };

export function validActivityId(id: unknown): id is number {
  return typeof id === "number" && Number.isSafeInteger(id) && id > 0;
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

async function read<T extends { id: number }>(
  dealId: number, feed: string, valid: (row: unknown) => row is T, signal?: AbortSignal,
): Promise<ActivityResult<T>> {
  if (!validActivityId(dealId)) return { status: "error", reason: "malformed" };
  try {
    const response = await fetch(`/api/sales/deals/${dealId}/${feed}`, { cache: "no-store", signal });
    if (!response.ok) return { status: "error", reason:
      response.status === 401 || response.status === 403 ? "access"
        : response.status === 404 ? "missing" : "request" };
    const rows: unknown = await response.json();
    if (!Array.isArray(rows) || !rows.every(valid)
      || new Set(rows.map((row) => row.id)).size !== rows.length) {
      return { status: "error", reason: "malformed" };
    }
    return { status: "ok", rows };
  } catch {
    return { status: "error", reason: "request" };
  }
}

export function readActivityTasks(dealId: number, signal?: AbortSignal) {
  return read<ActivityTask>(dealId, "tasks", (row): row is ActivityTask =>
    record(row) && validActivityId(row.id) && row.deal_id === dealId
    && typeof row.title === "string" && typeof row.kind === "string"
    && (row.due_at === null || typeof row.due_at === "string")
    && typeof row.status === "string" && ["open", "done", "canceled"].includes(row.status)
    && typeof row.overdue === "boolean", signal);
}

export function readActivityMessages(dealId: number, signal?: AbortSignal) {
  return read<ActivityMessage>(dealId, "messages", (row): row is ActivityMessage =>
    record(row) && validActivityId(row.id) && typeof row.channel === "string"
    && typeof row.direction === "string" && typeof row.author === "string"
    && typeof row.text === "string" && typeof row.created_at === "string", signal);
}
