import { overheadAccess, sameOverheadCommand, validCostReview, validOverheadDate, type CostReviewCommand } from "./production-overhead-journal";

export type CorrectionPreviewCommand = { original_entry_id: number; review: CostReviewCommand; expected_review_digest: string;
  method: "delta"; posting_date: string; evidence: string };
export type CorrectionCommand = { request_key: string; preview: CorrectionPreviewCommand; expected_preview_digest: string };
export type PreparedCorrection = { command: CorrectionPreviewCommand; digest: string; createsEntry: boolean };
export type PendingCorrection = { org: string; principal: string; month: string; command: CorrectionCommand; withdrawal_reason?: string };
type ReceiptBase = { organization_id: number; month: string; actor: string; request_key: string; command: CorrectionCommand; final_cost_certified: false };
export type CorrectionReceipt = ReceiptBase & { id: number; sequence: number; original_entry_id: number; entry_id: number | null;
  confirmed: true; withdrawn: false; posted: boolean; preview: { digest: string; snapshot: { command: CorrectionPreviewCommand; creates_entry: boolean } } };
export type CorrectionWithdrawal = ReceiptBase & { confirmed: false; withdrawn: true; posted: false; reason: string };
type Outcome = CorrectionReceipt | CorrectionWithdrawal;
type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const key = (org: string, principal: string, month: string) => `production-correction:${JSON.stringify([org, principal, month])}`;
const id = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;
const text = (value: unknown, min: number, max: number) => typeof value === "string" && value === value.trim() && value.length >= min && value.length <= max;
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const shape = (value: unknown, keys: string[]) => !!value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).sort().join() === [...keys].sort().join();
function validate(item: PendingCorrection) {
  const c = item?.command, p = c?.preview;
  if (!shape(item, ["org", "principal", "month", "command", ...(item && Object.hasOwn(item, "withdrawal_reason") ? ["withdrawal_reason"] : [])])
    || (Object.hasOwn(item, "withdrawal_reason") && !text(item.withdrawal_reason, 10, 1000))
    || typeof item.org !== "string" || !/^[1-9]\d*$/.test(item.org) || !text(item.principal, 1, 200)
    || typeof item.month !== "string" || !/^\d{4}-\d{2}$/.test(item.month) || Number(item.month.slice(0, 4)) < 1
    || !shape(c, ["request_key", "preview", "expected_preview_digest"]) || typeof c.request_key !== "string"
    || !/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(c.request_key) || !digest(c.expected_preview_digest)
    || !shape(p, ["original_entry_id", "review", "expected_review_digest", "method", "posting_date", "evidence"])
    || !id(p.original_entry_id) || !digest(p.expected_review_digest) || p.method !== "delta" || !text(p.evidence, 10, 1000)
    || typeof p.posting_date !== "string" || !validOverheadDate(p.posting_date, item.month) || !validCostReview(p.review, true))
    throw new Error("Сохранённый запрос исправления повреждён.");
}
export function pendingCorrection(store: Store, org: string, principal: string, month: string): PendingCorrection | null {
  const raw = store.getItem(key(org, principal, month));
  if (raw === null) return null;
  const item = JSON.parse(raw) as PendingCorrection; validate(item);
  if (item.org !== org || item.principal !== principal || item.month !== month)
    throw new Error("Сохранённое исправление относится к другому юрлицу, месяцу или пользователю.");
  return item;
}
/** Distinguishes a confirmed zero calculation from withdrawal; neither creates an entry. */
export async function resolveCorrection(store: Store, item: PendingCorrection, postIfMissing: boolean, request: typeof fetch = fetch): Promise<Outcome | null> {
  validate(item);
  const storageKey = key(item.org, item.principal, item.month), previous = pendingCorrection(store, item.org, item.principal, item.month);
  const withdraw = previous && previous.withdrawal_reason === undefined && item.withdrawal_reason !== undefined
    && sameOverheadCommand({ ...previous, withdrawal_reason: item.withdrawal_reason }, item);
  if (previous && !sameOverheadCommand(previous, item) && !withdraw) throw new Error("Сначала проверьте сохранённое исправление.");
  const raw = previous && !withdraw ? store.getItem(storageKey)! : JSON.stringify(item);
  if (!previous || withdraw) store.setItem(storageKey, raw);
  const unchanged = () => { if (store.getItem(storageKey) !== raw) throw new Error("Запрос изменился или не был сохранён. Отправка остановлена."); };
  unchanged();
  const access = await overheadAccess(item.org, request);
  if (access.principal !== item.principal) throw new Error("Пользователь изменился. Исправление не отправлено.");
  const base = `/api/accounting/organizations/${item.org}`;
  async function check(): Promise<Outcome | null> {
    const response = await request(`${base}/production-overhead-correction-requests/${item.command.request_key}`, { cache: "no-store" });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error("Результат исправления пока не удалось проверить. Запрос сохранён.");
    const row = await response.json() as Outcome;
    if (!row || String(row.organization_id) !== item.org || row.month !== item.month || row.actor !== item.principal
      || row.request_key !== item.command.request_key || row.final_cost_certified !== false || !sameOverheadCommand(row.command, item.command))
      throw new Error("Квитанция не соответствует сохранённому исправлению.");
    if (row.confirmed === true) {
      if (row.withdrawn !== false || !id(row.id) || !id(row.sequence) || row.original_entry_id !== item.command.preview.original_entry_id
        || (row.posted === true ? !id(row.entry_id) : row.posted !== false || row.entry_id !== null)
        || row.preview?.digest !== item.command.expected_preview_digest || !sameOverheadCommand(row.preview?.snapshot?.command, item.command.preview)
        || row.preview.snapshot.creates_entry !== row.posted) throw new Error("Квитанция не подтверждает версию исправления.");
    } else if (row.confirmed !== false || row.withdrawn !== true || row.posted !== false || !text(row.reason, 10, 1000)
      || (item.withdrawal_reason !== undefined && row.reason !== item.withdrawal_reason)) throw new Error("Квитанция не подтверждает отзыв исправления.");
    return row;
  }
  let outcome = await check();
  if (!outcome && postIfMissing) {
    if (!access.can_confirm) throw new Error("Нет права подтверждать исправление. Запрос сохранён.");
    unchanged();
    const withdrawing = item.withdrawal_reason !== undefined;
    const response = await request(`${base}/periods/${item.month}/production-overhead-correction-${withdrawing ? "withdraw" : "confirm"}`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": item.principal },
      body: JSON.stringify(withdrawing ? { command: item.command, reason: item.withdrawal_reason } : item.command) });
    outcome = await check();
    if (!outcome) throw new Error(response.ok ? "Подтверждение пока не найдено. Проверьте сохранённое исправление повторно."
      : "Исправление не подтверждено. Проверьте источники или отзовите сохранённый запрос.");
  }
  if (outcome) {
    unchanged(); store.removeItem(storageKey);
    if (store.getItem(storageKey) !== null) throw new Error("Не удалось завершить сохранённое исправление.");
  }
  return outcome;
}
