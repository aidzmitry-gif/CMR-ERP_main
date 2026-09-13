/** Exact WIP-to-finished-goods command retained until the ledger receipt is read back. */
export type OutputTransferCommand = {
  policy_id: number;
  order_id: number;
  analytical_order: string;
  department: string;
  warehouse: string;
  posting_date: string;
  output_document_ids: number[];
  basis_digest: string;
  digest: string;
};
export type OutputTransferDraft = Omit<OutputTransferCommand, "basis_digest" | "digest">;
export type PendingOutputTransfer = { org: string; principal: string; month: string; command: OutputTransferCommand };
export type OutputTransferReceipt = { organization_id: number; month: string; actor: string; order_id: number;
  basis_digest: string; digest: string; entry_id: number; entry?: { id: number }; posted: true; final_cost_certified: false };
type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const key = (org: string, principal: string, month: string) => `production-output-transfer:${JSON.stringify([org, principal, month])}`;
const id = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const text = (value: unknown, min: number, max: number) => typeof value === "string" && value === value.trim() && value.length >= min && value.length <= max;
const validDate = (value: unknown, month: string) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)
  && value.startsWith(`${month}-`) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;

function validate(item: PendingOutputTransfer) {
  const c = item?.command;
  if (!item || !Object.keys(item).every(name => ["org", "principal", "month", "command"].includes(name))
    || Object.keys(item).length !== 4 || typeof item.org !== "string" || !/^[1-9]\d*$/.test(item.org)
    || !text(item.principal, 1, 200) || typeof item.month !== "string" || !/^\d{4}-\d{2}$/.test(item.month)
    || !c || typeof c !== "object" || Array.isArray(c) || Object.keys(c).sort().join() !== ["policy_id", "order_id", "analytical_order", "department", "warehouse", "posting_date", "output_document_ids", "basis_digest", "digest"].sort().join()
    || !id(c.policy_id) || !id(c.order_id) || !text(c.analytical_order, 1, 200) || !text(c.department, 1, 200)
    || !text(c.warehouse, 1, 128) || !validDate(c.posting_date, item.month) || !Array.isArray(c.output_document_ids)
    || !c.output_document_ids.length || c.output_document_ids.length > 100 || c.output_document_ids.some(idValue => !id(idValue))
    || new Set(c.output_document_ids).size !== c.output_document_ids.length || !digest(c.basis_digest) || !digest(c.digest))
    throw new Error("Сохранённый перенос НЗП повреждён.");
}
export function pendingOutputTransfer(store: Store, org: string, principal: string, month: string): PendingOutputTransfer | null {
  const raw = store.getItem(key(org, principal, month)); if (raw === null) return null;
  const item = JSON.parse(raw) as PendingOutputTransfer; validate(item);
  if (item.org !== org || item.principal !== principal || item.month !== month) throw new Error("Сохранённый перенос относится к другому юрлицу, месяцу или пользователю.");
  return item;
}
async function access(org: string, request: typeof fetch) {
  const response = await request(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" });
  if (!response.ok) throw new Error("Не удалось проверить права переноса выпуска.");
  const row = await response.json();
  if (String(row?.organization_id) !== org || !text(row.principal, 1, 200) || typeof row.can_confirm !== "boolean") throw new Error("Ответ о правах повреждён.");
  return row as { organization_id: number; principal: string; can_confirm: boolean };
}
function receipt(item: PendingOutputTransfer, value: unknown): OutputTransferReceipt {
  const row = value as Partial<OutputTransferReceipt> | null;
  if (!row || String(row.organization_id) !== item.org || row.month !== item.month || row.actor !== item.principal
    || row.order_id !== item.command.order_id || row.basis_digest !== item.command.basis_digest || row.digest !== item.command.digest
    || row.posted !== true || row.final_cost_certified !== false || !id(row.entry_id) || (row.entry && row.entry.id !== row.entry_id))
    throw new Error("Квитанция не подтверждает сохранённый перенос НЗП.");
  return row as OutputTransferReceipt;
}
export async function resolveOutputTransfer(store: Store, item: PendingOutputTransfer, postIfMissing: boolean,
  request: typeof fetch = fetch): Promise<OutputTransferReceipt | null> {
  validate(item);
  const storageKey = key(item.org, item.principal, item.month), previous = pendingOutputTransfer(store, item.org, item.principal, item.month);
  if (previous && JSON.stringify(previous) !== JSON.stringify(item)) throw new Error("Сначала проверьте сохранённый перенос НЗП.");
  const raw = previous ? store.getItem(storageKey)! : JSON.stringify(item); if (!previous) store.setItem(storageKey, raw);
  const unchanged = () => { if (store.getItem(storageKey) !== raw) throw new Error("Сохранённый перенос изменился. Отправка остановлена."); };
  unchanged(); const current = await access(item.org, request);
  if (current.principal !== item.principal) throw new Error("Пользователь изменился. Перенос не отправлен.");
  const base = `/api/accounting/organizations/${item.org}/periods/${item.month}`;
  async function check() {
    const response = await request(`${base}/production-output-transfer-status/${item.command.order_id}`, { cache: "no-store" });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error("Результат переноса пока не удалось проверить. Запрос сохранён.");
    return receipt(item, await response.json());
  }
  let result = await check();
  if (!result && postIfMissing) {
    if (!current.can_confirm) throw new Error("Нет права проводить перенос выпуска. Запрос сохранён.");
    unchanged();
    const response = await request(`${base}/production-output-transfer-confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(item.command) });
    result = await check();
    if (!result) throw new Error(response.ok ? "Перенос пока не подтверждён. Проверьте сохранённый запрос повторно." : "Сервер не подтвердил перенос НЗП.");
  }
  if (result) { unchanged(); store.removeItem(storageKey); if (store.getItem(storageKey) !== null) throw new Error("Не удалось завершить сохранённый перенос."); }
  return result;
}
