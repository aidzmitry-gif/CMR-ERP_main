/** Durable client-side recovery for the reviewed gross-payroll import. */
export type PayrollAccrualLine = {
  source_line_id: string;
  employee: string;
  department: string;
  debit_account: string;
  amount_byn: string;
  dimensions: Record<string, string>;
  evidence: string;
};

export type PayrollAccrualDraft = {
  request_key: string;
  source_document: string;
  source_version: 1;
  source_digest: string;
  verified_by: string;
  source_evidence: string;
  policy_id: number;
  posting_date: string;
  payroll_account: string;
  lines: PayrollAccrualLine[];
};

export type PayrollAccrualCommand = PayrollAccrualDraft & { digest: string };
export type PendingPayrollAccrual = { org: string; principal: string; month: string; command: PayrollAccrualCommand };
export type PayrollAccrualReceipt = {
  organization_id: number;
  month: string;
  actor: string;
  request_key: string;
  source_document: string;
  source_version: 1;
  source_digest: string;
  digest: string;
  entry_id: number;
  entry?: { id: number };
  posted: true;
  statutory_payroll_certified: false;
  deductions_and_contributions_available: false;
};

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;
type Requester = typeof fetch;
const DIMENSIONS = new Set([
  "counterparty", "contract", "settlement_document", "warehouse", "sku", "lot", "order", "employee", "asset",
  "department", "owner", "serial",
]);
const key = (org: string, principal: string, month: string) =>
  `payroll-accrual-import:${JSON.stringify([org, principal, month])}`;
const id = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;
const uuid = (value: unknown) => typeof value === "string"
  && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const text = (value: unknown, min: number, max: number) => typeof value === "string"
  && value === value.trim() && value.length >= min && value.length <= max && !value.includes("\0");
const dateInMonth = (value: unknown, month: string) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)
  && value.startsWith(`${month}-`) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
const money = (value: unknown) => typeof value === "string" && /^\d+\.\d{2}$/.test(value) && BigInt(value.replace(".", "")) > 0n;

function validDimensions(value: unknown, employee: string, department: string): value is Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const dimensions = value as Record<string, unknown>;
  return Object.entries(dimensions).every(([name, item]) => DIMENSIONS.has(name) && text(item, 1, 200))
    && (dimensions.employee === undefined || dimensions.employee === employee)
    && (dimensions.department === undefined || dimensions.department === department);
}

function validate(item: PendingPayrollAccrual) {
  const c = item?.command;
  if (!item || Object.keys(item).sort().join() !== ["command", "month", "org", "principal"].sort().join()
    || typeof item.org !== "string" || !/^[1-9]\d*$/.test(item.org) || !text(item.principal, 1, 200)
    || typeof item.month !== "string" || !/^\d{4}-\d{2}$/.test(item.month) || !c || typeof c !== "object" || Array.isArray(c)
    || Object.keys(c).sort().join() !== ["digest", "lines", "payroll_account", "policy_id", "posting_date", "request_key",
      "source_digest", "source_document", "source_evidence", "source_version", "verified_by"].sort().join()
    || !uuid(c.request_key) || !text(c.source_document, 1, 120) || c.source_version !== 1
    || !digest(c.source_digest) || !text(c.verified_by, 1, 200) || !text(c.source_evidence, 10, 2000)
    || !id(c.policy_id) || !dateInMonth(c.posting_date, item.month) || !text(c.payroll_account, 1, 32)
    || !digest(c.digest) || !Array.isArray(c.lines) || c.lines.length < 1 || c.lines.length > 10000)
    throw new Error("Сохранённый импорт начислений повреждён.");
  const seen = new Set<string>();
  for (const line of c.lines) {
    if (!line || typeof line !== "object" || !text(line.source_line_id, 1, 128) || seen.has(line.source_line_id)
      || !text(line.employee, 1, 200) || !text(line.department, 1, 200) || !text(line.debit_account, 1, 32)
      || !money(line.amount_byn) || !validDimensions(line.dimensions, line.employee, line.department)
      || !text(line.evidence, 10, 1000)) throw new Error("Строка сохранённого импорта начислений повреждена.");
    seen.add(line.source_line_id);
  }
}

