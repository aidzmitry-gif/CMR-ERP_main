export type MoneyReceipt = { id: number; organization_id: number; document_id: number; basis_digest: string; history_from: string; history_through: string; actor: string; created_at: string; evidence: string; source_references: string[] };
export type MoneyReview = { organization_id: number; document_id: number; review_date: string; basis_digest: string; money_state: "no_receipts" | "funds_held" | "fully_refunded" | "history_unknown"; blockers: string[]; required_history_from: string; required_history_through: string; can_confirm_money_history: boolean; fulfillment_required: true; records: (MoneyReceipt & { current: boolean })[] };
export type MoneyConfirmation = { source_key: string; expected_basis_digest: string; history_from: string; history_through: string; evidence: string; source_references: string[]; all_money_sources_checked: boolean };
export class MoneyReconciliationError extends Error { constructor(message: string, public status?: number) { super(message); } }
export const moneyId = (v: string) => /^[1-9]\d*$/.test(v) && Number.isSafeInteger(Number(v));
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const digest = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
export function moneyDate(v: unknown): v is string {
  if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return false;
  const date = new Date(`${v}T00:00:00Z`); return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === v;
}
const references = (v: unknown): v is string[] => Array.isArray(v) && v.length >= 1 && v.length <= 100 && v.every((x) => typeof x === "string" && !!x.trim() && x === x.trim() && x.length <= 500) && new Set(v).size === v.length;
function invalid(): never { throw new MoneyReconciliationError("Некорректный ответ сверки или другой счёт/юрлицо. Подтверждение сервера не установлено."); }
function path(org: string, document: string) { if (!moneyId(org) || !moneyId(document)) invalid(); return `/api/sales/organizations/${org}/invoices/${document}/money-reconciliation`; }
async function request(url: string, body?: MoneyConfirmation): Promise<unknown> {
  let res: Response;
  try { res = await fetch(url, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined }); }
  catch { throw new MoneyReconciliationError(body ? "Результат отправки неизвестен. Повторите с тем же ключом и фактами." : "Не удалось загрузить сверку: сеть недоступна."); }
  if (!res.ok) {
    const labels: Record<number, string> = { 401: "Требуется вход.", 403: "Сверка доступна главному бухгалтеру с доступом к юрлицу и CRM.", 404: "Счёт недоступен в выбранном контексте.", 409: "Факты, период или ключ требуют новой проверки.", 422: "Проверьте период, основания и подтверждение всех источников.", 503: "Сервис сверки недоступен." };
    throw new MoneyReconciliationError(`${res.status}: ${labels[res.status] || "Сервер не подтвердил результат."}`, res.status);
  }
  try { return await res.json(); } catch { invalid(); }
}
function receipt(v: unknown, org: string, document: string): MoneyReceipt {
  if (!object(v) || !moneyId(String(v.id)) || v.organization_id !== Number(org) || v.document_id !== Number(document) || typeof v.id !== "number" || !digest(v.basis_digest) || !moneyDate(v.history_from) || !moneyDate(v.history_through) || v.history_from > v.history_through || typeof v.actor !== "string" || typeof v.created_at !== "string" || !v.created_at || typeof v.evidence !== "string" || !v.evidence.trim() || !references(v.source_references)) invalid();
  return v as MoneyReceipt;
}
export function validMoneyConfirmation(v: MoneyConfirmation, review: MoneyReview) {
  return !!v.source_key.trim() && v.source_key.length <= 160 && v.expected_basis_digest === review.basis_digest && moneyDate(v.history_from) && moneyDate(v.history_through) && v.history_from <= review.required_history_from && v.history_through >= review.required_history_through && v.history_through <= review.review_date && v.history_from <= v.history_through && !!v.evidence.trim() && v.evidence.length <= 2000 && references(v.source_references) && v.all_money_sources_checked === true && review.can_confirm_money_history;
}
export function moneyReviewKey(v: MoneyReview) { return JSON.stringify([v.organization_id, v.document_id, v.review_date, v.basis_digest, v.money_state, [...v.blockers].sort(), v.required_history_from, v.required_history_through, v.can_confirm_money_history]); }
export async function fetchMoneyReview(org: string, document: string): Promise<MoneyReview> {
  const v = await request(path(org, document));
  if (!object(v) || v.organization_id !== Number(org) || v.document_id !== Number(document) || !moneyDate(v.review_date) || !digest(v.basis_digest) || !["no_receipts", "funds_held", "fully_refunded", "history_unknown"].includes(String(v.money_state)) || !Array.isArray(v.blockers) || !v.blockers.every((x) => typeof x === "string") || !moneyDate(v.required_history_from) || !moneyDate(v.required_history_through) || v.required_history_from > v.required_history_through || typeof v.can_confirm_money_history !== "boolean" || v.fulfillment_required !== true || !Array.isArray(v.records) || v.records.length > 20) invalid();
  if (v.can_confirm_money_history && (v.blockers.length > 0 || !["no_receipts", "fully_refunded"].includes(String(v.money_state)) || v.required_history_through > v.review_date)) invalid();
  const records = v.records.map((r) => {
    const row = receipt(r, org, document); if (!object(r) || typeof r.current !== "boolean") invalid();
    if (r.current && (!v.can_confirm_money_history || row.basis_digest !== v.basis_digest || row.history_from > String(v.required_history_from) || row.history_through < String(v.required_history_through) || row.history_through > String(v.review_date))) invalid();
    return { ...row, current: r.current };
  });
  return { ...v, records } as MoneyReview;
}
export async function confirmMoneyHistory(org: string, document: string, body: MoneyConfirmation): Promise<MoneyReceipt> {
  if (!body.source_key.trim() || body.source_key.length > 160 || !digest(body.expected_basis_digest) || !moneyDate(body.history_from) || !moneyDate(body.history_through) || body.history_from > body.history_through || !body.evidence.trim() || body.evidence.length > 2000 || !references(body.source_references) || body.all_money_sources_checked !== true) invalid();
  const row = receipt(await request(path(org, document), body), org, document);
  if (row.basis_digest !== body.expected_basis_digest || row.history_from !== body.history_from || row.history_through !== body.history_through || row.evidence !== body.evidence || JSON.stringify(row.source_references) !== JSON.stringify(body.source_references)) invalid();
  return row;
}
