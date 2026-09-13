import { DocumentRegisterError, registerId, type DocumentRegisterItem, type ShipmentDocumentReference } from "./document-register-api";

export type ClientIdentity = { id: number; name: string; unp: string | null; revision: number; is_active: boolean; merged_into_id: number | null };
export type BindingSnapshot = {
  organization_id: number;
  deal: { id: number; number: string; counterparty: string; owner_id: number | null };
  client: ClientIdentity;
  documents: { id: number; version: number; number: string; kind: string; amount: string; status: string; content_sha256: string | null; supersedes_id: number | null; superseded_by_id: number | null }[];
};
export type ClientBinding = { deal_id: number; organization_id: number; counterparty_id: number; snapshot: BindingSnapshot; evidence: string; actor: string; created_at: string };
export type BindingPreview = { assigned: boolean; snapshot: BindingSnapshot; binding: ClientBinding | null };
export type BindingClaim = { counterparty_id: number; expected_snapshot: BindingSnapshot; evidence: string };
export type ClientDocument = DocumentRegisterItem & { counterparty_id: number; client_snapshot: ClientIdentity; original_url: string; client_original_url: string };
export type ClientDocumentPage = { organization_id: number; counterparty_id: number; client_current: ClientIdentity; identity_policy: "exact_binding_no_merge_follow"; coverage: { sales_documents: "confirmed_bindings_only"; settlements: "separate_chief_register"; shipments: "unavailable" | "internal_acts_only"; tn_ttn: "not_connected" | "not_certified" }; shipment_documents: ShipmentDocumentReference[]; items: ClientDocument[]; next_after_id: number | null };

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const positive = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v > 0;
const nullableId = (v: unknown) => v === null || positive(v);
const nullableString = (v: unknown) => v === null || typeof v === "string";
const decimal = (v: unknown) => typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v);
const hash = (v: unknown) => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
function invalid(): never { throw new DocumentRegisterError("Некорректный ответ или данные другого клиента, сделки либо юрлица."); }
function ids(...values: string[]) { if (!values.every(registerId)) throw new DocumentRegisterError("Укажите точные ID и выберите юрлицо."); }
function identity(v: unknown, id: number): v is ClientIdentity {
  return object(v) && v.id === id && typeof v.name === "string" && nullableString(v.unp) && positive(v.revision) && typeof v.is_active === "boolean" && nullableId(v.merged_into_id);
}
function snapshot(v: unknown, org: number, deal: number, client: number): v is BindingSnapshot {
  return object(v) && v.organization_id === org && object(v.deal) && v.deal.id === deal && typeof v.deal.number === "string" && typeof v.deal.counterparty === "string" && nullableId(v.deal.owner_id)
    && identity(v.client, client) && Array.isArray(v.documents) && v.documents.every((d) => object(d) && positive(d.id) && positive(d.version) && decimal(d.amount) && ["number", "kind", "status"].every((key) => typeof d[key] === "string") && nullableString(d.content_sha256) && nullableId(d.supersedes_id) && nullableId(d.superseded_by_id));
}
function binding(v: unknown, org: number, deal: number, client: number): v is ClientBinding {
  return object(v) && v.organization_id === org && v.deal_id === deal && v.counterparty_id === client && snapshot(v.snapshot, org, deal, client) && typeof v.evidence === "string" && typeof v.actor === "string" && typeof v.created_at === "string";
}
async function request(url: string, body?: BindingClaim): Promise<Response> {
  let result: Response;
  try { result = await fetch(url, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined }); }
  catch { throw new DocumentRegisterError(body ? "Ответ не получен. Повторите подтверждение с теми же фактами." : "Сеть недоступна. Повторите загрузку."); }
  if (!result.ok) {
    const labels: Record<number, string> = { 401: "Требуется вход в систему.", 403: "Недостаточно прав. Preview и подтверждение доступны только главному бухгалтеру; чтение требует доступа к книге и CRM.", 404: "Клиент или документ недоступны в выбранном контексте.", 409: "Факты изменились или требуют сверки. Получите новый просмотр перед подтверждением.", 422: "Проверьте ID и первичное основание.", 503: "Сервис юридических лиц недоступен." };
    throw new DocumentRegisterError(`${result.status}: ${labels[result.status] || "Не удалось выполнить запрос."}`, result.status);
  }
  return result;
}
async function json(url: string, body?: BindingClaim): Promise<unknown> {
  const result = await request(url, body);
  try { return await result.json(); } catch { invalid(); }
}

