/** Exact durable loss commands. Browser storage is a recovery journal, never authority. */
export type LossState = "pending" | "finalized" | "withdrawn";
export type LossScope = { deal: number; org: number; principal: string };
export type LossContext = { deal_id: number; principal: string; organization_id: number | null;
  organization: { id: number; name: string; unp: string } | null; mapping_required: boolean;
  funnel: string; stage: string; lost_stage: string | null; pending_request_id: string | null;
  latest_request_id: string | null; latest_request_state: LossState | null };
export type InvoiceIdentity = { id: number; deal_id: number; kind: "invoice"; version: number;
  content_sha256: string | null; supersedes_id: number | null; superseded_by_id: number | null };
export type LossSnapshot = { funnel: string; stage: string; lost_stage: string | null; invoices: InvoiceIdentity[] };
export type InvoiceProgress = { document_id: number; status: string; reserve_status: string; ready?: boolean;
  blockers?: string[]; money?: { state: string; digest: string; received: string; refunded: string } };
export type LossPreview = { organization_id: number; deal_id: number; snapshot: LossSnapshot;
  composition_digest: string; pending_request_id: string | null; invoices: InvoiceProgress[] };
export type RequestBody = { organization_id: number; request_key: string; expected_composition_digest: string;
  reason_code: string; comment: string | null; finalize_if_empty: boolean };
export type ResolveBody = { request_key: string; expected_request_digest: string; evidence: string };
export type LossResolution = { resolution_id: string; request_id: string; action: "finalized" | "withdrawn";
  command: ResolveBody; command_hash: string; digest: string; actor: string; snapshot: {
    request_digest: string; organization_id: number; deal_id: number; from_stage: string; to_stage: string;
    funnel: string; composition: InvoiceIdentity[]; invoices: InvoiceProgress[] } };
export type LossRecord = { request_id: string; request_digest: string; state: LossState; organization_id: number;
  deal_id: number; command: RequestBody; command_hash: string; snapshot: LossSnapshot; actor: string;
  resolution: LossResolution | null; invoices?: InvoiceProgress[]; ready_to_finalize?: boolean };
export type LossAttempt = { version: 1; scope: LossScope; nonce: string; kind: "request" | "finalize" | "withdraw";
  requestId: string; body: string; hash: string; outcome: "pending" | "uncertain" | "rejected" | "done" };
export type Journal = { raw: string | null; attempt: LossAttempt | null };
export class LossError extends Error {
  constructor(message: string, readonly status?: number, readonly uncertain = false) { super(message); }
}
const obj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const id = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v > 0;
const uuid = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
const digest = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const str = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const state = (v: unknown): v is LossState => ["pending", "finalized", "withdrawn"].includes(String(v));
const nilId = (v: unknown) => v === null || id(v);
const nilUuid = (v: unknown) => v === null || uuid(v);
export const canonical = (v: unknown): string => JSON.stringify(v, (_key, value) => obj(value)
  ? Object.fromEntries(Object.keys(value).sort().map(k => [k, value[k]])) : value);
