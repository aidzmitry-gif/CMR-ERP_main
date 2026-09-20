import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  context: vi.fn(), getBudgets: vi.fn(), getActuals: vi.fn(), getUnmatchedActuals: vi.fn(), journal: vi.fn(),
  previewAttribution: vi.fn(), begin: vi.fn(), dispatch: vi.fn(),
}));

vi.mock("@/lib/expense-control-api", () => ({
  ...api,
  ExpenseError: class ExpenseError extends Error { status?: number; },
}));

import { ExpenseControl } from "./expense-control";

afterEach(() => vi.clearAllMocks());

const context = {
  organization_id: 1, principal: "chief", role: "chief" as const, approval_enabled: true, approval_blocker: null,
  catalog: { revision: 1, groups: [{ id: 1, code: "office", title: "Офис", active: true }], articles: [{ id: 1, group_id: 1, code: "supplies", title: "Материалы", active: true }] },
  template: [],
};

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>(next => { resolve = next; });
  return { promise, resolve };
}

const actual = (year: number, month: number, basis: "cash" | "accrual") => ({
  year, month, currency: "BYN" as const, basis, amount: "10.00", coverage: "partial" as const,
  matched_lines: 1, unmatched_lines: 1, reason: "partial", rows: [],
});

const unmatched = (org: number, month: number, basis: "cash" | "accrual", source: string) => ({
  year: 2026, month, currency: "BYN" as const, basis,
  next_after_line_id: null,
  items: [{ entry_id: org * 1000 + month, line_id: org * 1000 + month, posting_date: `2026-${String(month).padStart(2, "0")}-02`, source,
    operation: "manual", account_code: "90.4", side: "debit" as const, amount: "2.00", dimensions: { analytics: "" }, reason: "нет статьи" as const }],
});

const attributionPreview = (lineId = 1001) => ({
  source_entry_id: lineId, source_line_id: lineId, article_id: 1, supersedes_id: null,
  effective_date: "2026-01-02", basis_digest: "a".repeat(64),
  source_snapshot: { entry_id: lineId, source: "source", source_version: 1, operation: "manual", posting_date: "2026-01-02", policy_id: 1,
    entry_digest: "b".repeat(64), line_id: lineId, account_code: "90.4", account_title: "Расходы", category: "expense", cash: false,
    side: "debit" as const, amount: "2.00", currency: "BYN" as const, dimensions: { analytics: "" } },
  article_snapshot: { id: 1, code: "supplies", title: "Материалы", group_id: 1, group: context.catalog.groups[0] },
});

function setupActualMocks() {
  api.context.mockImplementation((org: number) => Promise.resolve({ ...context, organization_id: org, principal: org === 1 ? "chief" : `chief-${org}` }));
  api.journal.mockResolvedValue({ raw: null, attempt: null });
  api.getBudgets.mockImplementation((scope: { org: number; principal: string }, year: number, basis: "cash" | "accrual") => Promise.resolve({
    organization_id: scope.org, principal: scope.principal, year, currency: "BYN", basis, versions: [], approved_plan: null,
    actuals: { accrued: { amount: null, coverage: "unknown", reason: "x" }, paid: { amount: null, coverage: "unknown", reason: "x" }, commitments: { amount: null, coverage: "unknown", reason: "x" } },
    approval_enabled: true, approval_blocker: null,
  }));
  api.getActuals.mockImplementation((_scope: unknown, year: number, month: number, basis: "cash" | "accrual") => Promise.resolve(actual(year, month, basis)));
}

