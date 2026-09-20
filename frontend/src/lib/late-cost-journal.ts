/** Exact confirmation command retained until the matching receipt is verified. */
export type LateCostPending = { org: string; expenseId: number; principal: string; body: string };
type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const key = (org: string, principal: string) => `late-cost-confirmation:${JSON.stringify([org, principal])}`;
const digest = /^[a-f0-9]{64}$/;
const uuid = /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/;
const money = /^\d{1,18}(?:\.\d{1,2})?$/;
const positiveId = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;
type MaterialSelection = { output_entry_id: number; amount_byn: string };
type PoolSelection = { output_entry_id: number; amount_byn: string };
function materialSelections(value: unknown): value is MaterialSelection[] {
  if (!Array.isArray(value) || value.length > 100) return false;
  return value.every(row => row && positiveId(row.output_entry_id)
    && typeof row.amount_byn === "string" && /^\d{1,18}\.\d{2}$/.test(row.amount_byn)
    && BigInt(row.amount_byn.replace(".", "")) > 0n
    && Object.keys(row).every(key => ["output_entry_id", "amount_byn"].includes(key)))
    && new Set(value.map(row => row.output_entry_id)).size === value.length;
}
function poolSelections(value: unknown): value is PoolSelection[] {
  if (!Array.isArray(value) || value.length > 100) return false;
  return value.every(row => row && positiveId(row.output_entry_id)
    && typeof row.amount_byn === "string" && /^-?\d{1,18}\.\d{2}$/.test(row.amount_byn)
    && BigInt(row.amount_byn.replace(".", "")) !== 0n
    && Object.keys(row).every(key => ["output_entry_id", "amount_byn"].includes(key)))
    && new Set(value.map(row => row.output_entry_id)).size === value.length;
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
    .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  return JSON.stringify(value);
}

function checked(value: unknown, org: string, principal: string): LateCostPending {
  const item = value as LateCostPending;
  if (!item || item.org !== org || item.principal !== principal || !principal || !/^[1-9][0-9]*$/.test(org)
    || !positiveId(item.expenseId) || typeof item.body !== "string") throw new Error("Команда проведения относится к другому документу или пользователю.");
  const data = JSON.parse(item.body), allocation = data?.allocation, accounts = data?.accounts;
  const material = data?.command_version === 2;
  const pool = data?.command_version === 3;
  const allowed = ["allocation", "accounts", "request_key", "expected_digest", "expected_basis_digest",
    ...(material || pool ? ["command_version", "material_outputs"] : [])];
  if (!data || !uuid.test(data.request_key) || !digest.test(data.expected_digest) || !digest.test(data.expected_basis_digest)
    || Object.keys(data).some(name => !allowed.includes(name))
    || material && !materialSelections(data.material_outputs)
    || pool && !poolSelections(data.material_outputs)
    || data.command_version !== undefined && !material && !pool
    || !allocation || !positiveId(allocation.expected_version) || !positiveId(allocation.policy_id)
    || typeof allocation.posting_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(allocation.posting_date)
    || typeof allocation.capitalizable_amount_byn !== "string" || !money.test(allocation.capitalizable_amount_byn)
    || typeof allocation.excluded_amount_byn !== "string" || !money.test(allocation.excluded_amount_byn)
    || typeof allocation.classification_evidence !== "string" || allocation.classification_evidence.trim().length < 10
    || !accounts || typeof accounts.settlement_account !== "string" || !/^60(?:\.[0-9]+)*$/.test(accounts.settlement_account)
    || !Array.isArray(accounts.excluded_costs) || accounts.excluded_costs.length > 100
    || accounts.excluded_costs.some((row: { account: string; amount_byn: string; dimensions: Record<string, string> }) => !row
      || typeof row.account !== "string" || typeof row.amount_byn !== "string" || !money.test(row.amount_byn)
      || !row.dimensions || typeof row.dimensions !== "object" || Array.isArray(row.dimensions)
      || Object.values(row.dimensions).some(v => typeof v !== "string"))) throw new Error("Повреждена сохранённая команда проведения.");
  return item;
}

