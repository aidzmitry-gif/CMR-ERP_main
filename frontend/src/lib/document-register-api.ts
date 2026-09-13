export type RegisterOrganization = { id: number; name: string; unp: string };
export type ShipmentDocumentReference = {
  act_id: number; document_id: number; document_version: number; content_sha256: string;
  source_key: string; operation_date: string; actor: string; evidence: string; line_count: number;
  status: "verified_internal_act"; tn_ttn_status: "not_certified"; document_url: string;
};
export type DocumentRegisterItem = {
  id: number; deal_id: number; organization_id: number; kind: string; number: string;
  version: number; status: string; amount: string; currency: string | null;
  created_at: string | null; issued_at: string | null; valid_until: string | null;
  expiry_reminder_at?: string | null;
  reserve_status: string; onec_ref: string | null; original_state: string;
  content_sha256: string | null; replacement_reason: string | null;
  supersedes_id: number | null; superseded_by_id: number | null;
  original_available: boolean; preview_available: boolean;
};
export type DocumentRegisterPage = {
  organization_id: number; deal_id: number;
  client_identity: { status: "unresolved"; counterparty_id: null } | { status: "confirmed"; counterparty_id: number; snapshot: { id: number; name: string; unp: string | null; revision: number; is_active: boolean; merged_into_id: number | null } };
  coverage: { sales_documents: "available"; settlements: "separate_chief_register"; shipments: "unavailable" | "internal_acts_only"; tn_ttn: "not_connected" | "not_certified" };
  shipment_documents: ShipmentDocumentReference[];
  items: DocumentRegisterItem[]; next_after_id: number | null;
};

export class DocumentRegisterError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}
export function registerId(value: string): boolean { return /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)); }
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const positive = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const nullableString = (value: unknown) => value === null || typeof value === "string";
const hash = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);

async function response(path: string): Promise<Response> {
  let result: Response;
  try { result = await fetch(path, { cache: "no-store", method: "GET" }); }
  catch { throw new DocumentRegisterError("Сеть недоступна. Повторите загрузку реестра."); }
  if (!result.ok) {
    const labels: Record<number, string> = { 401: "Войдите в систему.", 403: "Недостаточно прав для выбранной книги и сделки.", 404: "Документ или сделка недоступны в выбранном юрлице.", 409: "Требуется сверка версии или оригинала.", 422: "Некорректные параметры реестра.", 503: "Сервис юридических лиц недоступен." };
    throw new DocumentRegisterError(`${result.status}: ${labels[result.status] || "Не удалось загрузить документы."}`, result.status);
  }
  return result;
}
async function json(path: string): Promise<unknown> {
  const result = await response(path);
  try { return await result.json(); }
  catch { throw new DocumentRegisterError("Сервис вернул некорректный ответ."); }
}
function validClientIdentity(value: unknown): boolean {
  if (!object(value)) return false;
  if (value.status === "unresolved") return value.counterparty_id === null;
  const snapshot = value.snapshot;
  return value.status === "confirmed" && positive(value.counterparty_id) && object(snapshot)
    && snapshot.id === value.counterparty_id && typeof snapshot.name === "string"
    && nullableString(snapshot.unp) && positive(snapshot.revision) && typeof snapshot.is_active === "boolean"
    && (snapshot.merged_into_id === null || positive(snapshot.merged_into_id));
}
function invalid(): never { throw new DocumentRegisterError("Сервис вернул некорректный или чужой реестр."); }
function scope(org: string, dealId: string) {
  if (!registerId(org) || !registerId(dealId)) throw new DocumentRegisterError("Выберите юрлицо и точную сделку.");
  return `/api/sales/organizations/${org}/deals/${dealId}`;
}
function item(value: unknown, org: string, dealId: string): DocumentRegisterItem {
  if (!object(value) || !positive(value.id) || value.organization_id !== Number(org) || value.deal_id !== Number(dealId)
    || !positive(value.version) || typeof value.amount !== "string" || !/^-?\d+(\.\d+)?$/.test(value.amount)
    || !["kind", "number", "status", "reserve_status", "original_state"].every((key) => typeof value[key] === "string")
    || !["currency", "created_at", "issued_at", "valid_until", "onec_ref", "content_sha256", "replacement_reason"].every((key) => nullableString(value[key]))
    || !["supersedes_id", "superseded_by_id"].every((key) => value[key] === null || positive(value[key]))
    || typeof value.original_available !== "boolean" || typeof value.preview_available !== "boolean") invalid();
  if (value.expiry_reminder_at !== undefined && value.expiry_reminder_at !== null
    && (typeof value.expiry_reminder_at !== "string" || !Number.isFinite(Date.parse(value.expiry_reminder_at)))) invalid();
  return value as DocumentRegisterItem;
}
function shipment(value: unknown, org: string): value is ShipmentDocumentReference {
  return object(value) && positive(value.act_id) && positive(value.document_id) && positive(value.document_version)
    && hash(value.content_sha256) && typeof value.source_key === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value.source_key)
    && typeof value.operation_date === "string" && Number.isFinite(Date.parse(value.operation_date))
    && typeof value.actor === "string" && typeof value.evidence === "string" && typeof value.line_count === "number" && Number.isInteger(value.line_count) && value.line_count > 0
    && value.status === "verified_internal_act" && value.tn_ttn_status === "not_certified"
    && value.document_url === `/api/wms/organizations/${org}/physical-shipments/by-key/${value.source_key}/document`;
}

