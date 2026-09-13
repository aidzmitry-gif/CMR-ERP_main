export type DirectoryKind = "clients" | "contacts";
export const DIRECTORY_PAGE_SIZE = 50;

export interface ClientRow {
  id: number;
  name: string;
  unp: string | null;
  is_active: boolean;
  deal_id: number | null;
}

export interface ContactRow {
  id: number;
  full_name: string;
  phone: string | null;
  email: string | null;
  is_primary: boolean;
  counterparty_id: number;
  counterparty_name: string;
  deal_id: number | null;
}

export type DirectoryResult =
  | { status: "ok"; rows: (ClientRow | ContactRow)[]; total: number }
  | { status: "unauthorized" | "forbidden" | "error" };

function positiveId(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function nullableText(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function validRow(value: unknown, kind: DirectoryKind): value is ClientRow | ContactRow {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  if (!positiveId(row.id) || (row.deal_id !== null && !positiveId(row.deal_id))) return false;
  return kind === "clients"
    ? typeof row.name === "string" && nullableText(row.unp) && typeof row.is_active === "boolean"
    : typeof row.full_name === "string" && nullableText(row.phone) && nullableText(row.email)
      && typeof row.is_primary === "boolean" && positiveId(row.counterparty_id)
      && typeof row.counterparty_name === "string";
}

export async function loadDirectory(
  kind: DirectoryKind, q: string, offset: number, signal?: AbortSignal,
): Promise<DirectoryResult> {
  if (!Number.isSafeInteger(offset) || offset < 0) return { status: "error" };
  const params = new URLSearchParams({ q, offset: String(offset), limit: String(DIRECTORY_PAGE_SIZE) });
  try {
    const response = await fetch(`/api/sales/${kind}?${params}`, { cache: "no-store", signal });
    if (response.status === 401) return { status: "unauthorized" };
    if (response.status === 403) return { status: "forbidden" };
    if (!response.ok) return { status: "error" };
    const data: unknown = await response.json();
    if (typeof data !== "object" || data === null) return { status: "error" };
    const { rows, total } = data as Record<string, unknown>;
    if (!Array.isArray(rows) || rows.length > DIRECTORY_PAGE_SIZE
      || typeof total !== "number" || !Number.isSafeInteger(total) || total < 0
      || total < rows.length || (rows.length > 0 && total < offset + rows.length)
      || !rows.every((row) => validRow(row, kind))
      || new Set(rows.map((row) => row.id)).size !== rows.length) return { status: "error" };
    return { status: "ok", rows, total };
  } catch {
    return { status: "error" };
  }
}
