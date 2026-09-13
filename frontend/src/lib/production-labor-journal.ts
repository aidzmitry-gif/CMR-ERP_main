/** Exact verified payroll-import command retained until the ledger receipt is read back. */
export type ProductionLaborLine = {
  source_line_id: string;
  employee: string;
  order_id?: number;
  order_analytics?: string;
  department: string;
  cost_account: string;
  role: "direct" | "overhead";
  amount_byn: string;
  evidence: string;
};
export type ProductionLaborDraft = {
  request_key: string;
  source_document: string;
  source_version: 1;
  source_digest: string;
  verified_by: string;
  source_evidence: string;
  policy_id: number;
  posting_date: string;
  payroll_account: string;
  lines: ProductionLaborLine[];
};
export type ProductionLaborCommand = ProductionLaborDraft & { digest: string };
export type PendingProductionLabor = { org: string; principal: string; month: string; command: ProductionLaborCommand };
export type ProductionLaborReceipt = { organization_id: number; month: string; actor: string; request_key: string;
  source_document: string; source_version: 1; source_digest: string; digest: string; entry_id: number;
  entry?: { id: number }; posted: true; final_cost_certified: false };

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const key = (org: string, principal: string, month: string) =>
  `production-labor-import:${JSON.stringify([org, principal, month])}`;
const id = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const text = (value: unknown, min: number, max: number) => typeof value === "string"
  && value === value.trim() && value.length >= min && value.length <= max;
const validDate = (value: unknown, month: string) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)
  && value.startsWith(`${month}-`) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;

function validate(item: PendingProductionLabor) {
  const c = item?.command;
  if (!item || Object.keys(item).sort().join() !== ["command", "month", "org", "principal"].sort().join()
    || typeof item.org !== "string" || !/^[1-9]\d*$/.test(item.org) || !text(item.principal, 1, 200)
    || typeof item.month !== "string" || !/^\d{4}-\d{2}$/.test(item.month) || !c || typeof c !== "object" || Array.isArray(c)
    || Object.keys(c).sort().join() !== ["digest", "lines", "payroll_account", "policy_id", "posting_date", "request_key",
      "source_digest", "source_document", "source_evidence", "source_version", "verified_by"].sort().join()
    || !text(c.request_key, 36, 36) || !text(c.source_document, 1, 120) || c.source_version !== 1
    || !digest(c.source_digest) || !text(c.verified_by, 1, 200) || !text(c.source_evidence, 10, 2000)
    || !id(c.policy_id) || !validDate(c.posting_date, item.month) || !text(c.payroll_account, 1, 32)
    || !digest(c.digest) || !Array.isArray(c.lines) || c.lines.length < 1 || c.lines.length > 10000)
    throw new Error("Сохранённый импорт труда повреждён.");
  const seen = new Set<string>();
  for (const line of c.lines) {
    if (!line || typeof line !== "object" || !text(line.source_line_id, 1, 128) || seen.has(line.source_line_id)
      || !text(line.employee, 1, 200) || !text(line.department, 1, 200) || !text(line.cost_account, 1, 32)
      || !["direct", "overhead"].includes(line.role) || typeof line.amount_byn !== "string"
      || !/^\d+\.\d{2}$/.test(line.amount_byn) || Number(line.amount_byn) <= 0 || !text(line.evidence, 10, 1000)
      || (line.order_id !== undefined && !id(line.order_id))
      || (line.order_analytics !== undefined && !text(line.order_analytics, 1, 200))
      || (line.role === "direct" && (!id(line.order_id) || !text(line.order_analytics, 1, 200))))
      throw new Error("Строка сохранённого импорта труда повреждена.");
    seen.add(line.source_line_id);
  }
}