export async function previewClientBinding(org: string, deal: string, client: string): Promise<BindingPreview> {
  ids(org, deal, client);
  const value = await json(`/api/sales/organizations/${org}/deals/${deal}/client-binding-preview?counterparty_id=${client}`);
  if (!object(value) || typeof value.assigned !== "boolean" || !snapshot(value.snapshot, Number(org), Number(deal), Number(client)) || (value.assigned ? !binding(value.binding, Number(org), Number(deal), Number(client)) : value.binding !== null)) invalid();
  return value as BindingPreview;
}
export async function claimClientBinding(org: string, deal: string, body: BindingClaim): Promise<ClientBinding> {
  ids(org, deal, String(body.counterparty_id));
  if (!snapshot(body.expected_snapshot, Number(org), Number(deal), body.counterparty_id) || !body.evidence.trim() || body.evidence.length > 1000) invalid();
  const value = await json(`/api/sales/organizations/${org}/deals/${deal}/client-binding`, body);
  if (!binding(value, Number(org), Number(deal), body.counterparty_id)) invalid();
  return value;
}
function clientBase(org: string, client: string) { ids(org, client); return `/api/sales/organizations/${org}/counterparties/${client}`; }
function document(v: unknown, org: string, client: string): ClientDocument {
  if (!object(v) || !positive(v.id) || !positive(v.deal_id) || v.organization_id !== Number(org) || v.counterparty_id !== Number(client) || !identity(v.client_snapshot, Number(client))
    || !positive(v.version) || !decimal(v.amount) || !["number", "kind", "status", "reserve_status", "original_state"].every((key) => typeof v[key] === "string")
    || !["currency", "created_at", "issued_at", "valid_until", "onec_ref", "content_sha256", "replacement_reason"].every((key) => nullableString(v[key]))
    || !nullableId(v.supersedes_id) || !nullableId(v.superseded_by_id) || typeof v.original_available !== "boolean" || typeof v.preview_available !== "boolean"
    || v.original_url !== `/sales/organizations/${org}/deals/${v.deal_id}/documents/${v.id}/original`
    || v.client_original_url !== `/sales/organizations/${org}/counterparties/${client}/documents/${v.id}/original`) invalid();
  return v as ClientDocument;
}
function shipment(v: unknown, org: string): v is ShipmentDocumentReference {
  return object(v) && positive(v.act_id) && positive(v.document_id) && positive(v.document_version)
    && hash(v.content_sha256) && typeof v.source_key === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v.source_key)
    && typeof v.operation_date === "string" && Number.isFinite(Date.parse(v.operation_date))
    && typeof v.actor === "string" && typeof v.evidence === "string" && typeof v.line_count === "number" && Number.isInteger(v.line_count) && v.line_count > 0
    && v.status === "verified_internal_act" && v.tn_ttn_status === "not_certified"
    && v.document_url === `/api/wms/organizations/${org}/physical-shipments/by-key/${v.source_key}/document`;
}
export async function fetchClientDocuments(org: string, client: string, kind = "", after = 0): Promise<ClientDocumentPage> {
  const base = clientBase(org, client);
  if (!["", "invoice", "contract", "order"].includes(kind) || !Number.isSafeInteger(after) || after < 0) invalid();
  const q = new URLSearchParams({ after_id: String(after), limit: "50" }); if (kind) q.set("kind", kind);
  const value = await json(`${base}/document-register?${q}`);
  if (!object(value) || value.organization_id !== Number(org) || value.counterparty_id !== Number(client) || !identity(value.client_current, Number(client)) || value.identity_policy !== "exact_binding_no_merge_follow"
    || !object(value.coverage) || value.coverage.sales_documents !== "confirmed_bindings_only" || value.coverage.settlements !== "separate_chief_register"
    || !["unavailable", "internal_acts_only"].includes(value.coverage.shipments as string)
    || !["not_connected", "not_certified"].includes(value.coverage.tn_ttn as string)
    || !Array.isArray(value.shipment_documents) || !value.shipment_documents.every((row) => shipment(row, org))
    || !Array.isArray(value.items) || !nullableId(value.next_after_id)) invalid();
  const items = value.items.map((v) => document(v, org, client));
  if (items.some((row, i) => row.id <= (i ? items[i - 1].id : after)) || (value.next_after_id !== null && value.next_after_id !== items.at(-1)?.id)) invalid();
  return { ...value, items } as ClientDocumentPage;
}
export async function fetchClientDocument(org: string, client: string, id: number): Promise<ClientDocument> {
  if (!positive(id)) invalid();
  const row = document(await json(`${clientBase(org, client)}/document-register/${id}`), org, client);
  if (row.id !== id) invalid(); return row;
}
export async function fetchClientOriginal(org: string, client: string, id: number): Promise<string> {
  if (!positive(id)) invalid();
  const result = await request(`${clientBase(org, client)}/documents/${id}/original`);
  if (!result.headers.get("Content-Type")?.includes("text/html")) invalid();
  return result.text();
}
