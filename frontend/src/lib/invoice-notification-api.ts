import type { DocumentEmail } from "@/lib/document-email-api";

export type InvoiceNotificationEvent = "sales.invoice.expiring" | "sales.invoice.cancelled";
export type InvoiceNotificationState = "pending" | "blocked";

export type InvoiceNotification = {
  id: number;
  organization_id: number;
  deal_id: number;
  document_id: number;
  document_version: number;
  event_id: number;
  event_type: InvoiceNotificationEvent;
  business_key: string;
  channel: "email";
  recipient: string | null;
  state: InvoiceNotificationState;
  reason: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
};

export class InvoiceNotificationError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
  }
}

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const positive = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const nullableText = (value: unknown): value is string | null => value === null || typeof value === "string";
const eventTypes: InvoiceNotificationEvent[] = ["sales.invoice.expiring", "sales.invoice.cancelled"];

function id(value: string): boolean {
  return /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value));
}

function emailId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{8,64}$/.test(value);
}

function base(dealId: string): string {
  if (!id(dealId)) throw new InvoiceNotificationError("Некорректный ID сделки.");
  return `/api/sales/deals/${encodeURIComponent(dealId)}/invoice-notifications`;
}

async function request(path: string, method: "GET" | "POST" = "GET"): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, method === "GET" ? { cache: "no-store" } : { method });
  } catch {
    throw new InvoiceNotificationError("Сеть недоступна. Повторите операцию с уведомлением.");
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const labels: Record<number, string> = {
      401: "Войдите в систему.",
      403: "Недостаточно прав для уведомления.",
      404: "Уведомление или сделка недоступны.",
      409: "Состояние счёта изменилось. Обновите уведомления.",
      503: "Исходящая почта не настроена администратором.",
    };
    const detail = object(payload) && typeof payload.detail === "string" ? payload.detail : labels[response.status] || "Операция с уведомлением не выполнена.";
    throw new InvoiceNotificationError(`${response.status}: ${detail}`, response.status);
  }
  if (payload === null) throw new InvoiceNotificationError("Сервис вернул неполный ответ. Обновите уведомления.");
  return payload;
}

function parse(value: unknown, organizationId: number, dealId: number): InvoiceNotification {
  if (!object(value) || !positive(value.id) || value.organization_id !== organizationId || value.deal_id !== dealId
    || !positive(value.document_id) || !positive(value.document_version) || !positive(value.event_id)
    || !eventTypes.includes(value.event_type as InvoiceNotificationEvent) || typeof value.business_key !== "string"
    || value.channel !== "email" || !["pending", "blocked"].includes(value.state as string)
    || !nullableText(value.recipient) || !nullableText(value.reason) || !object(value.payload) || !nullableText(value.created_at)
    || (value.state === "pending" && (!value.recipient || value.reason !== null))
    || (value.state === "blocked" && (!value.reason || value.recipient !== null))) {
    throw new InvoiceNotificationError("Сервис вернул некорректное или чужое уведомление.");
  }
  if (value.created_at !== null && !Number.isFinite(Date.parse(value.created_at))) {
    throw new InvoiceNotificationError("Сервис вернул некорректную дату уведомления.");
  }
  return value as InvoiceNotification;
}

function parseEmail(value: unknown, dealId: string, expectedId?: string): DocumentEmail {
  if (!object(value) || !emailId(value.id) || value.deal_id !== Number(dealId)
    || (expectedId !== undefined && value.id !== expectedId) || !Array.isArray(value.to)
    || !Array.isArray(value.cc) || !Array.isArray(value.attachments) || typeof value.sender !== "string"
    || typeof value.subject !== "string" || typeof value.body !== "string" || typeof value.status !== "string"
    || !["prepared", "queued", "sending", "retry_wait", "accepted", "failed", "uncertain"].includes(value.status)
    || !nullableText(value.created_at) || !nullableText(value.accepted_at) || !nullableText(value.next_attempt_at)
    || typeof value.attempt_count !== "number" || !Number.isSafeInteger(value.attempt_count) || value.attempt_count < 0
    || !nullableText(value.last_reason) || !nullableText(value.message_id)
    || !value.to.every((item) => typeof item === "string") || !value.cc.every((item) => typeof item === "string")) {
    throw new InvoiceNotificationError("Сервис вернул некорректное письмо уведомления.");
  }
  return value as unknown as DocumentEmail;
}

export async function fetchInvoiceNotifications(organizationId: number, dealId: string, documentId: number): Promise<InvoiceNotification[]> {
  if (!positive(organizationId) || !positive(documentId) || !id(dealId)) throw new InvoiceNotificationError("Выберите точную сделку, юрлицо и счёт.");
  const value = await request(base(dealId));
  if (!Array.isArray(value)) throw new InvoiceNotificationError("Сервис вернул неполный реестр уведомлений.");
  return value.map((row) => parse(row, organizationId, Number(dealId))).filter((row) => row.document_id === documentId);
}

export async function prepareInvoiceNotificationEmail(organizationId: number, dealId: string, notificationId: number): Promise<DocumentEmail> {
  if (!positive(organizationId) || !positive(notificationId)) throw new InvoiceNotificationError("Некорректный идентификатор уведомления.");
  return parseEmail(await request(`${base(dealId)}/${notificationId}/prepare-email`, "POST"), dealId);
}

export async function sendInvoiceNotificationEmail(dealId: string, emailId: string): Promise<DocumentEmail> {
  if (!id(dealId) || !emailId || !/^[A-Za-z0-9_-]{8,64}$/.test(emailId)) throw new InvoiceNotificationError("Некорректный идентификатор письма.");
  return parseEmail(await request(`/api/sales/deals/${encodeURIComponent(dealId)}/emails/${encodeURIComponent(emailId)}/send`, "POST"), dealId, emailId);
}
