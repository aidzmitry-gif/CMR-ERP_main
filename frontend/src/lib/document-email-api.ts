export type EmailStatus = "prepared" | "queued" | "sending" | "retry_wait" | "accepted" | "failed" | "uncertain";
export interface EmailAttempt {
  number: number; status: EmailStatus; reason: string | null; smtp_code: number | null;
  started_at: string; finished_at: string | null; recipients: Record<string, number>;
}
export interface DocumentEmail {
  id: string; sender: string; to: string[]; cc: string[]; subject: string; body: string;
  attachments: { document_id: number; version: number; number: string; filename: string; size: number; sha256: string }[];
  status: EmailStatus; created_at: string; accepted_at: string | null; next_attempt_at: string | null;
  attempt_count: number; last_reason: string | null; message_id: string;
}
export interface EmailOptions {
  sender: string | null; configuration_error: string | null; enabled: boolean;
  documents: { id: number; kind: string; number: string; version: number | null; status: string;
    available: boolean; superseded_by_id: number | null }[];
}
export const EMAIL_STATUS: Record<EmailStatus, string> = {
  prepared: "Подготовлено — не отправлено", queued: "В очереди", sending: "Передаётся почтовому серверу",
  retry_wait: "Ожидает повторной попытки", accepted: "Принято почтовым сервером",
  failed: "Не отправлено", uncertain: "Результат отправки неизвестен",
};
export const EMAIL_REASON: Record<string, string> = {
  authentication_rejected: "Почтовый сервер отклонил авторизацию. Требуется администратор.",
  configuration_error: "Проверьте настройки корпоративной почты.",
  sender_configuration_changed: "Отправитель изменился. Требуется проверить настройки.",
  recipient_rejected: "Почтовый сервер отклонил получателя. Тело письма не передавалось.",
  sender_rejected: "Почтовый сервер отклонил отправителя.", data_rejected: "Почтовый сервер отказал в приёме письма.",
  connection_error: "Не удалось соединиться с почтовым сервером.",
  worker_interrupted: "Обработка прервалась; письмо могло быть принято сервером.",
  response_unknown: "Ответ сервера потерян после передачи письма.",
  message_too_large: "Письмо превышает допустимый размер.", server_size_limit: "Превышен лимит размера почтового сервера.",
  mime_integrity_error: "Нарушена контрольная сумма письма. Отправка остановлена.",
};
export function emailUrl(dealId: string, suffix = "") {
  return `/api/sales/deals/${encodeURIComponent(dealId)}/emails${suffix}`;
}
export async function emailRequest<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, body === undefined ? { cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof payload?.detail === "string" ? payload.detail : "Не удалось выполнить запрос CRM");
  if (payload === null) throw new Error("CRM вернула неполный ответ. Обновите историю отправки.");
  return payload as T;
}
