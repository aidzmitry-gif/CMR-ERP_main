/** Exact material-posting command retained until the matching ledger receipt is read back. */
export type MaterialPostingCommand = {
  zero_value?: boolean;
  policy_id: number;
  order_id: number;
  order_analytics: string;
  department: string;
  wms_movement_id: number;
  posting_date: string;
  account: string;
  warehouse: string;
  sku: string;
  lot: string;
  quantity: string;
  basis_digest: string;
  digest: string;
};
export type MaterialPostingDraft = Omit<MaterialPostingCommand, "basis_digest" | "digest">;

export type PendingMaterialPosting = {
  org: string;
  principal: string;
  month: string;
  command: MaterialPostingCommand;
};

export type MaterialPostingReceipt = {
  organization_id: number;
  month: string;
  actor: string;
  order_id: number;
  wms_movement_id: number;
  policy_id: number;
  basis_digest: string;
  digest: string;
  entry_id: number | null;
  entry?: { id: number } | null;
  posted: boolean;
  zero_value?: boolean;
  quantity_registered?: boolean;
  receipt_id?: number;
  receipt_digest?: string;
  final_cost_certified: false;
};

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;
// One active command per accountant/month keeps recovery discoverable after a reload;
// the movement id remains inside the immutable command and receipt.
const key = (org: string, principal: string, month: string) =>
  `production-material-posting:${JSON.stringify([org, principal, month])}`;
const id = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const text = (value: unknown, min: number, max: number) => typeof value === "string"
  && value === value.trim() && value.length >= min && value.length <= max;
const shape = (value: unknown, names: string[]) => !!value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).sort().join() === [...names].sort().join();
const dateInMonth = (value: unknown, month: string) => typeof value === "string"
  && /^\d{4}-\d{2}-\d{2}$/.test(value) && value.startsWith(`${month}-`)
  && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;

function validate(item: PendingMaterialPosting) {
  const c = item?.command;
  if (!shape(item, ["org", "principal", "month", "command"])
    || typeof item.org !== "string" || !/^[1-9]\d*$/.test(item.org)
    || !text(item.principal, 1, 200) || typeof item.month !== "string" || !/^\d{4}-\d{2}$/.test(item.month)
    || !shape(c, ["policy_id", "order_id", "order_analytics", "department", "wms_movement_id", "posting_date",
      "account", "warehouse", "sku", "lot", "quantity", "basis_digest", "digest", ...(c && Object.hasOwn(c, "zero_value") ? ["zero_value"] : [])])
    || (c?.zero_value !== undefined && typeof c.zero_value !== "boolean")
    || !id(c.policy_id) || !id(c.order_id) || !id(c.wms_movement_id)
    || !text(c.order_analytics, 1, 200) || !text(c.department, 1, 200)
    || !dateInMonth(c.posting_date, item.month) || !text(c.account, 1, 32) || !text(c.warehouse, 1, 200)
    || !text(c.sku, 1, 200) || !text(c.lot, 1, 200) || typeof c.quantity !== "string"
    || !/^\d+(?:\.\d{1,6})?$/.test(c.quantity) || Number(c.quantity) <= 0
    || !digest(c.basis_digest) || !digest(c.digest))
    throw new Error("Сохранённая проводка материала повреждена.");
}

export function pendingMaterialPosting(store: Store, org: string, principal: string, month: string, movement?: number): PendingMaterialPosting | null {
  const raw = store.getItem(key(org, principal, month));
  if (raw === null) return null;
  const item = JSON.parse(raw) as PendingMaterialPosting;
  validate(item);
  if (item.org !== org || item.principal !== principal || item.month !== month
    || (movement !== undefined && movement > 0 && item.command.wms_movement_id !== movement))
    throw new Error("Сохранённая проводка относится к другому юрлицу, периоду, пользователю или движению.");
  return item;
}

