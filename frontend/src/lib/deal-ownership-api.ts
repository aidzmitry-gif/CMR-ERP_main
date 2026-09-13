import { registerId } from "./document-register-api";

export type OwnershipSnapshot = {
  deal_id: number; number: string; counterparty: string; owner_id: number | null;
  documents: { id: number; version: number; number: string; kind: string; amount: string; content_sha256: string | null; superseded_by_id: number | null }[];
};
export type OwnershipPreview = { assigned: boolean; snapshot: OwnershipSnapshot };
export type OwnershipCommand = { org: string; dealId: string; endpoint: string; body: string };
export class OwnershipError extends Error {
  constructor(message: string, readonly status?: number, readonly uncertain = false) { super(message); }
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const positive = (v: unknown) => typeof v === "number" && Number.isSafeInteger(v) && v > 0;
const nullableId = (v: unknown) => v === null || positive(v);
function base(org: string, deal: string) {
  if (!registerId(org) || !registerId(deal)) throw new OwnershipError("Выберите организацию и точную сделку.");
  return `/api/sales/organizations/${org}/deals/${deal}`;
}
function snapshot(v: unknown, deal: string): v is OwnershipSnapshot {
  return object(v) && v.deal_id === Number(deal) && typeof v.number === "string" && typeof v.counterparty === "string" && nullableId(v.owner_id)
    && Array.isArray(v.documents) && v.documents.every(d => object(d) && positive(d.id) && positive(d.version)
      && typeof d.number === "string" && typeof d.kind === "string" && typeof d.amount === "string" && /^-?\d+(\.\d+)?$/.test(d.amount)
      && (d.content_sha256 === null || typeof d.content_sha256 === "string") && nullableId(d.superseded_by_id));
}
const canonical = (v: unknown): string => JSON.stringify(v, (_key, value) => object(value) ? Object.fromEntries(Object.keys(value).sort().map(k => [k, value[k]])) : value);
async function request(endpoint: string, body?: string): Promise<unknown> {
  let res: Response;
  try { res = await fetch(endpoint, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body }); }
  catch { throw new OwnershipError(body ? "Результат подтверждения организации неизвестен. Повторите исходный запрос." : "Не удалось проверить принадлежность сделки.", undefined, Boolean(body)); }
  if (!res.ok) {
    const labels: Record<number, string> = { 401: "Войдите в систему.", 403: "Подтверждение организации доступно главному бухгалтеру с доступом к этой сделке и организации.", 404: "Сделка недоступна в выбранной организации.", 409: "Факты изменились или принадлежность уже подтверждена. Проверьте заново.", 422: "Проверьте основание и данные сделки.", 503: "Сервис организаций недоступен." };
    throw new OwnershipError(`${res.status}: ${labels[res.status] || "Ошибка проверки принадлежности."}`, res.status, Boolean(body) && res.status >= 500);
  }
  try { return await res.json(); } catch { throw new OwnershipError("Некорректный ответ о принадлежности сделки.", undefined, Boolean(body)); }
}
export async function previewOwnership(org: string, deal: string): Promise<OwnershipPreview> {
  const v = await request(`${base(org, deal)}/ownership-preview`);
  if (!object(v) || typeof v.assigned !== "boolean" || !snapshot(v.snapshot, deal)) throw new OwnershipError("Ответ относится к другой сделке или содержит некорректные данные.");
  return v as OwnershipPreview;
}
export function ownershipCommand(org: string, dealId: string, expected: OwnershipSnapshot, evidence: string): OwnershipCommand {
  const endpoint = `${base(org, dealId)}/ownership`;
  if (!snapshot(expected, dealId) || !evidence.trim() || evidence.trim().length > 1000) throw new OwnershipError("Проверьте просмотренные факты и основание.");
  return { org, dealId, endpoint, body: JSON.stringify({ expected_snapshot: expected, evidence: evidence.trim() }) };
}
function validate(v: unknown, deal: string): OwnershipCommand {
  if (!object(v) || typeof v.org !== "string" || v.dealId !== deal || typeof v.endpoint !== "string" || typeof v.body !== "string") throw new OwnershipError("Сохранённое подтверждение требует сверки.");
  const b = JSON.parse(v.body) as unknown;
  if (!object(b) || Object.keys(b).sort().join() !== "evidence,expected_snapshot" || typeof b.evidence !== "string"
    || !snapshot(b.expected_snapshot, deal) || v.endpoint !== ownershipCommand(v.org, deal, b.expected_snapshot, b.evidence).endpoint) throw new OwnershipError("Сохранённое подтверждение требует сверки.");
  return v as OwnershipCommand;
}
export async function claimOwnership(command: OwnershipCommand): Promise<void> {
  validate(command, command.dealId);
  const expected = JSON.parse(command.body);
  const v = await request(command.endpoint, command.body);
  if (!object(v) || v.organization_id !== Number(command.org) || v.deal_id !== Number(command.dealId)
    || !snapshot(v.snapshot, command.dealId) || canonical(v.snapshot) !== canonical(expected.expected_snapshot)
    || v.evidence !== expected.evidence || typeof v.actor !== "string" || !v.actor.trim()) throw new OwnershipError("Подтверждение не соответствует исходной сделке и фактам. Требуется повтор исходного запроса.", undefined, true);
}
const storageKey = (deal: string) => `erp-deal-ownership-pending-v1:${deal}`;
export function loadOwnership(deal: string): OwnershipCommand | null {
  try { const raw = sessionStorage.getItem(storageKey(deal)); return raw ? validate(JSON.parse(raw), deal) : null; }
  catch { throw new OwnershipError("Не удалось прочитать сохранённое подтверждение организации. Требуется сверка; новый запрос остановлен."); }
}
export function saveOwnership(command: OwnershipCommand): void {
  validate(command, command.dealId);
  if (loadOwnership(command.dealId)) throw new OwnershipError("Сначала подтвердите результат исходного запроса организации.");
  try { sessionStorage.setItem(storageKey(command.dealId), JSON.stringify(command)); }
  catch { throw new OwnershipError("Не удалось сохранить исходный запрос. Подтверждение не отправлено."); }
}
export function clearOwnership(deal: string): void { sessionStorage.removeItem(storageKey(deal)); }
