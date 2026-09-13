/** Exact confirmation command retained until the matching receipt is verified. */
export type LateCostPending = { org: string; expenseId: number; principal: string; body: string };
type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const key = (org: string, principal: string) => `late-cost-confirmation:${JSON.stringify([org, principal])}`;
const digest = /^[a-f0-9]{64}$/;
const uuid = /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/;
const money = /^\d{1,18}(?:\.\d{1,2})?$/;
const positiveId = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;

function checked(value: unknown, org: string, principal: string): LateCostPending {
  const item = value as LateCostPending;
  if (!item || item.org !== org || item.principal !== principal || !principal || !/^[1-9][0-9]*$/.test(org)
    || !positiveId(item.expenseId) || typeof item.body !== "string") throw new Error("Команда проведения относится к другому документу или пользователю.");
  const data = JSON.parse(item.body), allocation = data?.allocation, accounts = data?.accounts;
  if (!data || !uuid.test(data.request_key) || !digest.test(data.expected_digest) || !digest.test(data.expected_basis_digest)
    || Object.keys(data).some(name => !["allocation", "accounts", "request_key", "expected_digest", "expected_basis_digest"].includes(name))
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
  return !!receipt && String(receipt.organization_id) === item.org && receipt.expense_id === item.expenseId
    && receipt.source_version === command.allocation.expected_version && receipt.request_key === command.request_key
    && receipt.digest === command.expected_digest && receipt.basis_digest === command.expected_basis_digest
    && receipt.posted === true && positiveId(receipt.entry_id);
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
