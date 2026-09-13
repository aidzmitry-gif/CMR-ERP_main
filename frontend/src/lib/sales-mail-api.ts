export interface IncomingAttachment {
  index: number;
  filename: string;
  content_type: string;
  size: number | null;
  sha256: string | null;
  downloadable: boolean;
  blocked_reason: string | null;
}

export interface IncomingEmail {
  receipt_id: string;
  direction: "incoming";
  deal_id: number | null;
  owner_id: number | null;
  owner: string | null;
  sender: string | null;
  to: string[];
  cc: string[];
  subject: string;
  received_at: string;
  message_date: string | null;
  message_id: string | null;
  routing_status: string;
  routing_reason: string;
  attachments: IncomingAttachment[];
}

export interface IncomingEmailDetail extends IncomingEmail {
  body_text: string;
  headers: Record<string, string[]>;
  raw_sha256: string;
}

export interface IncomingPage {
  items: IncomingEmail[];
  next_offset: number | null;
}

export interface SalesDealOption {
  id: number;
  number: string;
  title: string;
  counterparty: string;
  owner: string | null;
}

export class SalesMailHttpError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "SalesMailHttpError";
    this.status = status;
  }
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init ?? { cache: "no-store" });
  const payload = await response.json().catch(() => null) as { detail?: unknown } | T | null;
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string"
      ? payload.detail
      : `Не удалось выполнить запрос CRM (HTTP ${response.status})`;
    throw new SalesMailHttpError(response.status, detail);
  }
  if (payload === null) throw new Error("CRM вернула неполный ответ");
  return payload as T;
}

function queryUrl(path: string, offset: number, limit: number) {
  const query = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return `${path}?${query.toString()}`;
}

export function incomingUrl(dealId: string, suffix = "") {
  return `/api/sales/deals/${encodeURIComponent(dealId)}/incoming-emails${suffix}`;
}

export function incomingAttachmentUrl(dealId: string, receiptId: string, index: number) {
  return incomingUrl(dealId, `/${encodeURIComponent(receiptId)}/attachments/${index}`);
}

export function inboxUrl(suffix = "") {
  return `/api/sales/mail/inbox${suffix}`;
}

export function inboxAttachmentUrl(receiptId: string, index: number) {
  return inboxUrl(`/${encodeURIComponent(receiptId)}/attachments/${index}`);
}

export function fetchIncomingPage(dealId: string, offset = 0, limit = 50) {
  return requestJson<IncomingPage>(queryUrl(incomingUrl(dealId), offset, limit));
}

export function fetchIncomingDetail(dealId: string, receiptId: string) {
  return requestJson<IncomingEmailDetail>(incomingUrl(dealId, `/${encodeURIComponent(receiptId)}`));
}

export function fetchInboxPage(offset = 0, limit = 50) {
  return requestJson<IncomingPage>(queryUrl(inboxUrl(), offset, limit));
}

export function fetchInboxDetail(receiptId: string) {
  return requestJson<IncomingEmailDetail>(inboxUrl(`/${encodeURIComponent(receiptId)}`));
}

export async function fetchSalesDeals() {
  const payload = await requestJson<unknown>("/api/sales/deals");
  if (!Array.isArray(payload)) throw new Error("CRM вернула некорректный список сделок");
  return payload.filter((value): value is SalesDealOption => {
    if (!value || typeof value !== "object") return false;
    const deal = value as Partial<SalesDealOption>;
    return Number.isSafeInteger(deal.id) && (deal.id as number) > 0
      && typeof deal.number === "string" && typeof deal.title === "string"
      && typeof deal.counterparty === "string"
      && (deal.owner == null || typeof deal.owner === "string");
  });
}

export function assignInboxEmail(receiptId: string, dealId: number) {
  return requestJson<IncomingEmail>(inboxUrl(`/${encodeURIComponent(receiptId)}/assign`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ deal_id: dealId }),
  });
}