export async function hash(v: unknown): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new LossError("Для сохранения команды требуется защищённое соединение.");
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(v)))))
    .map(n => n.toString(16).padStart(2, "0")).join("");
}
function invalid(): never { throw new LossError("Ответ не соответствует сделке или сохранённой команде. Требуется сверка.", undefined, true); }
function checkScope(scope: LossScope) {
  if (!id(scope.deal) || !id(scope.org) || !str(scope.principal) || scope.principal.length > 200) invalid();
}
export function scopeOf(ctx: LossContext): LossScope {
  if (ctx.mapping_required || !ctx.organization_id) throw new LossError("Сначала подтвердите юрлицо сделки.");
  return { deal: ctx.deal_id, org: ctx.organization_id, principal: ctx.principal };
}
function prefix(scope: LossScope) { checkScope(scope); return `/api/sales/organizations/${scope.org}/deals/${scope.deal}`; }
async function request(url: string, options?: RequestInit): Promise<unknown> {
  let response: Response;
  try { response = await fetch(url, { cache: "no-store", ...options }); }
  catch { throw new LossError("Нет ответа сервера. Результат команды неизвестен; проверьте его или повторите исходную команду.", undefined, !!options?.method); }
  if (!response.ok) {
    const labels: Record<number, string> = { 401: "Войдите в систему.", 403: "Текущих прав на сделку или книгу недостаточно.",
      404: "Сделка или запрос недоступны.", 409: "Факты, пользователь или состояние запроса изменились. Обновите сведения.",
      422: "Проверьте обязательные поля.", 503: "Сервис временно недоступен." };
    throw new LossError(`${response.status}: ${labels[response.status] || "Ошибка сервера."}`, response.status, response.status >= 500);
  }
  try { return await response.json(); } catch { invalid(); }
}
export async function fetchLossContext(deal: string | number): Promise<LossContext> {
  if (!id(Number(deal))) invalid();
  const v = await request(`/api/sales/deals/${deal}/loss-context`);
  if (!obj(v) || v.deal_id !== Number(deal) || !str(v.principal) || !nilId(v.organization_id)
    || typeof v.mapping_required !== "boolean" || !str(v.funnel) || !str(v.stage)
    || !(v.lost_stage === null || str(v.lost_stage)) || !nilUuid(v.pending_request_id) || !nilUuid(v.latest_request_id)
    || !(v.latest_request_state === null || state(v.latest_request_state))) invalid();
  if (v.mapping_required ? v.organization_id !== null || v.organization !== null
    : !obj(v.organization) || !id(v.organization_id) || v.organization.id !== v.organization_id
      || !str(v.organization.name) || typeof v.organization.unp !== "string") invalid();
  return v as unknown as LossContext;
}
export async function requireScope(scope: LossScope) {
  const current = await fetchLossContext(scope.deal);
  if (current.principal !== scope.principal || current.organization_id !== scope.org || current.mapping_required)
    throw new LossError("Пользователь или юрлицо изменились. Исходная команда сохранена для первоначальной учётной записи.");
  return current;
}
function identities(v: unknown, deal: number): v is InvoiceIdentity[] {
  return Array.isArray(v) && v.every((d, i) => obj(d) && id(d.id) && d.deal_id === deal && d.kind === "invoice"
    && id(d.version) && (d.content_sha256 === null || digest(d.content_sha256)) && nilId(d.supersedes_id)
    && nilId(d.superseded_by_id) && (!i || v[i - 1].id < d.id));
}
function snapshot(v: unknown, deal: number): v is LossSnapshot {
  return obj(v) && str(v.funnel) && str(v.stage) && (v.lost_stage === null || str(v.lost_stage)) && identities(v.invoices, deal);
}
function invoiceRows(v: unknown, ids?: InvoiceIdentity[]): v is InvoiceProgress[] {
  return Array.isArray(v) && v.every(r => obj(r) && id(r.document_id) && str(r.status) && str(r.reserve_status)
    && (r.ready === undefined || typeof r.ready === "boolean")
    && (r.blockers === undefined || Array.isArray(r.blockers) && r.blockers.every(b => typeof b === "string"))
    && (r.money === undefined || obj(r.money) && str(r.money.state) && digest(r.money.digest)
      && typeof r.money.received === "string" && typeof r.money.refunded === "string"))
    && (!ids || v.length === ids.length && v.every((r, i) => r.document_id === ids[i].id));
}
export async function fetchLossPreview(scope: LossScope): Promise<LossPreview> {
  const v = await request(`${prefix(scope)}/loss-preview`);
  if (!obj(v) || v.organization_id !== scope.org || v.deal_id !== scope.deal || !snapshot(v.snapshot, scope.deal)
    || !digest(v.composition_digest) || await hash(v.snapshot) !== v.composition_digest
    || !nilUuid(v.pending_request_id) || !invoiceRows(v.invoices, v.snapshot.invoices)) invalid();
  return v as unknown as LossPreview;
}
function requestBody(v: unknown, scope: LossScope): v is RequestBody {
  return obj(v) && Object.keys(v).sort().join() === "comment,expected_composition_digest,finalize_if_empty,organization_id,reason_code,request_key"
    && v.organization_id === scope.org && uuid(v.request_key) && digest(v.expected_composition_digest)
    && str(v.reason_code) && v.reason_code === v.reason_code.trim() && v.reason_code.length <= 128
    && (v.comment === null || typeof v.comment === "string" && v.comment === v.comment.trim() && v.comment.length <= 2000)
    && typeof v.finalize_if_empty === "boolean";
}
function resolveBody(v: unknown): v is ResolveBody {
  return obj(v) && Object.keys(v).sort().join() === "evidence,expected_request_digest,request_key"
    && uuid(v.request_key) && digest(v.expected_request_digest) && str(v.evidence)
    && v.evidence === v.evidence.trim() && v.evidence.length <= 2000;
}
export async function validateResolution(v: unknown, scope: LossScope, record?: LossRecord): Promise<LossResolution> {
  if (!obj(v) || !uuid(v.resolution_id) || !uuid(v.request_id) || !["finalized", "withdrawn"].includes(String(v.action))
    || !resolveBody(v.command) || v.command.request_key !== v.resolution_id || await hash(v.command) !== v.command_hash
    || !digest(v.digest) || !str(v.actor) || !obj(v.snapshot) || v.snapshot.organization_id !== scope.org
    || v.snapshot.deal_id !== scope.deal || !str(v.snapshot.from_stage) || !str(v.snapshot.to_stage)
    || !str(v.snapshot.funnel) || !digest(v.snapshot.request_digest)
    || v.snapshot.request_digest !== v.command.expected_request_digest || !identities(v.snapshot.composition, scope.deal)
    || !invoiceRows(v.snapshot.invoices, v.snapshot.composition)) invalid();
  if (v.action === "finalized" && (v.snapshot.invoices as InvoiceProgress[]).some(r => r.ready !== true || r.blockers?.length !== 0)) invalid();
  if (record && (v.request_id !== record.request_id || v.snapshot.request_digest !== record.request_digest
    || canonical(v.snapshot.composition) !== canonical(record.snapshot.invoices)
    || v.snapshot.funnel !== record.snapshot.funnel || v.snapshot.from_stage !== record.snapshot.stage
    || v.snapshot.to_stage !== (v.action === "finalized" ? record.snapshot.lost_stage : record.snapshot.stage))) invalid();
  if (await hash({ id: v.resolution_id, request_id: v.request_id, action: v.action, command: v.command,
    command_hash: v.command_hash, snapshot: v.snapshot, actor: v.actor }) !== v.digest) invalid();
  return v as unknown as LossResolution;
}
export async function validateRecord(v: unknown, scope: LossScope): Promise<LossRecord> {
  if (!obj(v) || v.deal_id !== scope.deal || v.organization_id !== scope.org || !uuid(v.request_id) || !state(v.state)
    || !requestBody(v.command, scope) || v.command.request_key !== v.request_id || await hash(v.command) !== v.command_hash
    || !snapshot(v.snapshot, scope.deal) || !str(v.snapshot.lost_stage) || !digest(v.request_digest) || !str(v.actor)
    || await hash(v.snapshot) !== v.command.expected_composition_digest) invalid();
  if (await hash({ id: v.request_id, organization_id: v.organization_id, deal_id: v.deal_id, command: v.command,
    command_hash: v.command_hash, snapshot: v.snapshot, actor: v.actor }) !== v.request_digest) invalid();
  if (v.state === "pending" ? v.resolution !== null : !v.resolution) invalid();
  const result = v as unknown as LossRecord;
  if (v.resolution) {
    result.resolution = await validateResolution(v.resolution, scope, result);
    if (result.resolution.action !== v.state) invalid();
  }
  if (v.invoices !== undefined && !invoiceRows(v.invoices, result.snapshot.invoices)) invalid();
  if (v.ready_to_finalize !== undefined && (typeof v.ready_to_finalize !== "boolean"
    || v.ready_to_finalize && (v.state !== "pending" || !result.invoices?.every(r => r.ready === true && r.blockers?.length === 0)))) invalid();
  return result;
}
export async function fetchLossProgress(scope: LossScope, requestId: string): Promise<LossRecord> {
  if (!uuid(requestId)) invalid();
  const result = await validateRecord(await request(`${prefix(scope)}/loss-requests/${requestId}`), scope);
  if (result.request_id !== requestId) invalid();
  return result;
}
const key = (s: LossScope) => `deal-loss:v1:${encodeURIComponent(s.principal)}:${s.org}:${s.deal}`;
export async function readLossJournal(scope: LossScope): Promise<Journal> {
  checkScope(scope);
  try {
    const raw = sessionStorage.getItem(key(scope));
    if (raw === null) return { raw, attempt: null };
    const v = JSON.parse(raw);
    if (!obj(v) || v.version !== 1 || canonical(v.scope) !== canonical(scope) || !uuid(v.nonce) || !uuid(v.requestId)
      || !["request", "finalize", "withdraw"].includes(String(v.kind)) || typeof v.body !== "string" || !digest(v.hash)
      || !["pending", "uncertain", "rejected", "done"].includes(String(v.outcome))) invalid();
    const body = JSON.parse(v.body);
    if (v.kind === "request" ? !requestBody(body, scope) || body.request_key !== v.requestId : !resolveBody(body)) invalid();
    if (await hash(body) !== v.hash) invalid();
    return { raw, attempt: v as unknown as LossAttempt };
  } catch { throw new LossError("Сохранённая команда недоступна или повреждена. Новая отправка остановлена; требуется сверка."); }
}
function cas(scope: LossScope, raw: string | null, next: LossAttempt): Journal {
  try {
    if (sessionStorage.getItem(key(scope)) !== raw) throw new Error();
    const saved = JSON.stringify(next); sessionStorage.setItem(key(scope), saved);
    if (sessionStorage.getItem(key(scope)) !== saved) throw new Error();
    return { raw: saved, attempt: next };
  } catch { throw new LossError("Журнал команды изменён или не сохраняется. Повторная отправка остановлена.", undefined, true); }
}
export async function beginLossCommand(scope: LossScope, kind: LossAttempt["kind"], body: RequestBody | ResolveBody,
  requestId: string, expectedRaw: string | null): Promise<Journal> {
  const saved = await readLossJournal(scope);
  if (saved.raw !== expectedRaw || saved.attempt && ["pending", "uncertain"].includes(saved.attempt.outcome))
    throw new LossError("Сначала установите результат исходной команды.");
  if (kind === "request" ? !requestBody(body, scope) || body.request_key !== requestId : !resolveBody(body)) invalid();
  const attempt: LossAttempt = { version: 1, scope, nonce: crypto.randomUUID(), kind, requestId,
    body: JSON.stringify(body), hash: await hash(body), outcome: "pending" };
  return cas(scope, saved.raw, attempt);
}
export async function dispatchLoss(journal: Journal, firstDispatch = false): Promise<{ journal: Journal; record?: LossRecord; resolution?: LossResolution }> {
  const a = journal.attempt;
  if (!a || !journal.raw || !["pending", "uncertain"].includes(a.outcome)) invalid();
  const saved = await readLossJournal(a.scope);
  if (saved.raw !== journal.raw) throw new LossError("Другая вкладка изменила команду.");
  await requireScope(a.scope);
  if ((await readLossJournal(a.scope)).raw !== journal.raw) throw new LossError("Команда изменилась до отправки.");
  const url = a.kind === "request" ? `/api/sales/deals/${a.scope.deal}/lose`
    : `${prefix(a.scope)}/loss-requests/${a.requestId}/${a.kind}`;
  let receivedSuccess = false;
  try {
    const v = await request(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": a.scope.principal }, body: a.body });
    receivedSuccess = true;
    let record: LossRecord | undefined, resolution: LossResolution | undefined;
    if (a.kind === "request") {
      record = await validateRecord(v, a.scope);
      if (record.request_id !== a.requestId || record.command_hash !== a.hash || canonical(record.command) !== canonical(JSON.parse(a.body))) invalid();
    } else {
      resolution = await validateResolution(v, a.scope);
      if (resolution.request_id !== a.requestId || resolution.command_hash !== a.hash
        || canonical(resolution.command) !== canonical(JSON.parse(a.body))
        || resolution.action !== (a.kind === "finalize" ? "finalized" : "withdrawn")) invalid();
    }
    await requireScope(a.scope);
    return { journal: cas(a.scope, journal.raw, { ...a, outcome: "done" }), record, resolution };
  } catch (error) {
    const knownRejection = !receivedSuccess && firstDispatch && error instanceof LossError && !!error.status && error.status >= 400 && error.status < 500;
    cas(a.scope, journal.raw, { ...a, outcome: knownRejection ? "rejected" : "uncertain" });
    throw error;
  }
}
export async function recoverLoss(journal: Journal): Promise<{ journal: Journal; record: LossRecord }> {
  const a = journal.attempt;
  if (!a || !journal.raw) invalid();
  await requireScope(a.scope);
  const record = await fetchLossProgress(a.scope, a.requestId);
  if (a.kind === "request" ? record.command_hash !== a.hash : !record.resolution || record.resolution.command_hash !== a.hash
    || record.resolution.action !== (a.kind === "finalize" ? "finalized" : "withdrawn"))
    throw new LossError("Исходная команда ещё не подтверждена. Можно повторить только её сохранённое тело.", undefined, true);
  await requireScope(a.scope);
  return { journal: cas(a.scope, journal.raw, { ...a, outcome: "done" }), record };
}
/** Check exact current funnel semantics before any board mutation. */
export async function lossGate(deal: string, target: string): Promise<boolean> {
  const ctx = await fetchLossContext(deal);
  if (ctx.pending_request_id || ctx.lost_stage === target) return true;
  const rows = await request("/api/sales/stages");
  if (!Array.isArray(rows) || !rows.every(r => obj(r) && str(r.code) && str(r.funnel) && str(r.kind) && typeof r.is_active === "boolean")) invalid();
  return rows.some(r => r.funnel === ctx.funnel && r.code === target && r.is_active && r.kind === "lost");
}
