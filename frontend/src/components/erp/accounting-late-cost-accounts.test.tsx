import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingLateCostAccounts } from "./accounting-late-cost-accounts";
afterEach(() => vi.unstubAllGlobals());
const allocation = { expected_version: 1, policy_id: 2, posting_date: "2026-09-12", capitalizable_amount_byn: "100.00", excluded_amount_byn: "20.00", classification_evidence: "Reviewed transport" };
function setup() {
  const fetcher = vi.fn().mockImplementation((_url, options) => Promise.resolve({ ok: true, json: async () => options?.method === "POST"
    ? { organization_id: 1, expense_id: 7, posted: false, principal: "accountant", digest: "a".repeat(64), basis_digest: "b".repeat(64), posting: { source: "procurement:additional-expense:7", source_version: 1,
      lines: [{ account: "41", side: "debit", amount: "100.00", dimensions: {} }, { account: "18", side: "debit", amount: "20.00", dimensions: { counterparty: "carrier" } }, { account: "60", side: "credit", amount: "120.00", dimensions: {} }] } }
    : [{ code: "60", title: "Поставщики", valid_from: "2026-01-01", category: "liability", cash: false, quantity_tracking: false, required_dimensions: [] },
      { code: "18", title: "НДС", valid_from: "2026-01-01", category: "asset", cash: false, quantity_tracking: false, required_dimensions: ["counterparty"] }] }));
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingLateCostAccounts org="1" expenseId={7} allocation={allocation} disabled={false} />);
  return fetcher;
}
it("uses explicit working accounts and required analytics without posting", async () => {
  const fetcher = setup(); await screen.findByText("60 · Поставщики");
  fireEvent.change(screen.getByLabelText("Счёт расчётов с поставщиком"), { target: { value: "60" } });
  fireEvent.click(screen.getByText("Добавить исключённую сумму"));
  fireEvent.change(screen.getByLabelText("Счёт исключённой суммы 1"), { target: { value: "18" } });
  fireEvent.change(screen.getByLabelText("Сумма части 1, BYN"), { target: { value: "20.00" } });
  fireEvent.change(screen.getByLabelText("Контрагент"), { target: { value: "carrier" } });
  fireEvent.click(screen.getByText("Подготовить проводки"));
  await screen.findByText("Кредит 60 · 120.00 BYN");
  const [url, options] = fetcher.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(url).toContain("/posting-preview");
  expect(JSON.parse(options.body).accounts.excluded_costs).toEqual([{ account: "18", amount_byn: "20.00", dimensions: { counterparty: "carrier" } }]);
  fireEvent.change(screen.getByLabelText("Сумма части 1, BYN"), { target: { value: "19.00" } });
  await waitFor(() => expect(screen.queryByText("Кредит 60 · 120.00 BYN")).not.toBeInTheDocument());
  expect(fetcher.mock.calls.some(([path]) => path.endsWith("/confirm"))).toBe(false);
});
