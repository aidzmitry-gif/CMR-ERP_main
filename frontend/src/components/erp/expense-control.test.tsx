import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  context: vi.fn(), getBudgets: vi.fn(), getActuals: vi.fn(), journal: vi.fn(),
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
