import type { DealDoc } from "./api";

export type Price = { item_id: number; unit_price_net: string; vat_rate: string };
export type InvoiceInput = { reserve_mode?: "stock" | "on_order"; organization_id: number; currency: string; document_date: string; valid_until: string; pricing: Price[]; pricing_evidence: string };
export type Allocation = { line_no: number; warehouse: string; qty: string };
export type InvoiceCommand = InvoiceInput & { request_key: string; expected_document_version: number; expected_basis_digest: string; allocations: Allocation[]; evidence?: string; journal_complete?: true; unreserved_confirmed?: true };
export type InvoiceLine = { line_no: number; item_id: number; sku_code: string; name: string; unit: string; qty: string; price: string; vat_rate: string; net: string; tax: string; total: string; currency: string };
export type Availability = { organization_id: number; source: "wms_physical"; rows: { sku_code: string; warehouse: string; physical: string | null; reserved: string; free: string | null }[]; basis_by_warehouse: Record<string, { version: string | null; cutoff: number | null }> };
export type InvoicePreview = InvoiceInput & { deal_id: number; document_id: number | null; document_version: number; basis_digest: string; amount: string; lines: InvoiceLine[]; seller_profile: { profile_id: number; revision: number; digest: string; effective_from: string }; seller: Record<string, string | null>; buyer: { counterparty_id: number; revision: number; name: string; unp: string | null; requisites: Record<string, unknown>; requisites_digest: string }; availability: Availability | null };
export type InvoiceResult = { document: DealDoc; status: "issued"; organization_id: number; document_version: number; content_sha256: string; reservation_digest: string | null; replayed: boolean };
export type InvoiceItem = { id: number; sku_code: string; name: string; qty: number };
export type PendingInvoice = { dealId: string; documentId?: number; endpoint: string; body: string; command: InvoiceCommand };