export function pendingLateCost(store: Store, org: string, principal: string): LateCostPending | null {
  const raw = store.getItem(key(org, principal));
  return raw === null ? null : checked(JSON.parse(raw), org, principal);
}
export function rememberLateCost(store: Store, item: LateCostPending) {
  checked(item, item.org, item.principal);
  const previous = pendingLateCost(store, item.org, item.principal);
  if (previous && JSON.stringify(previous) !== JSON.stringify(item)) throw new Error("Сначала проверьте результат предыдущего проведения.");
  const raw = JSON.stringify(item);
  store.setItem(key(item.org, item.principal), raw);
  if (store.getItem(key(item.org, item.principal)) !== raw) throw new Error("Команда не сохранена. Проведение остановлено.");
}
export function matchesLateCostReceipt(item: LateCostPending, value: unknown): boolean {
  checked(item, item.org, item.principal);
  const receipt = value as Record<string, unknown> | null, command = JSON.parse(item.body);
  const identity = !!receipt && String(receipt.organization_id) === item.org && receipt.expense_id === item.expenseId
    && receipt.source_version === command.allocation.expected_version && receipt.request_key === command.request_key
    && receipt.digest === command.expected_digest && receipt.basis_digest === command.expected_basis_digest
    && receipt.posted === true && positiveId(receipt.entry_id);
  if (!identity || ![2, 3].includes(command.command_version)) return identity;
  const savedCommand = { allocation: command.allocation, accounts: command.accounts,
    command_version: command.command_version, material_outputs: command.material_outputs };
  if (canonical(receipt.command) !== canonical(savedCommand) || !Array.isArray(receipt.output_revisions)) return false;
  const links = receipt.output_revisions as Array<Record<string, unknown>>;
  const outputLinks = links.length === command.material_outputs.length
    && new Set(links.map(row => row.output_revision_id)).size === links.length
    && links.every((row, index) => positiveId(row.output_revision_id)
      && row.output_entry_id === command.material_outputs[index].output_entry_id
      && row.amount_byn === command.material_outputs[index].amount_byn);
  if (!outputLinks || command.command_version !== 3) return outputLinks;
  const inventory = receipt.inventory_value_links;
  return Array.isArray(inventory) && inventory.length <= 10000
    && new Set(inventory.map(row => row && typeof row === "object" ? (row as Record<string, unknown>).value_line_id : null)).size === inventory.length
    && inventory.every(row => !!row && typeof row === "object" && (row as Record<string, unknown>).value_entry_id === receipt.entry_id
      && positiveId((row as Record<string, unknown>).value_line_id)
      && positiveId((row as Record<string, unknown>).acquisition_entry_id)
      && positiveId((row as Record<string, unknown>).acquisition_line_id));
}
export function lateCostPath(item: LateCostPending): string {
  checked(item, item.org, item.principal);
  return `/api/accounting/organizations/${item.org}/additional-expenses/${item.expenseId}`
    + (JSON.parse(item.body).command_version === 2 ? "/material"
      : JSON.parse(item.body).command_version === 3 ? "/pool" : "");
}
export function settleLateCost(store: Store, item: LateCostPending, receipt: unknown) {
  if (!matchesLateCostReceipt(item, receipt)) throw new Error("Ответ не подтверждает сохранённую команду проведения.");
  clearRejectedLateCost(store, item);
}
/** Only for a definitive rejection of the first attempt, never a retry/readback. */
export function clearRejectedLateCost(store: Store, item: LateCostPending) {
  const current = pendingLateCost(store, item.org, item.principal);
  if (!current || JSON.stringify(current) !== JSON.stringify(item)) throw new Error("Сохранённая команда проведения изменилась.");
  store.removeItem(key(item.org, item.principal));
  if (store.getItem(key(item.org, item.principal)) !== null) throw new Error("Не удалось завершить сохранённую команду.");
}