export async function materialPostingAccess(org: string, request: typeof fetch = fetch) {
  const response = await request(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" });
  if (!response.ok) throw new Error("Не удалось проверить права проведения материала.");
  const row = await response.json();
  if (String(row?.organization_id) !== org || !text(row.principal, 1, 200) || typeof row.can_confirm !== "boolean")
    throw new Error("Ответ о правах относится к другому юрлицу или повреждён.");
  return row as { organization_id: number; principal: string; can_confirm: boolean };
}

function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object" || Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => same(v, b[i]));
  const left = a as Record<string, unknown>, right = b as Record<string, unknown>;
  return Object.keys(left).length === Object.keys(right).length
    && Object.keys(left).every(k => Object.hasOwn(right, k) && same(left[k], right[k]));
}

function receiptFor(item: PendingMaterialPosting, value: unknown): MaterialPostingReceipt {
  const row = value as Partial<MaterialPostingReceipt> | null;
  if (!row || String(row.organization_id) !== item.org || row.month !== item.month || row.actor !== item.principal
    || row.order_id !== item.command.order_id || row.wms_movement_id !== item.command.wms_movement_id
    || row.policy_id !== item.command.policy_id || row.basis_digest !== item.command.basis_digest
    || row.digest !== item.command.digest || row.final_cost_certified !== false
    || (item.command.zero_value === true
      ? row.zero_value !== true || row.quantity_registered !== true || row.posted !== false
        || row.entry_id !== null || row.entry != null || !id(row.receipt_id) || !digest(row.receipt_digest)
      : row.posted !== true || row.zero_value === true || !id(row.entry_id) || (row.entry && row.entry.id !== row.entry_id)))
    throw new Error("Квитанция не подтверждает сохранённую проводку материала.");
  return row as MaterialPostingReceipt;
}

/** postIfMissing=false is read-only recovery; a reload never submits a command. */
export async function resolveMaterialPosting(store: Store, item: PendingMaterialPosting, postIfMissing: boolean,
  request: typeof fetch = fetch): Promise<MaterialPostingReceipt | null> {
  validate(item);
  const storageKey = key(item.org, item.principal, item.month);
  const previous = pendingMaterialPosting(store, item.org, item.principal, item.month);
  if (previous && !same(previous, item)) throw new Error("Сначала проверьте результат сохранённой проводки материала.");
  const raw = previous ? store.getItem(storageKey)! : JSON.stringify(item);
  if (!previous) store.setItem(storageKey, raw);
  const unchanged = () => { if (store.getItem(storageKey) !== raw) throw new Error("Сохранённая проводка изменилась или не была сохранена. Отправка остановлена."); };
  unchanged();
  const access = await materialPostingAccess(item.org, request);
  if (access.principal !== item.principal) throw new Error("Пользователь изменился. Проводка не отправлена.");
  const base = `/api/accounting/organizations/${item.org}/periods/${item.month}`;
  async function check(): Promise<MaterialPostingReceipt | null> {
    const response = await request(`${base}/production-material-issue-posting-status/${item.command.wms_movement_id}`, { cache: "no-store" });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error("Результат проводки материала пока не удалось проверить. Запрос сохранён.");
    return receiptFor(item, await response.json());
  }
  let receipt = await check();
  if (!receipt && postIfMissing) {
    if (!access.can_confirm) throw new Error("Нет права проводить материал. Запрос сохранён.");
    unchanged();
    const response = await request(`${base}/production-material-issue-confirm`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(item.command) });
    // A committed transaction may outlive a lost POST response; only the readback is terminal.
    receipt = await check();
    if (!receipt) throw new Error(response.ok ? "Проводка пока не подтверждена. Проверьте сохранённый запрос повторно."
      : "Сервер не подтвердил проводку материала. Проверьте источники и сохранённый запрос.");
  }
  if (receipt) {
    unchanged(); store.removeItem(storageKey);
    if (store.getItem(storageKey) !== null) throw new Error("Не удалось завершить сохранённую проводку материала.");
  }
  return receipt;
}
