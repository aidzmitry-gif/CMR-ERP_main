import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingLateCostPosted } from "./accounting-late-cost-posted";

const packet = () => ({ organization_id: 1, expense_id: 7, source_version: 2, entry_id: 9, posted: true,
  digest: "a".repeat(64), basis_digest: "b".repeat(64), posting: { source: "procurement:additional-expense:7",
    posting_date: "2026-09-12", explanation: "Доставка товара", lines: [
      { account: "41", side: "debit", amount: "100.00", currency: "BYN", quantity: null, dimensions: { lot: "Партия 1" } },
      { account: "60", side: "credit", amount: "100.00", currency: "BYN", quantity: null, dimensions: { counterparty: "Перевозчик" } }] } });
afterEach(() => vi.unstubAllGlobals());
function setup(data = packet()) {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => data });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingLateCostPosted org="1" expenseId={7} version={2} entryId={9} />);
  return fetcher;
}
it("reads only on request and shows verified accounts and analytics", async () => {
  const fetcher = setup(); expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Показать проводки"));
  await screen.findByText("Дебет 41 · 100.00 BYN");
  expect(screen.getByText("Контрагент: Перевозчик")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith("/api/accounting/organizations/1/additional-expenses/7/posting", expect.objectContaining({ cache: "no-store" }));
  expect(fetcher.mock.calls[0][1].method).toBeUndefined();
});
it("rejects another organization before showing accounting values", async () => {
  setup({ ...packet(), organization_id: 2 }); fireEvent.click(screen.getByText("Показать проводки"));
  await screen.findByRole("alert"); expect(screen.queryByText("Дебет 41 · 100.00 BYN")).not.toBeInTheDocument();
});
it("rejects an unbalanced package instead of masking the difference", async () => {
  const data = packet(); data.posting.lines[0].amount = "99.99";
  setup(data); fireEvent.click(screen.getByText("Показать проводки"));
  await screen.findByText("Дебет и кредит пакета не сходятся.");
});
