import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  context: vi.fn(), getBudgets: vi.fn(), getActuals: vi.fn(), journal: vi.fn(),
}));

vi.mock("@/lib/expense-control-api", () => ({
  ...api,
  ExpenseError: class ExpenseError extends Error { status?: number; },
}));

import { ExpenseControl } from "./expense-control";

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
  fireEvent.click(screen.getByRole("button", { name: "Загрузить бюджет" }));

  expect(await screen.findByLabelText("План-факт расходов")).toBeInTheDocument();
  expect(screen.getByText("25.00 BYN")).toBeInTheDocument();
  expect(screen.getByText("25.00%")).toBeInTheDocument();
  expect(screen.getAllByRole("alert")[0]).toHaveTextContent("покрытие факта partial");
  expect(screen.getByText(/1 статья имеет факт без плана/)).toBeInTheDocument();
});
