import { fingerprint, shipmentIdentity, units, type Scope } from "./invoice-physical-shipment-api";

type Row = { source: string; qty: string; line_no: number; sku_code: string; warehouse: string };
type Basis = { reservation_digest: string; basis_digest: string; remaining: Row[]; acts: { id: number; digest: string }[] };
type Body = { source_key: string; expected_version: number; expected_content_sha256: string; expected_basis_digest: string; evidence: string };
export type RemainderRequest = { scope: Scope; basis: Basis; body: Body };
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const id = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v > 0;
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(v);
function invalid(): never { throw new Error("Основания снятия остатка не подтверждены. Требуется сверка."); }
const base = (s: Scope) => {
  if (![s.organization_id, s.deal_id, s.document_id].every(id)) invalid();
  return `/api/wms/organizations/${s.organization_id}/invoices/${s.document_id}/remainder-release`;
};
export class RemainderError extends Error { constructor(message: string, readonly code?: string) { super(message); } }
async function post(url: string, body: unknown): Promise<unknown> {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
  const value: unknown = await response.json();
  if (!response.ok) {
    const code = object(value) && typeof value.detail === "string" ? value.detail : undefined;
    const messages: Record<string, string> = {
      remainder_requires_physical_act: "Снятие остатка доступно после частичной отгрузки. Для неотгруженного счёта используйте аннулирование.",
      remainder_already_exhausted: "Неотгруженного резерва больше нет. Обновите основания отгрузки.",
      remainder_basis_changed: "После расчёта изменились резерв или акты. Получите новый расчёт.",
    };
    throw new RemainderError(response.status === 403 ? "Недостаточно прав для снятия остатка этого юрлица." : messages[code ?? ""] ?? "Снятие не подтверждено. Сохранённый запрос можно проверить повтором.", code);
  }
  return value;
}
function parseBasis(v: unknown): Basis {
  if (!object(v) || !hash(v.reservation_digest) || !hash(v.basis_digest) || !Array.isArray(v.remaining) || !v.remaining.length || !Array.isArray(v.acts) || !v.acts.length) invalid();
  const sources = new Set<string>();
  for (const row of v.remaining) {
    if (!object(row) || typeof row.source !== "string" || !row.source || sources.has(row.source) || !id(row.line_no) || typeof row.sku_code !== "string" || !row.sku_code || typeof row.warehouse !== "string" || !row.warehouse || typeof row.qty !== "string" || !/^\d{1,12}\.\d{2}$/.test(row.qty)) invalid();
    sources.add(row.source);
  }
  if (!v.remaining.some(row => units(row.qty) > BigInt(0)) || v.acts.some(a => !object(a) || !id(a.id) || !hash(a.digest))) invalid();
  return v as Basis;
}
export async function prepareRemainder(scope: Scope, evidence: string): Promise<RemainderRequest> {
  if (!evidence.trim() || evidence.length > 1000) throw new Error("Укажите причину снятия остатка (до 1000 символов).");
  const identity = await shipmentIdentity(scope);
  const body = { expected_version: identity.document_version, expected_content_sha256: identity.content_sha256 };
  const basis = parseBasis(await post(`${base(scope)}/preview`, body));
  return { scope, basis, body: { ...body, source_key: crypto.randomUUID(), expected_basis_digest: basis.basis_digest, evidence: evidence.trim() } };
}
const storageKey = (s: Scope) => `wms-remainder-pending:v1:${s.organization_id}:${s.deal_id}:${s.document_id}`;
export function loadRemainder(s: Scope): RemainderRequest | null {
  const raw = sessionStorage.getItem(storageKey(s));
  if (!raw) return null;
  const p: unknown = JSON.parse(raw);
  if (!object(p) || !object(p.scope) || Object.entries(s).some(([k,v]) => (p.scope as Record<string,unknown>)[k] !== v) || !object(p.body)) invalid();
  const b = p.body, basis = parseBasis(p.basis);
  if (!uuid(b.source_key) || !id(b.expected_version) || !hash(b.expected_content_sha256) || b.expected_basis_digest !== basis.basis_digest || typeof b.evidence !== "string" || !b.evidence.trim() || b.evidence.length > 1000) invalid();
  return p as RemainderRequest;
}
export function saveRemainder(p: RemainderRequest) {
  const raw = JSON.stringify(p), existing = sessionStorage.getItem(storageKey(p.scope));
  if (existing && existing !== raw) throw new Error("Для этого счёта уже сохранён другой запрос снятия. Сначала проверьте его результат.");
  sessionStorage.setItem(storageKey(p.scope), raw);
  if (sessionStorage.getItem(storageKey(p.scope)) !== raw) throw new Error("Не удалось сохранить запрос. Отправка остановлена.");
}
export function clearRemainder(p: RemainderRequest) {
  if (sessionStorage.getItem(storageKey(p.scope)) === JSON.stringify(p)) sessionStorage.removeItem(storageKey(p.scope));
}
export async function submitRemainder(p: RemainderRequest): Promise<number> {
  const value = await post(base(p.scope), p.body);
  if (!object(value) || !id(value.release_id) || !hash(value.digest) || !object(value.snapshot)) invalid();
  const s = value.snapshot;
  if (s.organization_id !== p.scope.organization_id || s.document_id !== p.scope.document_id || s.source_key !== p.body.source_key || s.evidence !== p.body.evidence || s.reservation_digest !== p.basis.reservation_digest || typeof s.actor !== "string" || !s.actor || !Array.isArray(s.lines)) invalid();
  if (await fingerprint(s) !== value.digest || await fingerprint({ organization_id:p.scope.organization_id, document_id:p.scope.document_id, data:p.body }) !== s.request_hash || await fingerprint({before:s.before,acts:s.acts}) !== p.body.expected_basis_digest || await fingerprint(s.acts) !== await fingerprint(p.basis.acts)) invalid();
  const rows = p.basis.remaining.filter(r => units(r.qty) > BigInt(0)), seen = new Set<string>();
  if (s.lines.length !== rows.length) invalid();
  for (const row of s.lines) {
    if (!object(row) || typeof row.source !== "string" || seen.has(row.source) || !id(row.before_id) || !id(row.after_id)) invalid();
    const expected = rows.find(r => r.source === row.source);
    if (!expected || row.qty !== expected.qty || row.line_no !== expected.line_no) invalid();
    seen.add(row.source);
  }
  return value.release_id;
}
