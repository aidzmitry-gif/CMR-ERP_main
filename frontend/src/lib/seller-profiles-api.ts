export type SellerSnapshot = { name: string; unp: string; currency: string; address: string; account: string; bank: string; bik: string; director: string; phone: string; email: string; logo_data_url: string; stamp_data_url: string | null; signature_data_url: string | null };
export type SellerProfile = { organization_id: number; profile_id: number; revision: number; effective_from: string; digest: string; seller: SellerSnapshot; evidence: string; actor: string };
export type SellerDraft = { effective_from: string; currency: string; address: string; account: string; bank: string; bik: string; director: string; phone: string; email: string; evidence: string; confirmed: boolean };
export type SellerRequest = SellerDraft & { source_key: string; expected_revision: number };
export class SellerProfileError extends Error { constructor(message: string, public status?: number) { super(message); } }
export const sellerId = (v: string) => /^[1-9]\d*$/.test(v) && Number.isSafeInteger(Number(v));
export const sellerCurrency = (v: string) => /^[A-Z]{3}$/.test(v);
export function sellerDate(v: string) { if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return false; const d = new Date(`${v}T00:00:00Z`); return !Number.isNaN(d.valueOf()) && d.toISOString().slice(0, 10) === v; }
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const positive = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v > 0;
const text = (v: unknown): v is string => typeof v === "string";
const nullableText = (v: unknown) => v === null || text(v);
function invalid(): never { throw new SellerProfileError("Некорректный ответ реквизитов или другое юрлицо. Результат не подтверждён."); }
function base(org: string) { if (!sellerId(org)) invalid(); return `/api/accounting/organizations/${org}`; }
export function sellerKey(): string {
  const crypto = globalThis.crypto;
  if (typeof crypto?.randomUUID === "function") return crypto.randomUUID();
  if (typeof crypto?.getRandomValues === "function") return Array.from(crypto.getRandomValues(new Uint8Array(32)), (b) => b.toString(16).padStart(2, "0")).join("");
  throw new SellerProfileError("Не удалось безопасно создать ключ запроса. Подтверждение не отправлено.");
}
export function validSellerDraft(v: SellerDraft) {
  const lengths = { address: 1000, account: 100, bank: 500, bik: 100, director: 300, evidence: 2000 } as const;
  return sellerDate(v.effective_from) && sellerCurrency(v.currency) && v.confirmed === true && Object.entries(lengths).every(([key, limit]) => { const s = v[key as keyof typeof lengths]; return text(s) && !!s.trim() && s.length <= limit; }) && text(v.phone) && v.phone.length <= 100 && text(v.email) && v.email.length <= 200;
}
async function request(url: string, body?: SellerRequest): Promise<unknown> {
  let res: Response;
  try { res = await fetch(url, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined }); }
  catch { throw new SellerProfileError(body ? "Результат отправки неизвестен. Повторите сохранённый запрос." : "Сеть недоступна. Реквизиты не загружены."); }
  if (!res.ok) {
    const messages: Record<number, string> = { 401: "Требуется вход в систему.", 403: "Недостаточно прав. Создание версии доступно главному бухгалтеру.", 404: "Юрлицо недоступно.", 409: "Требуется сверка: версия изменилась, реквизиты на дату отсутствуют либо валюта неизвестна/неактивна.", 422: "Проверьте поля и явное подтверждение.", 503: "Сервис реквизитов недоступен." };
    throw new SellerProfileError(`${res.status}: ${messages[res.status] || "Сервер не подтвердил результат."}`, res.status);
  }
  try { return await res.json(); } catch { invalid(); }
}
function profile(v: unknown, org: string): SellerProfile {
  if (!object(v) || v.organization_id !== Number(org) || !positive(v.profile_id) || !positive(v.revision) || !text(v.effective_from) || !sellerDate(v.effective_from) || !text(v.digest) || !/^[a-f0-9]{64}$/.test(v.digest) || !text(v.evidence) || !text(v.actor) || !object(v.seller)) invalid();
  const s = v.seller;
  if (!["name", "unp", "currency", "address", "account", "bank", "bik", "director", "phone", "email", "logo_data_url"].every((k) => text(s[k])) || !sellerCurrency(String(s.currency)) || !nullableText(s.stamp_data_url) || !nullableText(s.signature_data_url)) invalid();
  return v as SellerProfile;
}
export async function fetchSellerHistory(org: string): Promise<SellerProfile[]> {
  const value = await request(`${base(org)}/seller-profiles`); if (!Array.isArray(value) || value.length > 100) invalid();
  const rows = value.map((v) => profile(v, org));
  if (rows.some((r, i) => i > 0 && r.revision >= rows[i - 1].revision) || new Set(rows.map((r) => r.profile_id)).size !== rows.length) invalid();
  return rows;
}
export async function fetchSellerCurrent(org: string, on: string, currency: string): Promise<SellerProfile> {
  if (!sellerDate(on) || !sellerCurrency(currency)) invalid();
  const row = profile(await request(`${base(org)}/seller-profile?${new URLSearchParams({ on, currency })}`), org);
  if (row.effective_from > on || row.seller.currency !== currency) invalid(); return row;
}
export async function createSellerProfile(org: string, body: SellerRequest): Promise<SellerProfile> {
  if (!validSellerDraft(body) || !body.source_key.trim() || body.source_key.length > 160 || !Number.isSafeInteger(body.expected_revision) || body.expected_revision < 0) invalid();
  // Name, UNP and actor are server owned, even if a caller supplies extra keys.
  const payload: SellerRequest = { source_key: body.source_key, expected_revision: body.expected_revision, effective_from: body.effective_from, currency: body.currency, address: body.address, account: body.account, bank: body.bank, bik: body.bik, director: body.director, phone: body.phone, email: body.email, evidence: body.evidence, confirmed: body.confirmed };
  const row = profile(await request(`${base(org)}/seller-profiles`, payload), org);
  if (row.revision !== body.expected_revision + 1 || row.effective_from !== body.effective_from || row.evidence !== body.evidence || !["currency", "address", "account", "bank", "bik", "director", "phone", "email"].every((k) => row.seller[k as keyof SellerSnapshot] === body[k as keyof SellerDraft])) invalid();
  return row;
}
