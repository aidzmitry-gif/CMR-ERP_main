import { fetchRegisterDocument } from "./document-register-api";

export type Scope = { organization_id: number; deal_id: number; document_id: number };
export type Identity = { organization_id: number; document_id: number; document_version: number; content_sha256: string };
export type Line = { line_no: number; sku_code: string; warehouse: string; original_qty: string; remaining_qty: string; physical: string | null; reserved: string | null; free: string | null; blocking_reason: null | "fully_shipped" | "remainder_released" | "physical_stock_unknown" | "physical_reserves_exceed_stock" };
export type Preview = { identity: Identity; lines: Line[]; reservation_digest: string; remaining_digest: string; physical_digest: string };
export type Body = { source_key: string; expected_version: number; expected_content_sha256: string; expected_reservation_digest: string; expected_remaining_digest: string; expected_physical_digest: string; operation_date: string; evidence: string; lines: { line_no: number; warehouse: string; qty: string }[] };
export type Pending = { scope: Scope; body: Body; skus: { line_no: number; warehouse: string; sku_code: string }[] };
export type Receipt = { act_id: number; source_key: string; digest: string; request_hash: string; snapshot: { organization_id: number; document_id: number; document_version: number; content_sha256: string; source_key: string; request_hash: string; reservation_digest: string; kind: string; operation_date: string; evidence: string; actor: string; lines: { line_no: number; warehouse: string; sku_code: string; qty: string; movement_id: number; before_id: number; after_id: number; source: string }[] } };
const obj = (x: unknown): x is Record<string, unknown> => !!x && typeof x === "object" && !Array.isArray(x);
const id = (x: unknown): x is number => typeof x === "number" && Number.isSafeInteger(x) && x > 0;
const hash = (x: unknown): x is string => typeof x === "string" && /^[a-f0-9]{64}$/.test(x);
const uuid = (x: unknown): x is string => typeof x === "string" && /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(x);
const amount = (x: unknown): x is string => typeof x === "string" && /^-?\d{1,12}\.\d{2}$/.test(x);
export const lineKey = (x: { line_no: number; warehouse: string }) => JSON.stringify([x.line_no, x.warehouse]);
export function units(x: string): bigint {
  if (!/^\d{1,12}(?:\.\d{1,2})?$/.test(x)) throw new Error("Укажите количество с точностью до сотых.");
  const [whole, fraction = ""] = x.split(".");
  return BigInt(whole) * BigInt(100) + BigInt(fraction.padEnd(2, "0"));
}
export function quantity(x: string): string {
  const n = units(x);
  if (n <= BigInt(0) || n >= BigInt("100000000000000")) throw new Error("Количество должно быть положительным.");
  return `${n / BigInt(100)}.${String(n % BigInt(100)).padStart(2, "0")}`;
}
export function today() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; }
export class ShipmentError extends Error {
  constructor(message: string, readonly status?: number, readonly code?: string) { super(message); }
}
function invalid(): never { throw new ShipmentError("Ответ не соответствует выбранному счёту или операции. Результат требует проверки."); }
function base(s: Scope) {
  if (![s.organization_id, s.document_id, s.deal_id].every(id)) invalid();
  return `/api/wms/organizations/${s.organization_id}/invoices/${s.document_id}/physical-shipments`;
}
async function json(url: string, body?: unknown) {
  let r: Response;
  try { r = await fetch(url, { cache: "no-store", ...(body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) }); }
  catch { throw new ShipmentError("Связь прервана. Результат операции пока неизвестен."); }
  let data: unknown;
  try { data = await r.json(); } catch { throw new ShipmentError("Не удалось прочитать ответ. Результат операции требует проверки."); }
  if (!r.ok) {
    const messages: Record<number, string> = { 401: "Войдите в систему.", 403: "Недостаточно прав для этого юрлица или действия.", 404: "Акт пока не найден. Запрос ещё мог выполняться.", 409: "Основания или состояние операции изменились.", 422: "Проверьте дату, строки и количества." };
    throw new ShipmentError(messages[r.status] || "Сервис недоступен. Результат требует проверки.", r.status, obj(data) && typeof data.detail === "string" ? data.detail : undefined);
  }
  return data;
}
export function parsePreview(x: unknown, expected: Identity): Preview {
  if (!obj(x) || !obj(x.identity) || Object.entries(expected).some(([k,v]) => x.identity && (x.identity as Record<string,unknown>)[k] !== v)
    || ![x.reservation_digest,x.remaining_digest,x.physical_digest].every(hash) || !Array.isArray(x.lines) || !x.lines.length) invalid();
  const seen = new Set<string>();
  for (const r of x.lines) {
    if (!obj(r) || !id(r.line_no) || typeof r.sku_code !== "string" || !r.sku_code || typeof r.warehouse !== "string" || !r.warehouse
      || !amount(r.original_qty) || !amount(r.remaining_qty) || ![r.physical,r.reserved,r.free].every(v => v === null || amount(v))
      || ![null,"fully_shipped","remainder_released","physical_stock_unknown","physical_reserves_exceed_stock"].includes(r.blocking_reason as string | null)) invalid();
    if (units(r.original_qty) <= BigInt(0) || units(r.remaining_qty) > units(r.original_qty)) invalid();
    if (["fully_shipped", "remainder_released"].includes(r.blocking_reason as string) && units(r.remaining_qty) !== BigInt(0)) invalid();
    const key = lineKey(r as Line); if (seen.has(key)) invalid(); seen.add(key);
    if (r.blocking_reason === null && (units(r.remaining_qty) === BigInt(0) || r.physical === null || r.free === null || (r.free as string).startsWith("-"))) invalid();
  }
  return x as Preview;
}
export async function previewShipment(s: Scope) {
  const row = await fetchRegisterDocument(String(s.organization_id), String(s.deal_id), s.document_id);
  if (row.kind !== "invoice" || !hash(row.content_sha256)) throw new ShipmentError("Для отгрузки нужен сохранённый оригинал счёта.");
  const identity = { organization_id: s.organization_id, document_id: s.document_id, document_version: row.version, content_sha256: row.content_sha256 };
  return parsePreview(await json(`${base(s)}/preview`, { expected_version: row.version, expected_content_sha256: row.content_sha256 }), identity);
}
export function prepare(s: Scope, p: Preview, values: Record<string,string>, date: string, evidence: string): Pending {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || date > today() || !Number.isFinite(Date.parse(date)) || new Date(`${date}T12:00:00Z`).toISOString().slice(0,10) !== date) throw new ShipmentError("Укажите действительную дату, не позднее сегодняшней.");
  if (!evidence.trim() || evidence.length > 1000) throw new ShipmentError("Укажите основание отгрузки (до 1000 символов).");
  const selected = p.lines.filter(l => (values[lineKey(l)] || "").trim() !== "");
  if (!selected.length) throw new ShipmentError("Укажите количество хотя бы одной строки.");
  const lines = selected.map(l => { const qty = quantity(values[lineKey(l)]); if (l.blocking_reason || units(qty) > units(l.remaining_qty)) throw new ShipmentError("Количество превышает доступный остаток строки."); return { line_no:l.line_no,warehouse:l.warehouse,qty }; });
  return { scope:s, body: { source_key:crypto.randomUUID(),expected_version:p.identity.document_version,expected_content_sha256:p.identity.content_sha256,expected_reservation_digest:p.reservation_digest,expected_remaining_digest:p.remaining_digest,expected_physical_digest:p.physical_digest,operation_date:date,evidence:evidence.trim(),lines }, skus:selected.map(l => ({line_no:l.line_no,warehouse:l.warehouse,sku_code:l.sku_code})) };
}
function canonical(x: unknown): string {
  if (Array.isArray(x)) return `[${x.map(canonical).join(",")}]`;
  if (obj(x)) return `{${Object.keys(x).sort().map(k => `${JSON.stringify(k)}:${canonical(x[k])}`).join(",")}}`;
  return JSON.stringify(x);
}
export async function fingerprint(x: unknown) { return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(x))))).map(b=>b.toString(16).padStart(2,"0")).join(""); }
export async function verifyReceipt(x: unknown, p: Pending): Promise<Receipt> {
  if (!obj(x) || !id(x.act_id) || x.source_key !== p.body.source_key || !hash(x.digest) || !hash(x.request_hash) || !obj(x.snapshot)) invalid();
  const snap = x.snapshot;
  if (snap.organization_id !== p.scope.organization_id || snap.document_id !== p.scope.document_id || snap.document_version !== p.body.expected_version
    || snap.content_sha256 !== p.body.expected_content_sha256 || snap.reservation_digest !== p.body.expected_reservation_digest
    || snap.source_key !== p.body.source_key || snap.request_hash !== x.request_hash || snap.operation_date !== p.body.operation_date
    || snap.evidence !== p.body.evidence || snap.kind !== "internal_physical_shipment" || typeof snap.actor !== "string" || !snap.actor
    || !Array.isArray(snap.lines) || snap.lines.length !== p.body.lines.length) invalid();
  const seen = new Set<string>(); const movementIds = new Set<number>();
  for (const l of snap.lines) {
    if (!obj(l) || !id(l.line_no) || typeof l.warehouse !== "string") invalid();
    const key = lineKey(l as Body["lines"][number]), expected = p.body.lines.find(e=>lineKey(e) === key), sku = p.skus.find(e=>lineKey(e) === key);
    if (!expected || !sku || seen.has(key) || l.qty !== expected.qty || l.sku_code !== sku.sku_code || ![l.movement_id,l.before_id,l.after_id].every(id) || typeof l.source !== "string" || !l.source || movementIds.has(l.movement_id as number)) invalid();
    seen.add(key); movementIds.add(l.movement_id as number);
  }
  if (await fingerprint(snap) !== x.digest || await fingerprint({ organization_id:p.scope.organization_id, document_id:p.scope.document_id, data:p.body }) !== x.request_hash) invalid();
  return x as Receipt;
}
export async function createShipment(p: Pending) { return verifyReceipt(await json(base(p.scope),p.body),p); }
export async function findShipment(p: Pending) { return verifyReceipt(await json(`${base(p.scope)}/by-key/${p.body.source_key}`),p); }
export const storageKey = (s: Scope) => `wms-physical-pending:v1:${s.organization_id}:${s.deal_id}:${s.document_id}`;
export function savePending(p: Pending) { const raw=JSON.stringify(p); sessionStorage.setItem(storageKey(p.scope),raw); if(sessionStorage.getItem(storageKey(p.scope))!==raw) throw new ShipmentError("Не удалось сохранить запрос для восстановления. Отправка остановлена."); }
export function loadPending(s: Scope): Pending | null {
  const raw = sessionStorage.getItem(storageKey(s)); if (!raw) return null;
  const p: unknown = JSON.parse(raw);
  if (!obj(p) || !obj(p.scope) || Object.entries(s).some(([k,v])=>(p.scope as Record<string,unknown>)[k]!==v) || !obj(p.body) || !Array.isArray(p.skus)) invalid();
  const b=p.body;
  if (!uuid(b.source_key) || !id(b.expected_version) || ![b.expected_content_sha256,b.expected_reservation_digest,b.expected_remaining_digest,b.expected_physical_digest].every(hash)
    || typeof b.operation_date!=="string" || typeof b.evidence!=="string" || !Array.isArray(b.lines) || !b.lines.length || b.lines.length!==p.skus.length) invalid();
  const keys=new Set<string>();
  for(const l of b.lines) { if(!obj(l)||!id(l.line_no)||typeof l.warehouse!=="string"||!l.warehouse||!amount(l.qty)||quantity(l.qty)!==l.qty) invalid(); const k=lineKey(l as Body["lines"][number]); if(keys.has(k)) invalid(); keys.add(k); if(!p.skus.some(v=>obj(v)&&v.line_no===l.line_no&&v.warehouse===l.warehouse&&typeof v.sku_code==="string"&&v.sku_code)) invalid(); }
  return p as Pending;
}
export function clearPending(expected: Pending) {
  const current = loadPending(expected.scope);
  if (current && JSON.stringify(current) === JSON.stringify(expected)) {
    sessionStorage.removeItem(storageKey(expected.scope));
  }
}

