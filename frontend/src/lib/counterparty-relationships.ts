export type CounterpartyRelationshipKind = "contacts" | "deals" | "calls";

type RelationshipBase = {
  counterparty_id: number;
  offset: number;
  limit: number;
  total: number;
};

export type CompanyContact = {
  id: number;
  counterparty_id: number;
  full_name: string;
  phone: string | null;
  email: string | null;
  is_primary: boolean;
};

export type RelationshipManager = { employee_id: number; name: string; active: boolean };

export type RelatedDeal = {
  id: number;
  number: string;
  title: string;
  counterparty_id: number | null;
  crm_client_id: number | null;
  stage: string;
  owner_id: number | null;
  responsible_manager: RelationshipManager | null;
};

export type RelatedCall = {
  id: number;
  call_id: string;
  direction: string;
  owner: string;
  status: string;
  result: string | null;
  started_at: string;
  counterparty_id: number | null;
  contact_id: number | null;
  crm_client_id: number | null;
  deal_id: number | null;
};

export type RelationshipPage =
  | (RelationshipBase & { kind: "contacts"; items: CompanyContact[] })
  | (RelationshipBase & { kind: "deals"; items: RelatedDeal[] })
  | (RelationshipBase & { kind: "calls"; items: RelatedCall[] });

export type RelationshipResult =
  | { status: "ok"; page: RelationshipPage }
  | { status: "unauthorized" | "forbidden" | "error" };

const PAGE_SIZE = 20;
const positiveId = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0;
const nullableId = (value: unknown): value is number | null => value === null || positiveId(value);
const nullableText = (value: unknown): value is string | null => value === null || typeof value === "string";

function managerRow(value: unknown): value is RelationshipManager | null {
  if (value === null) return true;
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return positiveId(row.employee_id) && typeof row.name === "string" && !!row.name.trim()
    && typeof row.active === "boolean";
}

function relationshipItem(value: unknown, kind: CounterpartyRelationshipKind, counterpartyId: number): boolean {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  if (!positiveId(row.id)) return false;
  if (kind === "contacts") {
    return row.counterparty_id === counterpartyId && typeof row.full_name === "string"
      && nullableText(row.phone) && nullableText(row.email) && typeof row.is_primary === "boolean";
  }
  if (kind === "deals") {
    return (row.counterparty_id === null || row.counterparty_id === counterpartyId)
      && nullableId(row.crm_client_id) && typeof row.number === "string" && typeof row.title === "string"
      && typeof row.stage === "string" && nullableId(row.owner_id) && managerRow(row.responsible_manager);
  }
  return row.counterparty_id === counterpartyId && typeof row.call_id === "string"
    && typeof row.direction === "string" && typeof row.owner === "string" && typeof row.status === "string"
    && nullableText(row.result) && typeof row.started_at === "string"
    && nullableId(row.contact_id) && nullableId(row.crm_client_id) && nullableId(row.deal_id);
}

export async function loadCounterpartyRelationships(
  counterpartyId: number,
  kind: CounterpartyRelationshipKind,
  offset: number,
  focusContactId?: number,
  signal?: AbortSignal,
): Promise<RelationshipResult> {
  if (!positiveId(counterpartyId) || !Number.isSafeInteger(offset) || offset < 0
    || (focusContactId !== undefined && (kind !== "contacts" || !positiveId(focusContactId)))) return { status: "error" };
  const query = new URLSearchParams({ kind, offset: String(offset), limit: String(PAGE_SIZE) });
  if (focusContactId !== undefined) query.set("contact_id", String(focusContactId));
  try {
    const response = await fetch(`/api/sales/counterparties/${counterpartyId}/relationships?${query}`, {
      cache: "no-store", ...(signal ? { signal } : {}),
    });
    if (response.status === 401) return { status: "unauthorized" };
    if (response.status === 403) return { status: "forbidden" };
    if (!response.ok) return { status: "error" };
    const data: unknown = await response.json();
    if (typeof data !== "object" || data === null) return { status: "error" };
    const page = data as Record<string, unknown>;
    if (page.kind !== kind || page.counterparty_id !== counterpartyId || page.offset !== offset
      || page.limit !== PAGE_SIZE || !Number.isSafeInteger(page.total) || (page.total as number) < 0
      || !Array.isArray(page.items) || page.items.length > PAGE_SIZE
      || (page.total as number) < page.items.length
      || (page.items.length > 0 && (page.total as number) < offset + page.items.length)
      || !page.items.every((item) => relationshipItem(item, kind, counterpartyId))
      || new Set(page.items.map((item) => (item as { id: number }).id)).size !== page.items.length) {
      return { status: "error" };
    }
    return { status: "ok", page: data as RelationshipPage };
  } catch {
    return { status: "error" };
  }
}
