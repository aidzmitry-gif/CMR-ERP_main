/** Retain the exact reviewed command until its immutable server receipt is read back. */
export type CostReviewCommand = {
  policy_id: number; expected_source_digest: string;
  classifications: { line_id: number; role: "direct_cost" | "overhead" | "excluded"; evidence: string }[];
  orders: { analytical_order: string; order_id: number; evidence: string }[];
};
export type OverheadCommand = { request_key: string; review: CostReviewCommand; expected_review_digest: string; posting_date: string; evidence: string };
export type PendingOverhead = { org: string; principal: string; month: string; command: OverheadCommand; withdrawal_reason?: string };
export type OverheadReceipt = { organization_id: number; month: string; actor: string; request_key: string; entry_id: number;
  command: OverheadCommand; posted: true; final_cost_certified: false };
export type OverheadWithdrawal = { organization_id: number; month: string; actor: string; request_key: string;
  command: OverheadCommand; posted: false; withdrawn: true; reason: string; final_cost_certified: false };
type Outcome = OverheadReceipt | OverheadWithdrawal;
type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const key = (org: string, principal: string, month: string) => `production-overhead:${JSON.stringify([org, principal, month])}`;
const id = (v: unknown) => Number.isSafeInteger(v) && (v as number) > 0;
const digest = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const text = (v: unknown, min: number, max: number) => typeof v === "string" && v === v.trim() && v.length >= min && v.length <= max;
const shape = (v: unknown, names: string[]) => !!v && typeof v === "object" && !Array.isArray(v)
  && Object.keys(v).sort().join() === [...names].sort().join();