export async function fetchRegisterOrganizations(): Promise<RegisterOrganization[]> {
  const value = await json("/api/sales/document-register/organizations");
  if (!Array.isArray(value) || !value.every((row) => object(row) && positive(row.id) && typeof row.name === "string" && typeof row.unp === "string")) invalid();
  return value as RegisterOrganization[];
}
export async function fetchDocumentRegister(org: string, dealId: string, kind = "", after = 0): Promise<DocumentRegisterPage> {
  const base = scope(org, dealId);
  if (!Number.isSafeInteger(after) || after < 0 || !["", "invoice", "contract", "order"].includes(kind)) invalid();
  const params = new URLSearchParams({ after_id: String(after), limit: "50" });
  if (kind) params.set("kind", kind);
  const value = await json(`${base}/document-register?${params}`);
  if (!object(value) || value.organization_id !== Number(org) || value.deal_id !== Number(dealId) || !Array.isArray(value.items)
    || !(value.next_after_id === null || positive(value.next_after_id))
    || !validClientIdentity(value.client_identity)
    || !object(value.coverage) || value.coverage.sales_documents !== "available" || value.coverage.settlements !== "separate_chief_register"
    || !["unavailable", "internal_acts_only"].includes(value.coverage.shipments as string)
    || !["not_connected", "not_certified"].includes(value.coverage.tn_ttn as string)
    || !Array.isArray(value.shipment_documents) || !value.shipment_documents.every((row) => shipment(row, org))) invalid();
  const items = value.items.map((row) => item(row, org, dealId));
  if (items.some((row, i) => row.id <= (i ? items[i - 1].id : after)) || (value.next_after_id !== null && value.next_after_id !== items.at(-1)?.id)) invalid();
  return { ...value, items } as DocumentRegisterPage;
}
export async function fetchRegisterDocument(org: string, dealId: string, id: number): Promise<DocumentRegisterItem> {
  if (!positive(id)) invalid();
  const result = item(await json(`${scope(org, dealId)}/document-register/${id}`), org, dealId);
  if (result.id !== id) invalid();
  return result;
}
export async function fetchRegisterOriginal(org: string, dealId: string, id: number): Promise<string> {
  if (!positive(id)) invalid();
  const result = await response(`${scope(org, dealId)}/documents/${id}/original`);
  if (!result.headers.get("Content-Type")?.includes("text/html")) invalid();
  return result.text();
}
