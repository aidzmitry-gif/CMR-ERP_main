import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingProductionCostSources } from "./accounting-production-cost-sources";
afterEach(() => vi.unstubAllGlobals());
const policy = { id: 2, organization_id: 1, effective_from: "2026-10-01", reference: "Test policy", production_costing: {} };
const data = { digest: "a".repeat(64), snapshot: { organization_id: 1, month: "2026-10", policy_id: 2,
  scope: "posted_production_cost_accounts", status: "source_review", final_cost_certified: false,
  balances: [{ account: "20", role: "wip", dimensions: { order: "7", department: "SHOP" }, opening_byn: "10.00", debit_byn: "100.01", credit_byn: "30.00", closing_byn: "80.01" }],
  lines: [{ entry_id: 9, line_id: 11, source: "materials", account: "20", dimensions: { department: "SHOP", order: "7" }, posting_date: "2026-10-02", side: "debit", amount_byn: "100.01", opening: false },
    { entry_id: 10, line_id: 12, source: "other-order", account: "20", dimensions: { department: "SHOP", order: "8" }, posting_date: "2026-10-02", side: "debit", amount_byn: "1.00", opening: false }] } };
async function show() {
  fireEvent.click(screen.getByText("Обновить политики производства"));
  fireEvent.change(await screen.findByLabelText("Политика затрат производства"), { target: { value: "2" } });
  fireEvent.click(screen.getByText("Показать источники затрат"));
}
it("shows exact balances, drills into only matching analytics and clears stale result on error", async () => {
  let fail = false;
  const request = vi.fn(async (url: RequestInfo | URL) => String(url).endsWith("/policies") ? Response.json([policy])
    : fail ? new Response("{}", { status: 503 }) : Response.json(data));
  vi.stubGlobal("fetch", request);
  const onEntry = vi.fn();
  render(<AccountingProductionCostSources org="1" month="2026-10" disabled={false} onEntry={onEntry} />);
  expect(request).not.toHaveBeenCalled();
  await show();
  expect(await screen.findByText(/остаток: 80.01/)).toBeVisible();
  fireEvent.click(screen.getByText("Счёт 20 · НЗП"));
  fireEvent.click(screen.getByText("Проводка №9"));
  expect(onEntry).toHaveBeenCalledWith(9);
  expect(screen.queryByText("Проводка №10")).toBeNull();
  fail = true;
  fireEvent.click(screen.getByText("Показать источники затрат"));
  await screen.findByRole("alert");
  expect(screen.queryByText(/остаток: 80.01/)).toBeNull();
});
it("removes source data when the organization/month changes", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => Response.json(String(url).endsWith("/policies") ? [policy] : data)));
  const view = render(<AccountingProductionCostSources org="1" month="2026-10" disabled={false} />);
  await show(); await screen.findByText(/остаток: 80.01/);
  view.rerender(<AccountingProductionCostSources org="2" month="2026-11" disabled={false} />);
  await waitFor(() => expect(screen.queryByText(/остаток: 80.01/)).toBeNull());
  expect(screen.queryByLabelText("Политика затрат производства")).toBeNull();
});
