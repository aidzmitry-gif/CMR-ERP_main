export type Scope = { org: number; principal: string };
export type Group = { id: number; code: string; title: string; active: boolean };
export type Article = Group & { group_id: number };
export type Catalog = { revision: number; groups: Group[]; articles: Article[] };
export type BudgetLine = { article_id: number; months: (string | null)[]; article_snapshot: Article & { group: Group } };
export type Budget = { id: number; year: number; currency: "BYN"; basis: "cash" | "accrual"; revision: number; state: "draft";
  catalog_revision: number; actor: string; evidence: string; lines: BudgetLine[] };
export type ApprovedPlan = { budget_id: number; budget_revision: number; approved_by: string; approved_at: string;
  evidence: string; approval_digest: string; budget: Budget };
export type Context = { organization_id: number; principal: string; catalog: Catalog; role: "reader" | "accountant" | "chief";
  approval_enabled: true; approval_blocker: string | null; template: { code: string; title: string; articles: { code: string; title: string }[] }[] };
export type BudgetView = { organization_id: number; principal: string; year: number; currency: "BYN"; basis: "cash" | "accrual";
  versions: Budget[]; approved_plan: ApprovedPlan | null; actuals: Record<"accrued" | "paid" | "commitments", { amount: null; coverage: "unknown"; reason: string }>;
  approval_enabled: true; approval_blocker: string | null };
export type ExpenseActualRow = { article_id: number; article_code: string; article_title: string; group_id: number;
  group_title: string | null; amount: string; lines: number };
export type ExpenseActuals = { year: number; month: number; currency: "BYN"; basis: "cash" | "accrual";
  amount: string | null; coverage: "unknown" | "partial" | "complete"; matched_lines: number; unmatched_lines: number | null;
  rows: ExpenseActualRow[]; reason: string };
export type UnmatchedExpenseLine = { entry_id: number; line_id: number; posting_date: string; source: string; operation: string;
  account_code: string; side: "debit" | "credit"; amount: string; dimensions: Record<string, string>; reason: "нет статьи" | "статья отсутствует в текущем справочнике" };
export type UnmatchedExpenseLines = { year: number; month: number; currency: "BYN"; basis: "cash" | "accrual";
  items: UnmatchedExpenseLine[]; next_after_line_id: number | null };
export type CatalogBody = { request_key: string; expected_revision: number; evidence: string;
  action: "template" | "create_group" | "create_article" | "archive_group" | "archive_article";
  code: string | null; title: string | null; group_id: number | null; target_id: number | null };
export type BudgetBody = { request_key: string; expected_revision: number; expected_catalog_revision: number; evidence: string;
  year: number; currency: "BYN"; basis: "cash" | "accrual"; lines: { article_id: number; months: (string | null)[] }[] };
export type ApprovalBody = { request_key: string; budget_id: number; expected_revision: number; evidence: string };
export type Receipt = { organization_id: number; principal: string; kind: "catalog" | "budget" | "budget_approval"; request_key: string;
  command: CatalogBody | BudgetBody | ApprovalBody; command_hash: string; result: Catalog | Budget | ApprovedPlan; result_digest: string; receipt_digest: string };