export function pendingPayrollAccrual(store: Store, org: string, principal: string, month: string): PendingPayrollAccrual | null {
  const raw = store.getItem(key(org, principal, month));
  if (raw === null) return null;
  let item: PendingPayrollAccrual;
  try { item = JSON.parse(raw) as PendingPayrollAccrual; } catch { throw new Error("Сохранённый импорт начислений повреждён."); }
  validate(item);
  if (item.org !== org || item.principal !== principal || item.month !== month)
    throw new Error("Сохранённый импорт относится к другому юрлицу, периоду или пользователю.");
  return item;
}

function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object" || Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((value, index) => same(value, b[index]));
  const left = a as Record<string, unknown>, right = b as Record<string, unknown>;
  return Object.keys(left).length === Object.keys(right).length && Object.keys(left).every(name => Object.hasOwn(right, name) && same(left[name], right[name]));
}

function receiptFor(item: PendingPayrollAccrual, value: unknown): PayrollAccrualReceipt {
  const row = value as Partial<PayrollAccrualReceipt> | null;
  if (!row || String(row.organization_id) !== item.org || row.month !== item.month || row.actor !== item.principal
    || row.request_key !== item.command.request_key || row.source_document !== item.command.source_document
    || row.source_version !== 1 || row.source_digest !== item.command.source_digest || row.digest !== item.command.digest
    || row.posted !== true || row.statutory_payroll_certified !== false || row.deductions_and_contributions_available !== false
    || !id(row.entry_id) || (row.entry && row.entry.id !== row.entry_id))
    throw new Error("Квитанция не подтверждает сохранённый импорт начислений.");
  return row as PayrollAccrualReceipt;
}

export async function payrollAccrualAccess(org: string, request: Requester = fetch) {
  const response = await request(`/api/accounting/organizations/${org}/payroll-accrual-access`, { cache: "no-store" });
  if (!response.ok) throw new Error("Не удалось проверить права проведения начислений.");
  const row = await response.json();
  if (String(row?.organization_id) !== org || !text(row.principal, 1, 200) || typeof row.can_confirm !== "boolean")
    throw new Error("Ответ о правах проведения начислений повреждён.");
  return row as { organization_id: number; principal: string; can_confirm: boolean };
}

/** postIfMissing=false only reads the outcome after reload or an uncertain response. */
export async function resolvePayrollAccrual(store: Store, item: PendingPayrollAccrual, postIfMissing: boolean,
  request: Requester = fetch): Promise<PayrollAccrualReceipt | null> {
  validate(item);
  const storageKey = key(item.org, item.principal, item.month);
  const previous = pendingPayrollAccrual(store, item.org, item.principal, item.month);
  if (previous && !same(previous, item)) throw new Error("Сначала проверьте сохранённый импорт начислений.");
  const raw = previous ? store.getItem(storageKey)! : JSON.stringify(item);
  if (!previous) store.setItem(storageKey, raw);
  const unchanged = () => { if (store.getItem(storageKey) !== raw) throw new Error("Сохранённый импорт изменился. Отправка остановлена."); };
  unchanged();
  const current = await payrollAccrualAccess(item.org, request);
  if (current.principal !== item.principal) throw new Error("Пользователь изменился. Импорт начислений не отправлен.");
  const base = `/api/accounting/organizations/${item.org}/periods/${item.month}`;
  async function check(): Promise<PayrollAccrualReceipt | null> {
    const response = await request(`/api/accounting/organizations/${item.org}/payroll-accrual-import-status/${item.command.request_key}`, { cache: "no-store" });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error("Результат импорта начислений пока не удалось проверить. Запрос сохранён.");
    return receiptFor(item, await response.json());
  }
  let result = await check();
  if (!result && postIfMissing) {
    if (!current.can_confirm) throw new Error("Нет права проводить импорт начислений. Запрос сохранён.");
    unchanged();
    const response = await request(`${base}/payroll-accrual-import-confirm`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": item.principal },
      body: JSON.stringify(item.command),
    });
    result = await check();
    if (!result) throw new Error(response.ok ? "Импорт пока не подтверждён. Проверьте сохранённый запрос повторно."
      : "Сервер не подтвердил импорт начислений. Проверьте источник и сохранённый запрос.");
  }
  if (result) {
    unchanged(); store.removeItem(storageKey);
    if (store.getItem(storageKey) !== null) throw new Error("Не удалось завершить сохранённый импорт начислений.");
  }
  return result;
}