export async function shipmentIdentity(s: Scope): Promise<Identity> {
  const r=await fetchRegisterDocument(String(s.organization_id),String(s.deal_id),s.document_id);
  if(r.kind!=="invoice"||!hash(r.content_sha256)) invalid();
  return {organization_id:s.organization_id,document_id:s.document_id,document_version:r.version,content_sha256:r.content_sha256};
}
export async function shipmentHistory(s: Scope, identity: Identity, after=0): Promise<{items:Receipt[];next_after_id:number|null}> {
  const data=await json(`${base(s)}/history`,{expected_version:identity.document_version,expected_content_sha256:identity.content_sha256,after_id:after,limit:25});
  if(!obj(data)||!obj(data.identity)||Object.entries(identity).some(([k,v])=>(data.identity as Record<string,unknown>)[k]!==v)||!Array.isArray(data.items)||!(data.next_after_id===null||id(data.next_after_id))) invalid();
  const items:Receipt[]=[];
  for(const item of data.items){
    if(!obj(item)||!obj(item.snapshot)||!Array.isArray(item.snapshot.lines)||!uuid(item.source_key)||!id(item.act_id)||item.act_id<=(items.at(-1)?.act_id??after)) invalid();
    const snap=item.snapshot;
    if(snap.document_version!==identity.document_version||snap.content_sha256!==identity.content_sha256||!obj(snap.before)||!obj(snap.physical)||!hash(snap.reservation_digest)||typeof snap.operation_date!=="string"||typeof snap.evidence!=="string") invalid();
    const lines=snap.lines as Receipt["snapshot"]["lines"];
    if(lines.some(l=>!obj(l)||!id(l.line_no)||typeof l.warehouse!=="string"||typeof l.sku_code!=="string"||!amount(l.qty))) invalid();
    const p:Pending={scope:s,body:{source_key:item.source_key,expected_version:identity.document_version,expected_content_sha256:identity.content_sha256,expected_reservation_digest:snap.reservation_digest,expected_remaining_digest:await fingerprint(snap.before),expected_physical_digest:await fingerprint(snap.physical),operation_date:snap.operation_date,evidence:snap.evidence,lines:lines.map(l=>({line_no:l.line_no,warehouse:l.warehouse,qty:l.qty}))},skus:lines.map(l=>({line_no:l.line_no,warehouse:l.warehouse,sku_code:l.sku_code}))};
    // Request line order is not recorded separately; verify the immutable snapshot hash and identity.
    // Server validates historical request hash. Do not reconstruct an order-dependent request hash.
    const verifiedHash=await fingerprint(snap);
    if(item.digest!==verifiedHash||snap.organization_id!==s.organization_id||snap.document_id!==s.document_id||snap.source_key!==item.source_key||snap.request_hash!==item.request_hash||!hash(item.request_hash)||snap.kind!=="internal_physical_shipment"||typeof snap.actor!=="string"||!snap.actor) invalid();
    const keys=new Set<string>(), moves=new Set<number>();
    for(const l of lines){if(![l.movement_id,l.before_id,l.after_id].every(id)||keys.has(lineKey(l))||moves.has(l.movement_id)||quantity(l.qty)!==l.qty)invalid();keys.add(lineKey(l));moves.add(l.movement_id);}
    if(!p.body.lines.length) invalid();
    items.push(item as Receipt);
  }
  if(data.next_after_id!==null&&data.next_after_id!==items.at(-1)?.act_id) invalid();
  return {items,next_after_id:data.next_after_id as number|null};
}
