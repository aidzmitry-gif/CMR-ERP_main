import { canonical, hash } from "@/lib/expense-control-api";
import { searchAccountingSettlementDocuments } from "@/lib/accounting-settlement-documents";

export type OfficeDocument = { id: number; number: string; company: string; title: string; stage: string; weight: string; region: string; address: string };
export type CarrierChoice = { id: string; name: string; heavy: boolean };
export type ShippingIntent = {
  mode: "spot" | "contract"; customer: string; cargo: string; weight_kg: string; declared_value_byn: string;
  route_from: string; route_to: string; address: string; zone_code: string; carrier_code: string;
  carrier_name: string; pickup_date: string; contact: string; comment: string;
};
export type ExactInvoice = { organization_id: number; document_id: number; expected_version: number; expected_content_sha256: string };
export type OfficeSource = { document_id: number; number: string; company: string; title: string; amount: string; region: string; weight: string; address: string; deal_id: number | null };
export type ShippingPayload = { schema_version: 1; source: { kind: "office"; key: string; revision: "1" }; source_refs: { document_id: number; document_number: string; log_ref: string }; intent: ShippingIntent };
export type PreparedRequest = { envelope_id: string; request_key: string; actor: string; created_at: string; source_snapshot: OfficeSource; source_sha256: string; payload_sha256: string; payload: ShippingPayload };
export type Association = { association_id: string; request_key: string; execution_id: string; exact_invoice: ExactInvoice; intent_digest: string; assignment_revision: number; current_review_matches: boolean };
export type ShipmentStatus = { id: number; number: string; status: string; carrier_name: string; tracking_status: string; tracking_no: string; eta: string | null };
export type LogisticsStatus = { state: "not_prepared" | "not_received" | "pending" | "withdrawn" | "resolved" | "source_changed" | "unavailable"; intake_id: number | null; pending_reason: string; target: { kind: "shipment" | "rfq"; id: number; number: string; status: string } | null; shipment: ShipmentStatus | null };
export type ShippingContext = { source_snapshot: OfficeSource; source_sha256: string; assignment_revision: number; document_stage: string; principal: string; is_current_reviewer: boolean; capabilities: { can_request: boolean; can_associate: boolean }; request: PreparedRequest | null; association: Association | null; source_matches_request: boolean; logistics: LogisticsStatus };
export type PrepareCommand = { request_key: string; expected_source_hash: string; expected_assignment_revision: number; intent: ShippingIntent };
export type ConfirmCommand = { request_key: string; expected_source_hash: string; expected_assignment_revision: number; exact_invoice: ExactInvoice; envelope_id: string; expected_payload_hash: string; expected_intent_digest: string; evidence_refs: { source_sha256: string; invoice_sha256: string; explanation: string } };
export type AssociationPreview = { exact_invoice: ExactInvoice; intent_digest: string; assignment_revision: number; verified_invoice: { deal_id: number; [key: string]: unknown } };
export type InvoiceChoice = { number: string; exact_invoice: ExactInvoice };
export type PendingCommand = { version: 1; principal: string; document_id: number; kind: "prepare"; body: PrepareCommand } | { version: 1; principal: string; document_id: number; kind: "confirm"; body: ConfirmCommand };