const obj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const id = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const decimal = (v: unknown): v is string => typeof v === "string" && /^-?\d{1,12}(?:\.\d{1,2})?$/.test(v);
export function exact(value: string): string {
  const text = value.trim().replace(",", ".");
  if (!/^\d{1,12}(?:\.\d{1,2})?$/.test(text)) throw new InvoiceError("Введите неотрицательное число с точностью до двух знаков.");
  const [whole, fraction = ""] = text.split(".");
  return `${BigInt(whole)}.${fraction.padEnd(2, "0")}`;
}
export function units(value: string): bigint {
  const [whole, fraction] = exact(value).split(".");
  return BigInt(whole) * 100n + BigInt(fraction);
}
export class InvoiceError extends Error {
  constructor(message: string, public status?: number, public uncertain = false) { super(message); }
}
function invalid(): never { throw new InvoiceError("Ответ не соответствует выбранной сделке, юрлицу или контракту счёта."); }
function endpoint(dealId: string, documentId?: number) {
  if (!/^[1-9]\d*$/.test(dealId) || !Number.isSafeInteger(Number(dealId)) || (documentId !== undefined && !id(documentId))) invalid();
  return documentId ? `/api/sales/documents/${documentId}/issue` : `/api/sales/deals/${dealId}/documents`;
}
async function request(url: string, body?: string, issuance = false): Promise<unknown> {
  let response: Response;
  try { response = await fetch(url, { method: body === undefined ? "GET" : "POST", cache: "no-store", headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body }); }
  catch { throw new InvoiceError(issuance ? "Ответ на выпуск не получен. Результат неизвестен; повторите исходный запрос." : "Не удалось загрузить данные. Повторите запрос.", undefined, issuance); }
  if (!response.ok) {
    const labels: Record<number, string> = { 401: "Требуется вход.", 403: "Нет доступа к операции или выбранному юрлицу.", 404: "Сделка или документ недоступны.", 409: "Данные изменились, остатка недостаточно либо ключ требует сверки.", 422: "Проверьте реквизиты запроса, цены, ставки и распределение.", 503: "Сервис выпуска временно недоступен." };
    const detail = await response.json().catch(() => null);
    const text = obj(detail) && typeof detail.detail === "string" ? ` ${detail.detail}` : "";
    throw new InvoiceError(`${response.status}: ${labels[response.status] ?? "Ошибка запроса."}${text}`, response.status, issuance && response.status >= 500);
  }
  try { return await response.json(); }
  catch { throw new InvoiceError("Некорректный ответ сервера. Результат выпуска требует проверки.", undefined, issuance); }
}
export async function invoiceItems(dealId: string): Promise<InvoiceItem[]> {
  endpoint(dealId);
  const rows = await request(`/api/sales/deals/${dealId}/items`);
  if (!Array.isArray(rows) || !rows.every(r => obj(r) && id(r.id) && typeof r.code === "string" && typeof r.title === "string" && typeof r.qty === "number" && Number.isFinite(r.qty) && r.qty > 0)) invalid();
  return rows.map(r => ({ id: r.id, sku_code: r.code, name: r.title, qty: r.qty }));
}
export function validatePreview(value: unknown, dealId: string, input: InvoiceInput, documentId?: number): InvoicePreview {
  if (!obj(value) || value.deal_id !== Number(dealId) || value.organization_id !== input.organization_id || value.document_id !== (documentId ?? null)
    || !id(value.document_version) || !hash(value.basis_digest) || !decimal(value.amount) || value.currency !== input.currency
    || value.document_date !== input.document_date || value.valid_until !== input.valid_until || value.pricing_evidence !== input.pricing_evidence
    || !obj(value.seller) || value.seller.currency !== input.currency || !["name", "unp", "address", "account", "bank", "bik", "director"].every(k => typeof (value.seller as Record<string, unknown>)[k] === "string")
    || !obj(value.seller_profile) || !id(value.seller_profile.profile_id) || !id(value.seller_profile.revision) || !hash(value.seller_profile.digest)
    || !obj(value.buyer) || !id(value.buyer.counterparty_id) || !id(value.buyer.revision) || typeof value.buyer.name !== "string" || !(value.buyer.unp === null || typeof value.buyer.unp === "string") || !obj(value.buyer.requisites) || !hash(value.buyer.requisites_digest)
    || !Array.isArray(value.lines) || value.lines.length !== input.pricing.length) invalid();
  const seen = new Set<number>();
  for (const [index, line] of value.lines.entries()) {
    if (!obj(line) || line.line_no !== index + 1 || !id(line.item_id) || seen.has(line.item_id) || !["sku_code", "name", "unit"].every(k => typeof line[k] === "string")
      || !["qty", "price", "vat_rate", "net", "tax", "total"].every(k => decimal(line[k])) || line.currency !== input.currency) invalid();
    const price = input.pricing.find(p => p.item_id === line.item_id);
    if (!price || line.price !== exact(price.unit_price_net) || line.vat_rate !== exact(price.vat_rate) || units(line.qty as string) <= 0n) invalid();
    seen.add(line.item_id);
  }
  if ((value.reserve_mode ?? "stock") !== (input.reserve_mode ?? "stock")) invalid();
  if (input.reserve_mode === "on_order") {
    if (value.availability !== null) invalid();
    return value as InvoicePreview;
  }
  const availability = value.availability;
  if (!obj(availability) || availability.organization_id !== input.organization_id || availability.source !== "wms_physical" || !Array.isArray(availability.rows) || !obj(availability.basis_by_warehouse)) invalid();
  const pairs = new Set<string>();
  for (const row of availability.rows) {
    if (!obj(row) || typeof row.sku_code !== "string" || typeof row.warehouse !== "string" || !row.warehouse.trim() || !decimal(row.reserved)
      || !(row.physical === null || decimal(row.physical)) || !(row.free === null || decimal(row.free))) invalid();
    const pair = JSON.stringify([row.sku_code, row.warehouse]);
    if (pairs.has(pair)) invalid();
    pairs.add(pair);
    const basis = availability.basis_by_warehouse[row.warehouse];
    if (!obj(basis) || !(basis.version === null || hash(basis.version)) || !(basis.cutoff === null || id(basis.cutoff))) invalid();
  }
  return value as InvoicePreview;
}
export async function previewInvoice(dealId: string, input: InvoiceInput, documentId?: number) {
  endpoint(dealId, documentId);
  return validatePreview(await request(`/api/sales/deals/${dealId}/invoice-preview`, JSON.stringify({ ...input, ...(documentId ? { document_id: documentId } : {}) })), dealId, input, documentId);
}
export function allocationError(preview: Pick<InvoicePreview, "reserve_mode" | "availability" | "lines">, allocations: Allocation[]): string | null {
  if (preview.reserve_mode === "on_order") return allocations.length ? "Под заказ не допускает складских распределений." : null;
  if (!preview.availability) return "Нет подтверждённой доступности склада.";
  const used = new Map<string, bigint>();
  try {
    if (!allocations.length) return "Распределите все строки по складам.";
    const pairs = new Set<string>();
    for (const allocation of allocations) {
      const line = preview.lines.find(l => l.line_no === allocation.line_no);
      if (!line) return "Неизвестная строка счёта.";
      const row = preview.availability.rows.find(r => r.sku_code === line.sku_code && r.warehouse === allocation.warehouse);
      if (!row || row.free === null || row.physical === null) return "Выберите склад с известной доступностью из серверного просмотра.";
      const qty = units(allocation.qty);
      if (qty <= 0n) return "Количество распределения должно быть больше нуля.";
      const pair = JSON.stringify([allocation.line_no, allocation.warehouse]);
      if (pairs.has(pair)) return "Объедините повторное распределение одной строки на один склад.";
      pairs.add(pair);
      const stockKey = JSON.stringify([line.sku_code, allocation.warehouse]);
      used.set(stockKey, (used.get(stockKey) ?? 0n) + qty);
      if (row.free.startsWith("-") || (used.get(stockKey) ?? 0n) > units(row.free)) return "Распределение превышает наблюдаемый свободный остаток.";
    }
    for (const line of preview.lines) {
      if (allocations.filter(a => a.line_no === line.line_no).reduce((s, a) => s + units(a.qty), 0n) !== units(line.qty)) return `Распределите полностью строку ${line.line_no}.`;
    }
  } catch { return "Проверьте точные количества распределения."; }
  return null;
}
export function prepareCommand(dealId: string, documentId: number | undefined, input: InvoiceInput, preview: InvoicePreview, allocations: Allocation[], evidence: string): PendingInvoice {
  if ((input.reserve_mode ?? "stock") !== (preview.reserve_mode ?? "stock")) invalid();
  if (input.reserve_mode === "on_order") {
    if (allocations.length || preview.availability !== null) invalid();
    const command: InvoiceCommand = { ...input, pricing: input.pricing.map(p => ({ ...p })), request_key: crypto.randomUUID(),
      expected_document_version: preview.document_version, expected_basis_digest: preview.basis_digest, allocations: [], unreserved_confirmed: true };
    return { dealId, documentId, endpoint: endpoint(dealId, documentId), command, body: JSON.stringify({ ...(!documentId ? { kind: "invoice" } : {}), ...command }) };
  }
  const error = allocationError(preview, allocations);
  if (error || !evidence.trim()) throw new InvoiceError(error ?? "Укажите основание полноты журнала.");
  const command: InvoiceCommand = { ...input, pricing: input.pricing.map(p => ({ ...p })), request_key: crypto.randomUUID(), expected_document_version: preview.document_version,
    expected_basis_digest: preview.basis_digest, allocations: allocations.map(a => ({ ...a, qty: exact(a.qty) })), evidence: evidence.trim(), journal_complete: true };
  return { dealId, documentId, endpoint: endpoint(dealId, documentId), command, body: JSON.stringify({ ...(!documentId ? { kind: "invoice" } : {}), ...command }) };
}
export async function issueInvoice(pending: PendingInvoice): Promise<InvoiceResult> {
  if (pending.endpoint !== endpoint(pending.dealId, pending.documentId) || pending.body !== JSON.stringify({ ...(!pending.documentId ? { kind: "invoice" } : {}), ...pending.command })) invalid();
  const v = await request(pending.endpoint, pending.body, true);
  const expected = pending.command;
  const onOrder = expected.reserve_mode === "on_order";
  if (!obj(v) || v.status !== "issued" || v.organization_id !== expected.organization_id || v.document_version !== expected.expected_document_version || !hash(v.content_sha256) || (onOrder ? v.reservation_digest !== null : !hash(v.reservation_digest)) || typeof v.replayed !== "boolean"
    || !obj(v.document) || !id(v.document.id) || (pending.documentId !== undefined && v.document.id !== pending.documentId) || v.document.kind !== "invoice"
    || v.document.content_sha256 !== v.content_sha256 || v.document.version !== v.document_version || v.document.status !== "issued" || v.document.original_state !== "issued" || (v.document.reserve_mode ?? "stock") !== (expected.reserve_mode ?? "stock") || v.document.reserve_status !== (onOrder ? "unreserved" : "reserved") || typeof v.document.number !== "string" || typeof v.document.amount !== "number" || !Number.isFinite(v.document.amount) || v.document.amount < 0) {
    throw new InvoiceError("Ответ выпуска не совпадает с исходным запросом. Сохранён точный запрос для сверки/повтора.", undefined, true);
  }
  // DocumentOut has no deal_id: verify the returned original in the scoped list.
  try {
    const docs = await request(`/api/sales/deals/${pending.dealId}/documents`);
    const issued = v.document;
    if (!Array.isArray(docs) || !docs.some(d => obj(d) && d.id === issued.id && d.kind === "invoice" && d.content_sha256 === v.content_sha256 && d.version === v.document_version && (d.reserve_mode ?? "stock") === (expected.reserve_mode ?? "stock"))) invalid();
  } catch { throw new InvoiceError("Выпуск ответил, но связь оригинала со сделкой пока не подтверждена. Повторите исходный запрос.", undefined, true); }
  return v as InvoiceResult;
}
const pendingKey = (dealId: string) => `erp-invoice-pending-v1:${dealId}`;
export function savePending(pending: PendingInvoice) {
  try { sessionStorage.setItem(pendingKey(pending.dealId), JSON.stringify(pending)); }
  catch { throw new InvoiceError("Не удалось сохранить исходный запрос в этой вкладке. Выпуск не отправлен."); }
}
export function loadPending(dealId: string): PendingInvoice | null {
  const raw = sessionStorage.getItem(pendingKey(dealId));
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as PendingInvoice;
    if (value.dealId !== dealId || !obj(value.command) || !hash(value.command.expected_basis_digest) || value.endpoint !== endpoint(dealId, value.documentId)
      || value.body !== JSON.stringify({ ...(!value.documentId ? { kind: "invoice" } : {}), ...value.command })) invalid();
    return value;
  } catch { throw new InvoiceError("Сохранённый запрос повреждён. Проверьте историю счёта; новый выпуск заблокирован."); }
}
export function clearPending(dealId: string) { sessionStorage.removeItem(pendingKey(dealId)); }