export function pendingProductionLabor(store: Store, org: string, principal: string, month: string): PendingProductionLabor | null {
  const raw = store.getItem(key(org, principal, month));
  if (raw === null) return null;
  const item = JSON.parse(raw) as PendingProductionLabor;
  validate(item);
  if (item.org !== org || item.principal !== principal || item.month !== month)
    throw new Error("Сохранённый импорт труда относится к другому юрлицу, периоду или пользователю.");
  return item;
}

function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object" || Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => same(v, b[i]));
  const left = a as Record<string, unknown>, right = b as Record<string, unknown>;
  return Object.keys(left).length === Object.keys(right).length && Object.keys(left).every(k => Object.hasOwn(right, k) && same(left[k], right[k]));
}

function receiptFor(item: PendingProductionLabor, value: unknown): ProductionLaborReceipt {
  const row = value as Partial<ProductionLaborReceipt> | null;
  if (!row || String(row.organization_id) !== item.org || row.month !== item.month || row.actor !== item.principal
    || row.request_key !== item.command.request_key || row.source_document !== item.command.source_document
    || row.source_version !== 1 || row.source_digest !== item.command.source_digest || row.digest !== item.command.digest
    || row.posted !== true || row.final_cost_certified !== false || !id(row.entry_id)
    || (row.entry && row.entry.id !== row.entry_id)) throw new Error("Квитанция не подтверждает сохранённый импорт труда.");
  return row as ProductionLaborReceipt;
}

async function access(org: string, request: typeof fetch) {
  const response = await request(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" });
  if (!response.ok) throw new Error("Не удалось проверить права проведения труда.");
  const row = await response.json();
  if (String(row?.organization_id) !== org || !text(row.principal, 1, 200) || typeof row.can_confirm !== "boolean")
    throw new Error("Ответ о правах проведения труда повреждён.");
  return row as { organization_id: number; principal: string; can_confirm: boolean };
}

/** postIfMissing=false is read-only recovery after reload or an uncertain response. */
export async function resolveProductionLabor(store: Store, item: PendingProductionLabor, postIfMissing: boolean,
  request: typeof fetch = fetch): Promise<ProductionLaborReceipt | null> {
  validate(item);
  const storageKey = key(item.org, item.principal, item.month);
  const previous = pendingProductionLabor(store, item.org, item.principal, item.month);
  if (previous && !same(previous, item)) throw new Error("Сначала проверьте сохранённый импорт труда.");
  const raw = previous ? store.getItem(storageKey)! : JSON.stringify(item);
  if (!previous) store.setItem(storageKey, raw);
  const unchanged = () => { if (store.getItem(storageKey) !== raw) throw new Error("Сохранённый импорт изменился. Отправка остановлена."); };
  unchanged();
  const current = await access(item.org, request);
  if (current.principal !== item.principal) throw new Error("Пользователь изменился. Импорт труда не отправлен.");
  const base = `/api/accounting/organizations/${item.org}/periods/${item.month}`;
  async function check(): Promise<ProductionLaborReceipt | null> {
    const response = await request(`/api/accounting/organizations/${item.org}/production-labor-import-status/${item.command.request_key}`, { cache: "no-store" });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error("Результат импорта труда пока не удалось проверить. Запрос сохранён.");
    return receiptFor(item, await response.json());
  }
  let result = await check();
  if (!result && postIfMissing) {
    if (!current.can_confirm) throw new Error("Нет права проводить импорт труда. Запрос сохранён.");
    unchanged();
    const response = await request(`${base}/production-labor-import-confirm`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": item.principal },
      body: JSON.stringify(item.command),
    });
    result = await check();
    if (!result) throw new Error(response.ok ? "Импорт пока не подтверждён. Проверьте сохранённый запрос повторно."
      : "Сервер не подтвердил импорт труда. Проверьте источник и сохранённый запрос.");
  }
  if (result) {
    unchanged(); store.removeItem(storageKey);
    if (store.getItem(storageKey) !== null) throw new Error("Не удалось завершить сохранённый импорт труда.");
  }
  return result;
}