async function loadFacts(month = "1", basis: "cash" | "accrual" = "accrual") {
  await screen.findByText(/Книга № \d+\. Учётная запись:/);
  fireEvent.change(screen.getByLabelText("Год бюджета"), { target: { value: "2026" } });
  fireEvent.change(screen.getByLabelText("Валюта бюджета"), { target: { value: "BYN" } });
  fireEvent.change(screen.getByLabelText("Основа"), { target: { value: basis } });
  fireEvent.change(screen.getByLabelText("Месяц факта"), { target: { value: month } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить бюджет" }));
  await screen.findAllByRole("button", { name: "Показать неразнесённые строки" });
}

it("shows a month plan-fact percentage and warnings for partial and unplanned actuals", async () => {
  api.context.mockResolvedValue(context);
  api.journal.mockResolvedValue({ raw: null, attempt: null });
  api.getBudgets.mockResolvedValue({
    organization_id: 1, principal: "chief", year: 2026, currency: "BYN", basis: "accrual",
    versions: [{ id: 5, year: 2026, currency: "BYN", basis: "accrual", revision: 1, state: "draft", catalog_revision: 1, actor: "chief", evidence: "test", lines: [{ article_id: 1, months: ["100.00", ...Array(11).fill(null)], article_snapshot: { ...context.catalog.articles[0], group: context.catalog.groups[0] } }] }],
    approved_plan: null, actuals: { accrued: { amount: null, coverage: "unknown", reason: "not connected" }, paid: { amount: null, coverage: "unknown", reason: "not connected" }, commitments: { amount: null, coverage: "unknown", reason: "not connected" } }, approval_enabled: true, approval_blocker: null,
  });
  api.getActuals.mockResolvedValue({
    year: 2026, month: 1, currency: "BYN", basis: "accrual", amount: "140.00", coverage: "partial",
    matched_lines: 2, unmatched_lines: 3, reason: "partial", rows: [
      { article_id: 1, article_code: "supplies", article_title: "Материалы", group_id: 1, group_title: "Офис", amount: "125.00", lines: 1 },
      { article_id: 9, article_code: "other", article_title: "Вне плана", group_id: 2, group_title: "Прочее", amount: "15.00", lines: 1 },
    ],
  });

  render(<ExpenseControl org="1" />);
  await screen.findByText("Книга № 1. Учётная запись: chief. Версия справочника: 1.");
  fireEvent.change(screen.getByLabelText("Валюта бюджета"), { target: { value: "BYN" } });
  fireEvent.change(screen.getByLabelText("Основа"), { target: { value: "accrual" } });
  fireEvent.change(screen.getByLabelText("Месяц факта"), { target: { value: "1" } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить бюджет" }));

  expect(await screen.findByLabelText("План-факт расходов")).toBeInTheDocument();
  expect(screen.getByText("25.00 BYN")).toBeInTheDocument();
  expect(screen.getByText("25.00%")).toBeInTheDocument();
  expect(screen.getAllByRole("alert")[0]).toHaveTextContent("покрытие факта partial");
  expect(screen.getByText(/1 статья имеет факт без плана/)).toBeInTheDocument();
});
it("uses the approved immutable budget instead of a newer draft for plan-fact", async () => {
  api.context.mockResolvedValue(context);
  api.journal.mockResolvedValue({ raw: null, attempt: null });
  const line = (amount: string) => ({ article_id: 1, months: [amount, ...Array(11).fill(null)], article_snapshot: { ...context.catalog.articles[0], group: context.catalog.groups[0] } });
  api.getBudgets.mockResolvedValue({
    organization_id: 1, principal: "chief", year: 2026, currency: "BYN", basis: "accrual",
    versions: [{ id: 8, year: 2026, currency: "BYN", basis: "accrual", revision: 2, state: "draft", catalog_revision: 1, actor: "chief", evidence: "newer draft", lines: [line("200.00")] }],
    approved_plan: { budget_id: 5, budget_revision: 1, approved_by: "chief", approved_at: "2026-01-01T00:00:00", evidence: "approved", approval_digest: "a".repeat(64), budget: { id: 5, year: 2026, currency: "BYN", basis: "accrual", revision: 1, state: "draft", catalog_revision: 1, actor: "chief", evidence: "approved", lines: [line("100.00")] } },
    actuals: { accrued: { amount: null, coverage: "unknown", reason: "not connected" }, paid: { amount: null, coverage: "unknown", reason: "not connected" }, commitments: { amount: null, coverage: "unknown", reason: "not connected" } }, approval_enabled: true, approval_blocker: null,
  });
  api.getActuals.mockResolvedValue({
    year: 2026, month: 1, currency: "BYN", basis: "accrual", amount: "125.00", coverage: "complete",
    matched_lines: 1, unmatched_lines: 0, reason: "complete", rows: [{ article_id: 1, article_code: "supplies", article_title: "Материалы", group_id: 1, group_title: "Офис", amount: "125.00", lines: 1 }],
  });

  render(<ExpenseControl org="1" />);
  await screen.findByText("Книга № 1. Учётная запись: chief. Версия справочника: 1.");
  fireEvent.change(screen.getByLabelText("Валюта бюджета"), { target: { value: "BYN" } });
  fireEvent.change(screen.getByLabelText("Основа"), { target: { value: "accrual" } });
  fireEvent.change(screen.getByLabelText("Месяц факта"), { target: { value: "1" } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить бюджет" }));

  expect(await screen.findByText(/План: утверждённая версия 1\./)).toBeInTheDocument();
  expect(screen.getByText("25.00 BYN")).toBeInTheDocument();
  expect(screen.getByText("25.00%")).toBeInTheDocument();
  expect(screen.queryByText("-75.00 BYN")).not.toBeInTheDocument();
});

it("shows accrual and cash actuals separately with their own coverage", async () => {
  api.context.mockResolvedValue(context);
  api.journal.mockResolvedValue({ raw: null, attempt: null });
  api.getBudgets.mockResolvedValue({ organization_id: 1, principal: "chief", year: 2026, currency: "BYN", basis: "accrual", versions: [], approved_plan: null,
    actuals: { accrued: { amount: null, coverage: "unknown", reason: "not connected" }, paid: { amount: null, coverage: "unknown", reason: "not connected" }, commitments: { amount: null, coverage: "unknown", reason: "not connected" } }, approval_enabled: true, approval_blocker: null });
  api.getActuals.mockImplementation((_scope, year, month, basis) => Promise.resolve({ year, month, currency: "BYN", basis,
    amount: basis === "accrual" ? "140.00" : "70.00", coverage: basis === "accrual" ? "partial" : "complete", matched_lines: 1, unmatched_lines: basis === "accrual" ? 2 : 0,
    reason: basis === "accrual" ? "Есть строки без статьи" : "Все оплаты размечены", rows: [] }));

  render(<ExpenseControl org="1" />);
  await screen.findByText("Книга № 1. Учётная запись: chief. Версия справочника: 1.");
  fireEvent.change(screen.getByLabelText("Год бюджета"), { target: { value: "2026" } });
  fireEvent.change(screen.getByLabelText("Валюта бюджета"), { target: { value: "BYN" } });
  fireEvent.change(screen.getByLabelText("Основа"), { target: { value: "accrual" } });
  fireEvent.change(screen.getByLabelText("Месяц факта"), { target: { value: "1" } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить бюджет" }));

  expect(await screen.findByLabelText("Фактические оплаты расходов")).toHaveTextContent("Все оплаты размечены");
  expect(screen.getByLabelText("Начислено")).toHaveTextContent("140.00 BYN");
  expect(screen.getByLabelText("Начислено")).toHaveTextContent("Покрытие: partial");
  expect(screen.getByLabelText("Оплачено")).toHaveTextContent("70.00 BYN");
  expect(screen.getByLabelText("Оплачено")).toHaveTextContent("Покрытие: complete");
  expect(api.getActuals.mock.calls.map(call => call[3])).toEqual(["accrual", "cash"]);
});

it("matches a cash budget only with cash actuals", async () => {
  api.context.mockResolvedValue(context);
  api.journal.mockResolvedValue({ raw: null, attempt: null });
  const line = { article_id: 1, months: ["100.00", ...Array(11).fill(null)], article_snapshot: { ...context.catalog.articles[0], group: context.catalog.groups[0] } };
  api.getBudgets.mockResolvedValue({ organization_id: 1, principal: "chief", year: 2026, currency: "BYN", basis: "cash", versions: [{ id: 5, year: 2026, currency: "BYN", basis: "cash", revision: 1, state: "draft", catalog_revision: 1, actor: "chief", evidence: "cash", lines: [line] }], approved_plan: null,
    actuals: { accrued: { amount: null, coverage: "unknown", reason: "not connected" }, paid: { amount: null, coverage: "unknown", reason: "not connected" }, commitments: { amount: null, coverage: "unknown", reason: "not connected" } }, approval_enabled: true, approval_blocker: null });
  api.getActuals.mockImplementation((_scope, year, month, basis) => Promise.resolve({ year, month, currency: "BYN", basis, amount: basis === "cash" ? "80.00" : "140.00", coverage: "complete", matched_lines: 1, unmatched_lines: 0, reason: "complete",
    rows: [{ article_id: 1, article_code: "supplies", article_title: "Материалы", group_id: 1, group_title: "Офис", amount: basis === "cash" ? "80.00" : "140.00", lines: 1 }] }));

  render(<ExpenseControl org="1" />);
  await screen.findByText("Книга № 1. Учётная запись: chief. Версия справочника: 1.");
  fireEvent.change(screen.getByLabelText("Год бюджета"), { target: { value: "2026" } });
  fireEvent.change(screen.getByLabelText("Валюта бюджета"), { target: { value: "BYN" } });
  fireEvent.change(screen.getByLabelText("Основа"), { target: { value: "cash" } });
  fireEvent.change(screen.getByLabelText("Месяц факта"), { target: { value: "1" } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить бюджет" }));

  expect(await screen.findByLabelText("План-факт расходов")).toHaveTextContent("Основа: денежные выплаты");
  expect(screen.getByLabelText("План-факт расходов")).toHaveTextContent("80.00 BYN");
  expect(screen.getByLabelText("План-факт расходов")).toHaveTextContent("-20.00 BYN");
  expect(screen.getByLabelText("План-факт расходов")).not.toHaveTextContent("140.00 BYN");
  expect(api.getBudgets).toHaveBeenLastCalledWith({ org: 1, principal: "chief" }, 2026, "cash");
});

it("keeps accrual visible when cash is unavailable and never derives commitments", async () => {
  api.context.mockResolvedValue(context);
  api.journal.mockResolvedValue({ raw: null, attempt: null });
  api.getBudgets.mockResolvedValue({ organization_id: 1, principal: "chief", year: 2026, currency: "BYN", basis: "accrual", versions: [], approved_plan: null,
    actuals: { accrued: { amount: null, coverage: "unknown", reason: "not connected" }, paid: { amount: null, coverage: "unknown", reason: "not connected" }, commitments: { amount: null, coverage: "unknown", reason: "not connected" } }, approval_enabled: true, approval_blocker: null });
  api.getActuals.mockImplementation((_scope, year, month, basis) => basis === "cash" ? Promise.reject(new Error("cash ledger unavailable")) : Promise.resolve({ year, month, currency: "BYN", basis, amount: "140.00", coverage: "complete", matched_lines: 1, unmatched_lines: 0, reason: "complete", rows: [] }));

  render(<ExpenseControl org="1" />);
  await screen.findByText("Книга № 1. Учётная запись: chief. Версия справочника: 1.");
  fireEvent.change(screen.getByLabelText("Год бюджета"), { target: { value: "2026" } });
  fireEvent.change(screen.getByLabelText("Валюта бюджета"), { target: { value: "BYN" } });
  fireEvent.change(screen.getByLabelText("Основа"), { target: { value: "accrual" } });
  fireEvent.change(screen.getByLabelText("Месяц факта"), { target: { value: "1" } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить бюджет" }));

  expect(await screen.findByLabelText("Фактические оплаты расходов")).toHaveTextContent("cash ledger unavailable");
  expect(screen.getByLabelText("Начислено")).toHaveTextContent("140.00 BYN");
  expect(screen.getByLabelText("Оплачено")).toHaveTextContent("— Неизвестно");
  expect(screen.getByLabelText("Непогашенные обязательства")).toHaveTextContent("— Неизвестно");
  expect(screen.getByLabelText("Непогашенные обязательства")).toHaveTextContent("разность начислений и оплат не используется");
});

it("opens a listed unmatched entry without replacing the fact on list failure", async () => {
  const onEntry = vi.fn();
  api.context.mockResolvedValue(context); api.journal.mockResolvedValue({ raw: null, attempt: null });
  api.getBudgets.mockResolvedValue({ organization_id: 1, principal: "chief", year: 2026, currency: "BYN", basis: "accrual", versions: [], approved_plan: null, actuals: { accrued: { amount: null, coverage: "unknown", reason: "x" }, paid: { amount: null, coverage: "unknown", reason: "x" }, commitments: { amount: null, coverage: "unknown", reason: "x" } }, approval_enabled: true, approval_blocker: null });
  api.getActuals.mockImplementation((_s, year, month, basis) => Promise.resolve({ year, month, currency: "BYN", basis, amount: "10.00", coverage: "partial", matched_lines: 1, unmatched_lines: 1, reason: "partial", rows: [] }));
  api.getUnmatchedActuals.mockResolvedValue({ year: 2026, month: 1, currency: "BYN", basis: "accrual", total: 1, next_after_line_id: null, items: [{ entry_id: 7, line_id: 8, posting_date: "2026-01-02", source: "source", operation: "manual", account_code: "90.4", side: "debit", amount: "2.00", dimensions: {}, reason: "нет статьи" }] });
  render(<ExpenseControl org="1" onEntry={onEntry} />);
  await screen.findByText("Книга № 1. Учётная запись: chief. Версия справочника: 1.");
  fireEvent.change(screen.getByLabelText("Год бюджета"), { target: { value: "2026" } }); fireEvent.change(screen.getByLabelText("Валюта бюджета"), { target: { value: "BYN" } }); fireEvent.change(screen.getByLabelText("Основа"), { target: { value: "accrual" } }); fireEvent.change(screen.getByLabelText("Месяц факта"), { target: { value: "1" } }); fireEvent.click(screen.getByRole("button", { name: "Загрузить бюджет" }));
  const accrualPanel = await screen.findByLabelText("Фактические начисления расходов");
  fireEvent.click(within(accrualPanel).getByRole("button", { name: "Показать неразнесённые строки" }));
  fireEvent.click(await screen.findByRole("button", { name: "Открыть проводку" }));
  expect(onEntry).toHaveBeenCalledWith(7);
});

it.each(["month", "basis", "scope"] as const)("drops an unmatched response from the previous %s", async dimension => {
  setupActualMocks();
  const old = deferred<ReturnType<typeof unmatched>>();
  let listCalls = 0;
  api.getUnmatchedActuals.mockImplementation((scope: { org: number }, _year: number, month: number, basis: "cash" | "accrual") => {
    listCalls += 1;
    return listCalls === 1 ? old.promise : Promise.resolve(unmatched(scope.org, month, basis, "new-row"));
  });
  const view = render(<ExpenseControl org="1" />);
  await loadFacts();
  const panel = () => screen.getByLabelText("Фактические начисления расходов");
  fireEvent.click(within(panel()).getByRole("button", { name: "Показать неразнесённые строки" }));

  if (dimension === "scope") {
    view.rerender(<ExpenseControl org="2" />);
    await loadFacts();
  } else {
    if (dimension === "month") fireEvent.change(screen.getByLabelText("Месяц факта"), { target: { value: "2" } });
    if (dimension === "basis") fireEvent.change(screen.getByLabelText("Основа"), { target: { value: "cash" } });
    fireEvent.click(screen.getByRole("button", { name: "Загрузить бюджет" }));
    await screen.findAllByRole("button", { name: "Показать неразнесённые строки" });
  }
  fireEvent.click(within(panel()).getByRole("button", { name: "Показать неразнесённые строки" }));
  expect(await screen.findByText(/new-row/)).toBeInTheDocument();

  await act(async () => { old.resolve(unmatched(1, 1, "accrual", "old-row")); await old.promise; });
  expect(screen.queryByText(/old-row/)).not.toBeInTheDocument();
});

it("does not start a duplicate B while stale A is finishing", async () => {
  setupActualMocks();
  const first = deferred<ReturnType<typeof unmatched>>();
  const second = deferred<ReturnType<typeof unmatched>>();
  const actualMonths: number[] = [];
  api.getActuals.mockImplementation((_scope: unknown, year: number, month: number, basis: "cash" | "accrual") => {
    actualMonths.push(month);
    return Promise.resolve(actual(year, month, basis));
  });
  let monthTwoCalls = 0;
  api.getUnmatchedActuals.mockImplementation((scope: { org: number }, _year: number, month: number, basis: "cash" | "accrual") => {
    if (month === 1) return first.promise;
    monthTwoCalls += 1;
    return monthTwoCalls === 1 ? second.promise : Promise.resolve(unmatched(scope.org, month, basis, "duplicate"));
  });
  render(<ExpenseControl org="1" />);
  await loadFacts();
  const panel = screen.getByLabelText("Фактические начисления расходов");
  fireEvent.click(within(panel).getByRole("button", { name: "Показать неразнесённые строки" }));
  fireEvent.change(screen.getByLabelText("Месяц факта"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить бюджет" }));
  await waitFor(() => expect(actualMonths.slice(-2)).toEqual([2, 2]));
  await waitFor(() => {
    const currentPanel = screen.getByLabelText("Фактические начисления расходов");
    expect(within(currentPanel).getByRole("button", { name: "Показать неразнесённые строки" })).toBeInTheDocument();
  });
  const monthTwoPanel = screen.getByLabelText("Фактические начисления расходов");
  fireEvent.click(within(monthTwoPanel).getByRole("button", { name: "Показать неразнесённые строки" }));
  await waitFor(() => expect(api.getUnmatchedActuals).toHaveBeenCalledTimes(2));

  await act(async () => { first.resolve(unmatched(1, 1, "accrual", "old-A")); await first.promise; });
  fireEvent.click(within(monthTwoPanel).getByRole("button", { name: "Показать неразнесённые строки" }));
  const callsWhileBIsPending = api.getUnmatchedActuals.mock.calls.length;
  await act(async () => { second.resolve(unmatched(1, 2, "accrual", "new-B")); await second.promise; });
  expect(callsWhileBIsPending).toBe(2);
});

it("keeps the fact visible when the unmatched register request fails", async () => {
  setupActualMocks();
  api.getUnmatchedActuals.mockRejectedValue(new Error("registry unavailable"));
  render(<ExpenseControl org="1" />);
  await loadFacts();
  const panel = screen.getByLabelText("Фактические начисления расходов");
  fireEvent.click(within(panel).getByRole("button", { name: "Показать неразнесённые строки" }));
  expect(await within(panel).findByRole("alert")).toHaveTextContent("registry unavailable");
  expect(screen.getByLabelText("Начислено")).toHaveTextContent("10.00 BYN");
  expect(panel).toHaveTextContent("без статьи: 1");
});

it("previews and confirms an append-only attribution from an unmatched accrual line", async () => {
  setupActualMocks();
  api.getUnmatchedActuals.mockResolvedValueOnce(unmatched(1, 1, "accrual", "source")).mockResolvedValueOnce({
    year: 2026, month: 1, currency: "BYN", basis: "accrual", items: [], next_after_line_id: null,
  });
  api.previewAttribution.mockResolvedValue(attributionPreview());
  api.begin.mockImplementation((scope: unknown, kind: string, body: unknown) => Promise.resolve({
    raw: "pending-attribution", attempt: { scope, kind, body: JSON.stringify(body), hash: "x", nonce: "n", outcome: "pending" },
  }));
  api.dispatch.mockImplementation((saved: { attempt: { scope: { org: number; principal: string }; body: string } }) => {
    const command = JSON.parse(saved.attempt.body);
    const result = { ...attributionPreview(command.source_line_id), evidence: command.evidence, explanation: command.explanation };
    return Promise.resolve({ receipt: { organization_id: saved.attempt.scope.org, principal: saved.attempt.scope.principal,
      kind: "expense_article_attribution", request_key: command.request_key, command, command_hash: "c".repeat(64), result,
      result_digest: "d".repeat(64), receipt_digest: "e".repeat(64) }, journal: { raw: "done-attribution", attempt: null } });
  });

  render(<ExpenseControl org="1" />);
  await loadFacts();
  const panel = screen.getByLabelText("Фактические начисления расходов");
  fireEvent.click(within(panel).getByRole("button", { name: "Показать неразнесённые строки" }));
  fireEvent.click(await within(panel).findByRole("button", { name: "Разнести" }));
  fireEvent.change(screen.getByLabelText("Статья разнесения"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Основание разнесения"), { target: { value: "Проверен первичный документ" } });
  fireEvent.change(screen.getByLabelText("Пояснение разнесения"), { target: { value: "Отнесено на материалы" } });
  fireEvent.click(screen.getByRole("button", { name: "Проверить разнесение" }));

  expect(await screen.findByLabelText("Предварительный просмотр разнесения")).toHaveTextContent("проводка 1001, строка 1001");
  expect(api.previewAttribution).toHaveBeenCalledWith({ org: 1, principal: "chief" }, {
    source_line_id: 1001, article_id: 1, effective_date: "2026-01-02",
  });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить разнесение" }));

  await waitFor(() => expect(api.begin).toHaveBeenCalledWith({ org: 1, principal: "chief" }, "attribution", expect.objectContaining({
    source_line_id: 1001, article_id: 1, effective_date: "2026-01-02", expected_basis_digest: "a".repeat(64),
    evidence: "Проверен первичный документ", explanation: "Отнесено на материалы",
  }), null));
  expect(await screen.findByText(/Атрибуция сохранена\. Квитанция/)).toBeInTheDocument();
  expect(within(panel).queryByRole("button", { name: "Разнести" })).not.toBeInTheDocument();
});

it("keeps manual attribution controls hidden from a reader", async () => {
  setupActualMocks();
  api.context.mockResolvedValue({ ...context, role: "reader" });
  api.getUnmatchedActuals.mockResolvedValue(unmatched(1, 1, "accrual", "source"));

  render(<ExpenseControl org="1" />);
  await loadFacts();
  const panel = screen.getByLabelText("Фактические начисления расходов");
  fireEvent.click(within(panel).getByRole("button", { name: "Показать неразнесённые строки" }));
  await within(panel).findByText(/source/);

  expect(within(panel).queryByRole("button", { name: "Разнести" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Статья разнесения")).not.toBeInTheDocument();
});