export class OfficeShippingError extends Error {
  constructor(message: string, readonly status?: number, readonly uncertain = false) { super(message); }
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const positive = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v > 0;
const text = (v: unknown): v is string => typeof v === "string";
const digest = (v: unknown): v is string => text(v) && /^[a-f0-9]{64}$/.test(v);
const uuid = (v: unknown): v is string => text(v) && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
const bool = (v: unknown): v is boolean => typeof v === "boolean";
const same = (a: unknown, b: unknown) => canonical(a) === canonical(b);
function invalid(): never { throw new OfficeShippingError("Ответ или сохранённая команда не прошли сверку. Обновите данные."); }
function exact(v: unknown): v is ExactInvoice {
  return object(v) && positive(v.organization_id) && positive(v.document_id) && positive(v.expected_version) && digest(v.expected_content_sha256);
}
function source(v: unknown, id: number): v is OfficeSource {
  return object(v) && v.document_id === id && ["number", "company", "title", "amount", "region", "weight", "address"].every(k => text(v[k]))
    && /^-?\d+\.\d{2}$/.test(String(v.amount)) && (v.deal_id === null || positive(v.deal_id));
}
export function validIntent(v: unknown): v is ShippingIntent {
  if (!object(v) || !["spot", "contract"].includes(String(v.mode))) return false;
  const limits = { customer: 255, cargo: 255, route_from: 128, route_to: 128, address: 255, zone_code: 8, carrier_code: 32, carrier_name: 128, pickup_date: 10, contact: 255, comment: 2000 };
  if (!Object.entries(limits).every(([k, max]) => text(v[k]) && [...v[k] as string].length <= max)) return false;
  if (!["weight_kg", "declared_value_byn"].every(k => text(v[k]) && /^(0|[1-9]\d*)\.\d{2}$/.test(v[k] as string))) return false;
  if (Number(v.weight_kg) >= 1e10 || Number(v.declared_value_byn) >= 1e12) return false;
  const date = v.pickup_date as string;
  return !date || /^\d{4}-\d{2}-\d{2}$/.test(date) && date.slice(0, 4) !== "0000"
    && Number.isFinite(Date.parse(date)) && new Date(date).toISOString().slice(0, 10) === date;
}
export function decimalInput(v: string): string | null {
  const value = v.trim().replace(",", ".");
  if (!/^(0|[1-9]\d*)(\.\d{1,2})?$/.test(value)) return null;
  const [whole, fraction = ""] = value.split(".");
  return `${whole}.${fraction.padEnd(2, "0")}`;
}
function prepare(v: unknown): v is PrepareCommand {
  return object(v) && text(v.request_key) && v.request_key.length > 0 && v.request_key.length <= 64
    && digest(v.expected_source_hash) && positive(v.expected_assignment_revision) && validIntent(v.intent);
}
function confirm(v: unknown): v is ConfirmCommand {
  return object(v) && text(v.request_key) && v.request_key.length > 0 && v.request_key.length <= 64
    && digest(v.expected_source_hash) && positive(v.expected_assignment_revision) && exact(v.exact_invoice)
    && uuid(v.envelope_id) && digest(v.expected_payload_hash) && digest(v.expected_intent_digest)
    && object(v.evidence_refs) && v.evidence_refs.source_sha256 === v.expected_source_hash
    && v.evidence_refs.invoice_sha256 === v.exact_invoice.expected_content_sha256
    && text(v.evidence_refs.explanation) && v.evidence_refs.explanation.trim().length > 0 && [...v.evidence_refs.explanation].length <= 1000;
}
async function request(path: string, init?: RequestInit): Promise<unknown> {
  const mutation = init?.method === "POST";
  let res: Response;
  try { res = await fetch(path, { ...init, cache: "no-store" }); }
  catch (e) { if (e instanceof DOMException && e.name === "AbortError") throw e; throw new OfficeShippingError(mutation ? "Связь прервана. Проверьте, сохранилась ли команда." : "Не удалось загрузить данные. Повторите загрузку.", undefined, mutation); }
  if (!res.ok) {
    const labels: Record<number, string> = { 401: "Войдите в систему.", 403: "Недостаточно прав для этой операции.", 404: "Документ недоступен в текущей области доступа.", 409: "Документ, счёт или назначение изменились. Обновите данные и сверьте результат.", 422: "Проверьте заполнение полей.", 503: "Сервис временно недоступен." };
    throw new OfficeShippingError(labels[res.status] || `Запрос не выполнен (${res.status}).`, res.status, mutation && res.status >= 500);
  }
  try { return await res.json(); } catch { throw new OfficeShippingError("Ответ сервера не прочитан. Обновите сведения для сверки.", undefined, mutation); }
}
const path = (id: number) => { if (!positive(id)) invalid(); return `/api/office/docs/${id}`; };
const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export async function fetchOfficeDocuments(signal?: AbortSignal): Promise<OfficeDocument[]> {
  const v = await request("/api/office/docs", { signal });
  if (!Array.isArray(v) || !v.every(d => object(d) && positive(d.id) && ["number", "company", "title", "stage", "weight", "region", "address"].every(k => text(d[k])))
    || new Set(v.map(d => d.id)).size !== v.length) invalid();
  return v.map(d => ({ id: d.id, number: d.number, company: d.company, title: d.title, stage: d.stage, weight: d.weight, region: d.region, address: d.address }));
}
export async function fetchOfficeCarriers(signal?: AbortSignal): Promise<CarrierChoice[]> {
  const v = await request("/api/office/carriers", { signal });
  if (!Array.isArray(v) || !v.every(d => object(d) && text(d.id) && d.id.length > 0 && text(d.name) && bool(d.heavy))
    || new Set(v.map(d => d.id)).size !== v.length) invalid();
  return v.map(d => ({ id: d.id, name: d.name, heavy: d.heavy }));
}
export async function searchShippingInvoices(org: number, buyer: number, term: string): Promise<InvoiceChoice[]> {
  if (!positive(org) || !positive(buyer)) invalid();
  const rows = await searchAccountingSettlementDocuments(String(org), String(buyer), term);
  const invoices: InvoiceChoice[] = [];
  for (const row of rows) {
    if (row.source !== "sales") continue;
    const sha = (row as typeof row & { content_sha256?: unknown }).content_sha256;
    if (!digest(sha)) throw new OfficeShippingError("В реестре отсутствует точная версия счёта. Обновите реестр; выбор по названию недоступен.");
    invoices.push({ number: row.number, exact_invoice: { organization_id: org, document_id: row.id, expected_version: row.version, expected_content_sha256: sha } });
  }
  if (new Set(invoices.map(v => v.exact_invoice.document_id)).size !== invoices.length) invalid();
  return invoices;
}
export async function parseShippingContext(v: unknown, id: number): Promise<ShippingContext> {
  if (!object(v) || !source(v.source_snapshot, id) || !digest(v.source_sha256) || await hash(v.source_snapshot) !== v.source_sha256
    || !Number.isSafeInteger(v.assignment_revision) || Number(v.assignment_revision) < 0 || !text(v.document_stage)
    || !text(v.principal) || !v.principal || !bool(v.is_current_reviewer) || !object(v.capabilities)
    || !bool(v.capabilities.can_request) || !bool(v.capabilities.can_associate) || !bool(v.source_matches_request)
    || (!v.is_current_reviewer && (v.capabilities.can_request || v.capabilities.can_associate))) invalid();
  if (v.request !== null) {
    const r = v.request;
    if (!object(r) || !uuid(r.envelope_id) || !text(r.request_key) || !r.request_key || !text(r.actor) || !r.actor || !text(r.created_at)
      || !source(r.source_snapshot, id) || !digest(r.source_sha256) || await hash(r.source_snapshot) !== r.source_sha256
      || !digest(r.payload_sha256) || !object(r.payload) || r.payload.schema_version !== 1 || !object(r.payload.source)
      || r.payload.source.kind !== "office" || r.payload.source.key !== `office:shipping-request:${r.envelope_id}` || r.payload.source.revision !== "1"
      || !object(r.payload.source_refs) || r.payload.source_refs.document_id !== id || r.payload.source_refs.document_number !== r.source_snapshot.number
      || !text(r.payload.source_refs.log_ref) || !validIntent(r.payload.intent) || await hash(r.payload) !== r.payload_sha256
      || v.source_matches_request !== (v.source_sha256 === r.source_sha256)) invalid();
  } else if (!v.source_matches_request || v.association !== null) invalid();
  if (v.association !== null) {
    const a = v.association, r = v.request as PreparedRequest;
    if (!object(a) || !uuid(a.association_id) || !uuid(a.execution_id) || !text(a.request_key) || !a.request_key
      || !exact(a.exact_invoice) || !digest(a.intent_digest) || !positive(a.assignment_revision) || !bool(a.current_review_matches)
      || await hash({ schema_version: 1, exact_invoice: a.exact_invoice, intent: r.payload.intent }) !== a.intent_digest) invalid();
  }
  const l = v.logistics;
  if (!object(l) || !["not_prepared", "not_received", "pending", "withdrawn", "resolved", "source_changed", "unavailable"].includes(String(l.state))
    || !(l.intake_id === null || positive(l.intake_id)) || !text(l.pending_reason)) invalid();
  if (l.state === "resolved") {
    const target = l.target;
    if (v.association === null || !object(target) || !["shipment", "rfq"].includes(String(target.kind)) || !positive(target.id) || !text(target.number) || !text(target.status)
      || target.kind !== ((v.request as PreparedRequest).payload.intent.mode === "contract" ? "rfq" : "shipment") || !positive(l.intake_id)) invalid();
    if (l.shipment !== null) {
      const s = l.shipment;
      if (!object(s) || !positive(s.id) || !["number", "status", "carrier_name", "tracking_status", "tracking_no"].every(k => text(s[k]))
        || !(s.eta === null || text(s.eta))
        || target.kind === "shipment" && (s.id !== target.id || s.number !== target.number)) invalid();
    } else if (target.kind === "shipment") invalid();
  } else if (l.target !== null || l.shipment !== null) invalid();
  if ((v.request === null) !== (l.state === "not_prepared") || (!v.source_matches_request && l.state !== "source_changed")
    || ["pending", "withdrawn"].includes(String(l.state)) && !positive(l.intake_id)) invalid();
  return v as ShippingContext;
}
export async function fetchShippingContext(id: number, signal?: AbortSignal): Promise<ShippingContext> {
  return parseShippingContext(await request(`${path(id)}/shipping-source`, { signal }), id);
}
export async function prepareShipping(id: number, body: PrepareCommand): Promise<void> {
  if (!prepare(body)) invalid();
  const v = await request(`${path(id)}/carrier-request`, post(body));
  if (!object(v) || !uuid(v.envelope_id) || v.source_sha256 !== body.expected_source_hash || !object(v.payload)
    || !same(v.payload.intent, body.intent) || !object(v.payload.source_refs) || v.payload.source_refs.document_id !== id
    || !object(v.payload.source) || v.payload.source.key !== `office:shipping-request:${v.envelope_id}` || v.payload.source.kind !== "office"
    || v.payload.source.revision !== "1" || v.payload.schema_version !== 1 || !digest(v.payload_sha256) || await hash(v.payload) !== v.payload_sha256)
    throw new OfficeShippingError("Ответ о подготовке не прошёл сверку. Проверьте сохранённую заявку.", undefined, true);
}
export async function associationCommand(context: ShippingContext, invoice: ExactInvoice, explanation: string): Promise<ConfirmCommand> {
  if (!context.request || !context.source_matches_request || !exact(invoice)) invalid();
  const body = { request_key: crypto.randomUUID(), expected_source_hash: context.source_sha256, expected_assignment_revision: context.assignment_revision,
    exact_invoice: invoice, envelope_id: context.request.envelope_id, expected_payload_hash: context.request.payload_sha256,
    expected_intent_digest: await hash({ schema_version: 1, exact_invoice: invoice, intent: context.request.payload.intent }),
    evidence_refs: { source_sha256: context.request.source_sha256, invoice_sha256: invoice.expected_content_sha256, explanation } };
  if (!confirm(body)) invalid();
  return body;
}
export async function previewAssociation(id: number, body: ConfirmCommand): Promise<AssociationPreview> {
  if (!confirm(body)) invalid();
  const v = await request(`${path(id)}/shipping-association-preview`, post(body));
  if (!object(v) || !same(v.exact_invoice, body.exact_invoice) || v.intent_digest !== body.expected_intent_digest
    || v.assignment_revision !== body.expected_assignment_revision || v.envelope_id !== body.envelope_id
    || v.payload_sha256 !== body.expected_payload_hash || v.source_sha256 !== body.expected_source_hash
    || !object(v.verified_invoice) || !positive(v.verified_invoice.deal_id)) invalid();
  return v as AssociationPreview;
}
export async function confirmAssociation(id: number, body: ConfirmCommand): Promise<void> {
  if (!confirm(body)) invalid();
  const v = await request(`${path(id)}/shipping-association-confirm`, post(body));
  if (!object(v) || !uuid(v.association_id) || !uuid(v.execution_id) || v.intent_digest !== body.expected_intent_digest || !bool(v.replayed))
    throw new OfficeShippingError("Ответ о связи со счётом не прошёл сверку. Проверьте результат.", undefined, true);
}
export async function resolveIntake(context: ShippingContext): Promise<void> {
  const id = context.logistics.intake_id;
  if (!positive(id) || !context.association || !context.source_matches_request || !context.association.current_review_matches || !context.capabilities.can_associate) invalid();
  const v = await request(`/api/logistics/intakes/${id}/resolve`, { method: "POST" });
  if (!object(v) || v.id !== id || v.state !== "resolved") throw new OfficeShippingError("Результат обработки нужно сверить с сохранённым состоянием.", undefined, true);
}

// Tab-local recovery survives reload. No automatic replay or shared cross-user draft.
function journalKey(principal: string, documentId: number) { return `erp.office.shipping.v1:${encodeURIComponent(principal)}:${documentId}`; }
export function savePending(value: PendingCommand): void {
  if (!positive(value.document_id) || !value.principal || !(value.kind === "prepare" ? prepare(value.body) : confirm(value.body))) invalid();
  const key = journalKey(value.principal, value.document_id), body = JSON.stringify(value);
  try {
    if (sessionStorage.getItem(key) !== null) throw new Error("pending");
    sessionStorage.setItem(key, body);
    if (sessionStorage.getItem(key) !== body) throw new Error("storage");
  } catch { throw new OfficeShippingError("Не удалось сохранить команду для сверки. Отправка не выполнена; проверьте доступ к хранилищу вкладки."); }
}
export function readPending(principal: string, documentId: number): PendingCommand | null {
  let raw: string | null;
  try { raw = sessionStorage.getItem(journalKey(principal, documentId)); } catch { throw new OfficeShippingError("Хранилище вкладки недоступно. Отправка команды заблокирована до восстановления сверки."); }
  if (raw === null) return null;
  let v: unknown; try { v = JSON.parse(raw); } catch { invalid(); }
  if (!object(v) || v.version !== 1 || v.principal !== principal || v.document_id !== documentId
    || !(v.kind === "prepare" ? prepare(v.body) : v.kind === "confirm" && confirm(v.body))) invalid();
  return v as PendingCommand;
}
export function pendingMatches(pending: PendingCommand, context: ShippingContext): boolean {
  if (pending.principal !== context.principal || pending.document_id !== context.source_snapshot.document_id) return false;
  if (pending.kind === "prepare") return !!context.request && context.request.request_key === pending.body.request_key
    && context.request.actor === pending.principal && context.request.source_sha256 === pending.body.expected_source_hash && same(context.request.payload.intent, pending.body.intent);
  return !!context.association && context.association.request_key === pending.body.request_key && same(context.association.exact_invoice, pending.body.exact_invoice)
    && context.association.intent_digest === pending.body.expected_intent_digest && context.association.assignment_revision === pending.body.expected_assignment_revision
    && context.request?.envelope_id === pending.body.envelope_id && context.request.payload_sha256 === pending.body.expected_payload_hash;
}
export function clearPending(pending: PendingCommand): void {
  const key = journalKey(pending.principal, pending.document_id);
  if (!same(readPending(pending.principal, pending.document_id), pending)) invalid();
  sessionStorage.removeItem(key);
}