export type Attempt = { scope: Scope; kind: "catalog" | "budget" | "approval"; body: string; hash: string; nonce: string; outcome: "pending" | "uncertain" | "done" | "rejected" };
export type Journal = { raw: string | null; attempt: Attempt | null };
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const positive = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const text = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const revision = (v: unknown) => Number.isSafeInteger(v) && Number(v) >= 0;
const uuid = (v: unknown) => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
const money = (v: unknown) => v === null || typeof v === "string" && /^(0|[1-9][0-9]{0,15})\.[0-9]{2}$/.test(v);
const signedMoney = (v: unknown) => v === null || typeof v === "string" && /^-?(0|[1-9][0-9]{0,15})\.[0-9]{2}$/.test(v);
export function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (object(v)) return `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonical(v[k])}`).join(",")}}`;
  return JSON.stringify(v);
}
export async function hash(v: unknown) {
  const data = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(v)));
  return Array.from(new Uint8Array(data), v => v.toString(16).padStart(2, "0")).join("");
}
export class ExpenseError extends Error { constructor(message: string, public status?: number) { super(message); } }
function invalid(): never { throw new ExpenseError("Ответ или сохранённая команда не прошли проверку. Обновите сведения."); }
const prefix = (org: number) => `/api/accounting/organizations/${org}`;
async function request(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try { response = await fetch(path, { ...init, cache: "no-store" }); }
  catch { throw new ExpenseError("Связь прервана. Результат команды нужно проверить."); }
  let body: unknown;
  try { body = await response.json(); } catch { throw new ExpenseError("Ответ сервера не прочитан. Результат нужно проверить."); }
  if (!response.ok) throw new ExpenseError(object(body) && text(body.detail) ? body.detail : `Запрос отклонён (${response.status}).`, response.status);
  return body;
}
function group(v: unknown): v is Group { return object(v) && positive(v.id) && text(v.code) && text(v.title) && typeof v.active === "boolean"; }
function article(v: unknown): v is Article { return group(v) && positive((v as Article).group_id); }
function checkCatalog(v: unknown): v is Catalog {
  return object(v) && revision(v.revision) && Array.isArray(v.groups) && v.groups.every(group)
    && new Set(v.groups.map(g => g.id)).size === v.groups.length
    && Array.isArray(v.articles) && v.articles.every(a => article(a) && (v.groups as Group[]).some(g => g.id === a.group_id))
    && new Set(v.articles.map(a => a.id)).size === v.articles.length;
}
function checkBudget(v: unknown): v is Budget {
  return object(v) && positive(v.id) && revision(v.catalog_revision) && positive(v.revision) && v.state === "draft"
    && Number.isInteger(v.year) && Number(v.year) >= 2000 && Number(v.year) <= 2100 && v.currency === "BYN"
    && ["cash", "accrual"].includes(String(v.basis)) && text(v.actor) && text(v.evidence) && Array.isArray(v.lines)
    && v.lines.length > 0 && new Set(v.lines.map(l => object(l) ? l.article_id : null)).size === v.lines.length
    && v.lines.every(l => object(l) && positive(l.article_id) && Array.isArray(l.months) && l.months.length === 12 && l.months.every(money)
      && article(l.article_snapshot) && l.article_snapshot.id === l.article_id && object(l.article_snapshot)
      && group((l.article_snapshot as Record<string, unknown>).group) && ((l.article_snapshot as Record<string, unknown>).group as Group).id === l.article_snapshot.group_id);
}
function checkApprovedPlan(v: unknown): v is ApprovedPlan {
  return object(v) && positive(v.budget_id) && positive(v.budget_revision) && text(v.approved_by)
    && text(v.approved_at) && text(v.evidence) && /^[0-9a-f]{64}$/i.test(String(v.approval_digest))
    && checkBudget(v.budget) && v.budget.id === v.budget_id && v.budget.revision === v.budget_revision;
}
function checkActualRow(v: unknown): v is ExpenseActualRow {
  return object(v) && positive(v.article_id) && text(v.article_code) && text(v.article_title)
    && positive(v.group_id) && (v.group_title === null || text(v.group_title)) && typeof v.amount === "string" && signedMoney(v.amount)
    && typeof v.lines === "number" && Number.isSafeInteger(v.lines) && v.lines > 0;
}
function checkActuals(v: unknown): v is ExpenseActuals {
  return object(v) && Number.isInteger(v.year) && Number(v.year) >= 2000 && Number(v.year) <= 2100
    && Number.isInteger(v.month) && Number(v.month) >= 1 && Number(v.month) <= 12 && v.currency === "BYN"
    && ["cash", "accrual"].includes(String(v.basis)) && signedMoney(v.amount)
    && ["unknown", "partial", "complete"].includes(String(v.coverage)) && typeof v.matched_lines === "number"
    && Number.isSafeInteger(v.matched_lines) && v.matched_lines >= 0
    && (v.unmatched_lines === null || typeof v.unmatched_lines === "number" && Number.isSafeInteger(v.unmatched_lines) && v.unmatched_lines >= 0)
    && Array.isArray(v.rows) && v.rows.every(checkActualRow) && text(v.reason);
}
async function envelope(v: unknown, org: number, principal?: string) {
  if (object(v) && (v.organization_id !== org || principal && v.principal !== principal)) throw new ExpenseError("Область доступа изменилась. Обновите сведения.", 403);
  if (!object(v) || !text(v.principal)) invalid();
  const { digest, ...rest } = v;
  if (digest !== await hash(rest)) invalid();
  return v;
}
export async function organizations(): Promise<{ id: number; name: string; unp: string }[]> {
  const v = await request("/api/accounting/organizations");
  if (!Array.isArray(v) || !v.every(o => object(o) && positive(o.id) && text(o.name) && text(o.unp))) invalid();
  return v as { id: number; name: string; unp: string }[];
}
export async function context(org: number, principal?: string): Promise<Context> {
  if (!positive(org)) invalid();
  const v = await envelope(await request(`${prefix(org)}/expense-catalog`), org, principal);
  if (!checkCatalog(v.catalog) || !["reader", "accountant", "chief"].includes(String(v.role))
    || v.approval_enabled !== true || v.approval_blocker !== null || !Array.isArray(v.template)
    || !v.template.every(g => object(g) && text(g.code) && text(g.title) && Array.isArray(g.articles)
      && g.articles.every(a => object(a) && text(a.code) && text(a.title)))) invalid();
  return v as unknown as Context;
}
export async function getBudgets(scope: Scope, year: number, basis: "cash" | "accrual"): Promise<BudgetView> {
  const v = await envelope(await request(`${prefix(scope.org)}/expense-budgets?year=${year}&currency=BYN&basis=${basis}`), scope.org, scope.principal);
  if (v.year !== year || v.currency !== "BYN" || v.basis !== basis
    || (v.approved_plan !== null && !checkApprovedPlan(v.approved_plan)) || v.approval_enabled !== true
    || v.approval_blocker !== null || !Array.isArray(v.versions) || !v.versions.every(b => checkBudget(b) && b.year === year && b.basis === basis)
    || !object(v.actuals) || !["accrued", "paid", "commitments"].every(k => {
      const a = (v.actuals as Record<string, unknown>)[k]; return object(a) && a.amount === null && a.coverage === "unknown" && text(a.reason);
    })) invalid();
  return v as unknown as BudgetView;
}
export async function getActuals(scope: Scope, year: number, month: number, basis: "cash" | "accrual"): Promise<ExpenseActuals> {
  const v = await envelope(await request(`${prefix(scope.org)}/expense-actuals?year=${year}&month=${month}&currency=BYN&basis=${basis}`), scope.org, scope.principal);
  if (v.year !== year || v.month !== month || v.currency !== "BYN" || v.basis !== basis || !checkActuals(v.actuals)) invalid();
  return v.actuals as ExpenseActuals;
}
export async function getUnmatchedActuals(scope: Scope, year: number, month: number, basis: "cash" | "accrual", after?: number): Promise<UnmatchedExpenseLines> {
  const cursor = after ? `&after_line_id=${after}` : "";
  const v = await envelope(await request(`${prefix(scope.org)}/expense-actuals/unmatched?year=${year}&month=${month}&currency=BYN&basis=${basis}${cursor}`), scope.org, scope.principal);
  const item = (row: unknown): row is UnmatchedExpenseLine => object(row) && positive(row.entry_id) && positive(row.line_id) && text(row.posting_date) && text(row.source) && text(row.operation) && text(row.account_code)
    && ["debit", "credit"].includes(String(row.side)) && signedMoney(row.amount) && object(row.dimensions) && Object.values(row.dimensions).every(value => typeof value === "string")
    && ["нет статьи", "статья отсутствует в текущем справочнике"].includes(String(row.reason));
  if (v.year !== year || v.month !== month || v.currency !== "BYN" || v.basis !== basis || !Array.isArray(v.items) || !v.items.every(item)
    || (v.next_after_line_id !== null && !positive(v.next_after_line_id))) invalid();
  return v as unknown as UnmatchedExpenseLines;
}
function validateBody(kind: Attempt["kind"], v: unknown) {
  if (!object(v) || !uuid(v.request_key) || !text(v.evidence)) invalid();
  if (kind === "approval") {
    if (!revision(v.expected_revision) || !positive(v.expected_revision) || !positive(v.budget_id)
      || canonical(Object.keys(v).sort()) !== canonical(["request_key", "budget_id", "expected_revision", "evidence"].sort())) invalid();
    return;
  }
  if (!revision(v.expected_revision)) invalid();
  const keys = kind === "catalog" ? ["request_key", "expected_revision", "evidence", "action", "code", "title", "group_id", "target_id"]
    : ["request_key", "expected_revision", "expected_catalog_revision", "evidence", "year", "currency", "basis", "lines"];
  if (canonical(Object.keys(v).sort()) !== canonical(keys.sort())) invalid();
  if (kind === "budget") {
    if (!revision(v.expected_catalog_revision) || !Number.isInteger(v.year) || Number(v.year) < 2000 || Number(v.year) > 2100
      || v.currency !== "BYN" || !["cash", "accrual"].includes(String(v.basis)) || !Array.isArray(v.lines) || !v.lines.length || v.lines.length > 300
      || !v.lines.every(l => object(l) && positive(l.article_id) && canonical(Object.keys(l).sort()) === canonical(["article_id", "months"])
        && Array.isArray(l.months) && l.months.length === 12 && l.months.every(money))
      || v.lines.some((l, i) => i && l.article_id <= (v.lines as { article_id: number }[])[i - 1].article_id)) invalid();
  } else {
    const action = String(v.action);
    if (!["template", "create_group", "create_article", "archive_group", "archive_article"].includes(action)) invalid();
    const create = action.startsWith("create");
    if (create ? !text(v.code) || !/^[a-z][a-z0-9_]{0,63}$/.test(v.code) || !text(v.title) : v.code !== null || v.title !== null) invalid();
    if (action === "create_article" ? !positive(v.group_id) : v.group_id !== null) invalid();
    if (action.startsWith("archive") ? !positive(v.target_id) : v.target_id !== null) invalid();
  }
}
const storageKey = (s: Scope) => `expense-command:v1:${encodeURIComponent(s.principal)}:${s.org}`;
export async function journal(scope: Scope): Promise<Journal> {
  try {
    const raw = sessionStorage.getItem(storageKey(scope));
    if (raw === null) return { raw, attempt: null };
    const a = JSON.parse(raw);
    if (!object(a) || canonical(a.scope) !== canonical(scope) || !["catalog", "budget", "approval"].includes(String(a.kind)) || !uuid(a.nonce)
      || !["pending", "uncertain", "done", "rejected"].includes(String(a.outcome)) || typeof a.body !== "string") invalid();
    validateBody(a.kind as Attempt["kind"], JSON.parse(a.body));
    if (await hash(JSON.parse(a.body)) !== a.hash) invalid();
    return { raw, attempt: a as unknown as Attempt };
  } catch { throw new ExpenseError("Журнал недоступен или повреждён. Новая отправка остановлена."); }
}
function cas(old: Journal, next: Attempt): Journal {
  try {
    const key = storageKey(next.scope);
    if (sessionStorage.getItem(key) !== old.raw) throw new Error();
    const raw = JSON.stringify(next); sessionStorage.setItem(key, raw);
    if (sessionStorage.getItem(key) !== raw) throw new Error();
    return { raw, attempt: next };
  } catch { throw new ExpenseError("Журнал изменился или не сохраняется. Отправка остановлена."); }
}
export async function begin(scope: Scope, kind: Attempt["kind"], body: CatalogBody | BudgetBody | ApprovalBody, expected: string | null) {
  validateBody(kind, body);
  const saved = await journal(scope);
  if (saved.raw !== expected || saved.attempt && ["pending", "uncertain"].includes(saved.attempt.outcome))
    throw new ExpenseError("Сначала проверьте исходную команду.");
  return cas(saved, { scope, kind, body: JSON.stringify(body), hash: await hash(body), nonce: crypto.randomUUID(), outcome: "pending" });
}
export async function validateReceipt(v: unknown, a: Attempt): Promise<Receipt> {
  const expectedKind = a.kind === "approval" ? "budget_approval" : a.kind;
  if (!object(v) || v.organization_id !== a.scope.org || v.principal !== a.scope.principal || v.kind !== expectedKind
    || v.request_key !== JSON.parse(a.body).request_key || canonical(v.command) !== canonical(JSON.parse(a.body))
    || v.command_hash !== a.hash || v.result_digest !== await hash(v.result)) invalid();
  const { receipt_digest, ...unsigned } = v;
  if (receipt_digest !== await hash(unsigned)
    || (a.kind === "catalog" ? !checkCatalog(v.result) : a.kind === "budget" ? !checkBudget(v.result) : !checkApprovedPlan(v.result))) invalid();
  const command = JSON.parse(a.body);
  if (a.kind === "catalog" && (v.result as Catalog).revision !== command.expected_revision + 1) invalid();
  if (a.kind === "budget") {
    const budget = v.result as Budget;
    if (budget.year !== command.year || budget.currency !== command.currency || budget.basis !== command.basis
      || budget.catalog_revision !== command.expected_catalog_revision || budget.actor !== a.scope.principal || budget.evidence !== command.evidence
      || canonical(budget.lines.map(l => ({ article_id: l.article_id, months: l.months }))) !== canonical(command.lines)) invalid();
  }
  if (a.kind === "approval") {
    const approved = v.result as ApprovedPlan;
    const { approval_digest, ...approvalUnsigned } = approved;
    if (approval_digest !== await hash(approvalUnsigned)) invalid();
    if (approved.budget_id !== command.budget_id || approved.budget_revision !== command.expected_revision
      || approved.approved_by !== a.scope.principal || approved.evidence !== command.evidence
      || approved.budget.id !== command.budget_id || approved.budget.revision !== command.expected_revision) invalid();
  }
  return v as unknown as Receipt;
}
export async function dispatch(saved: Journal, mode: "first" | "retry" | "recover") {
  const a = saved.attempt;
  if (!a || !saved.raw || !["pending", "uncertain"].includes(a.outcome)) invalid();
  await context(a.scope.org, a.scope.principal);
  if ((await journal(a.scope)).raw !== saved.raw) throw new ExpenseError("Команда изменилась до отправки.");
  const url = mode === "recover" ? `${prefix(a.scope.org)}/expense-commands/${JSON.parse(a.body).request_key}`
    : `${prefix(a.scope.org)}/${a.kind === "catalog" ? "expense-catalog/commands" : a.kind === "budget" ? "expense-budgets/drafts" : "expense-budgets/approve"}`;
  try {
    const v = await request(url, mode === "recover" ? undefined : { method: "POST", body: a.body,
      headers: { "Content-Type": "application/json", "X-Expected-Principal": a.scope.principal } });
    const receipt = await validateReceipt(v, a);
    return { receipt, journal: cas(saved, { ...a, outcome: "done" }) };
  } catch (e) {
    const rejected = mode === "first" && e instanceof ExpenseError && e.status && e.status >= 400 && e.status < 500;
    cas(saved, { ...a, outcome: rejected ? "rejected" : "uncertain" });
    throw e;
  }
}