export function sameOverheadCommand(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object" || Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => sameOverheadCommand(v, b[i]));
  const left = a as Record<string, unknown>, right = b as Record<string, unknown>;
  return Object.keys(left).length === Object.keys(right).length
    && Object.keys(left).every(k => Object.hasOwn(right, k) && sameOverheadCommand(left[k], right[k]));
}
export function validOverheadDate(value: string, month: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && value.startsWith(`${month}-`) && Number.isFinite(Date.parse(value))
    && new Date(value).toISOString().slice(0, 10) === value;
}
export function validCostReview(r: CostReviewCommand, allowEmptyOrders = false) {
  return !(!shape(r, ["policy_id", "expected_source_digest", "classifications", "orders"]) || !id(r.policy_id) || !digest(r.expected_source_digest)
    || !Array.isArray(r.classifications) || !r.classifications.length || r.classifications.length > 10000
    || r.classifications.some(row => !shape(row, ["line_id", "role", "evidence"]) || !id(row.line_id)
      || !["direct_cost", "overhead", "excluded"].includes(row.role) || !text(row.evidence, 10, 1000))
    || !Array.isArray(r.orders) || (!allowEmptyOrders && !r.orders.length) || r.orders.length > 1000
    || r.orders.some(row => !shape(row, ["analytical_order", "order_id", "evidence"]) || !id(row.order_id)
      || !text(row.analytical_order, 1, 200) || !text(row.evidence, 10, 1000))
    || new Set(r.classifications.map(row => row.line_id)).size !== r.classifications.length
    || new Set(r.orders.map(row => row.order_id)).size !== r.orders.length
    || new Set(r.orders.map(row => row.analytical_order)).size !== r.orders.length);
}
function validate(item: PendingOverhead) {
  const c = item?.command;
  if (!shape(item, ["org", "principal", "month", "command", ...(item && Object.hasOwn(item, "withdrawal_reason") ? ["withdrawal_reason"] : [])])
    || (Object.hasOwn(item, "withdrawal_reason") && !text(item.withdrawal_reason, 10, 1000))
    || typeof item.org !== "string" || !/^[1-9]\d*$/.test(item.org)
    || !text(item.principal, 1, 200) || typeof item.month !== "string" || !/^\d{4}-\d{2}$/.test(item.month) || Number(item.month.slice(0, 4)) < 1
    || !shape(c, ["request_key", "review", "expected_review_digest", "posting_date", "evidence"])
    || typeof c.request_key !== "string" || !/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(c.request_key)
    || !digest(c.expected_review_digest) || typeof c.posting_date !== "string" || !validOverheadDate(c.posting_date, item.month) || !text(c.evidence, 10, 1000)
    || !validCostReview(c.review))
    throw new Error("Сохранённый запрос распределения повреждён.");
}
export function pendingOverhead(store: Store, org: string, principal: string, month: string): PendingOverhead | null {
  const raw = store.getItem(key(org, principal, month));
  if (raw === null) return null;
  const item = JSON.parse(raw) as PendingOverhead; validate(item);
  if (item.org !== org || item.principal !== principal || item.month !== month)
    throw new Error("Сохранённое распределение относится к другому юрлицу, периоду или пользователю.");
  return item;
}
export async function overheadAccess(org: string, request: typeof fetch = fetch) {
  const response = await request(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" });
  if (!response.ok) throw new Error("Не удалось проверить права распределения.");
  const row = await response.json();
  if (String(row?.organization_id) !== org || !text(row.principal, 1, 200) || typeof row.can_confirm !== "boolean")
    throw new Error("Ответ о правах относится к другому юрлицу или повреждён.");
  return row as { organization_id: number; principal: string; can_confirm: boolean };
}
/** postIfMissing=false is a read-only recovery check; a reload never submits a command. */
export async function resolveOverhead(store: Store, item: PendingOverhead, postIfMissing: boolean,
  request: typeof fetch = fetch): Promise<Outcome | null> {
  validate(item);
  const storageKey = key(item.org, item.principal, item.month);
  const previous = pendingOverhead(store, item.org, item.principal, item.month);
  const beginsWithdrawal = previous && previous.withdrawal_reason === undefined && item.withdrawal_reason !== undefined
    && sameOverheadCommand({ ...previous, withdrawal_reason: item.withdrawal_reason }, item);
  if (previous && !sameOverheadCommand(previous, item) && !beginsWithdrawal) throw new Error("Сначала проверьте результат сохранённого распределения.");
  const raw = previous && !beginsWithdrawal ? store.getItem(storageKey)! : JSON.stringify(item);
  if (!previous || beginsWithdrawal) store.setItem(storageKey, raw);
  const unchanged = () => { if (store.getItem(storageKey) !== raw) throw new Error("Сохранённый запрос изменился или не был сохранён. Отправка остановлена."); };
  unchanged();
  const access = await overheadAccess(item.org, request);
  if (access.principal !== item.principal) throw new Error("Пользователь изменился. Сохранённый запрос не отправлен.");
  const base = `/api/accounting/organizations/${item.org}`;
  async function check(): Promise<Outcome | null> {
    const response = await request(`${base}/production-overhead-requests/${item.command.request_key}`, { cache: "no-store" });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error("Результат распределения пока не удалось проверить. Запрос сохранён.");
    const row = await response.json() as Outcome & { withdrawn?: boolean };
    if (!row || String(row.organization_id) !== item.org || row.month !== item.month || row.actor !== item.principal
      || row.request_key !== item.command.request_key || row.final_cost_certified !== false
      || !sameOverheadCommand(row.command, item.command)) throw new Error("Квитанция не соответствует сохранённому распределению.");
    if (row.posted === true ? (!id(row.entry_id) || row.withdrawn === true)
      : (row.posted !== false || row.withdrawn !== true || !text(row.reason, 10, 1000)
        || (item.withdrawal_reason !== undefined && row.reason !== item.withdrawal_reason)))
      throw new Error("Квитанция не подтверждает результат проведения или отзыва запроса.");
    return row;
  }
  let receipt = await check();
  if (!receipt && postIfMissing) {
    if (!access.can_confirm) throw new Error("Нет права проводить распределение. Запрос сохранён.");
    unchanged();
    const withdrawing = item.withdrawal_reason !== undefined;
    const response = await request(`${base}/periods/${item.month}/production-overhead-${withdrawing ? "withdraw" : "confirm"}`, { method: "POST",
      headers: { "Content-Type": "application/json", "X-Expected-Principal": item.principal },
      body: JSON.stringify(withdrawing ? { command: item.command, reason: item.withdrawal_reason } : item.command) });
    // Even an error response can follow a committed transaction; only the GET receipt proves the outcome.
    receipt = await check();
    if (!receipt) throw new Error(response.ok ? "Распределение пока не подтверждено. Проверьте сохранённый запрос повторно."
      : "Сервер не подтвердил распределение. Проверьте актуальность источников и сохранённый запрос.");
  }
  if (receipt) {
    unchanged(); store.removeItem(storageKey);
    if (store.getItem(storageKey) !== null) throw new Error("Не удалось завершить сохранённый запрос.");
  }
  return receipt;
}
