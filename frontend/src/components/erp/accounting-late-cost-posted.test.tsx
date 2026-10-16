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

it("reads the complete material package including linked output costs", async () => {
  const original = packet();
  original.posting.lines[0].account = "20";
  const data = { ...original, preview: { posting: original.posting, wip_origins: [],
    command: { command_version: 2, material_outputs: [{ output_entry_id: 12, amount_byn: "100.00" }] },
    outputs: [{ output_entry_id: 12, amount_byn: "100.00", prospective_evidence: { matrix: [
      { account: "43", side: "debit", amount: "50.00", dimensions: {} },
      { account: "90.4", side: "debit", amount: "50.00", dimensions: {} },
      { account: "20", side: "credit", amount: "100.00", dimensions: {} }] } }] },
    output_revisions: [{ output_entry_id: 12, output_revision_id: 19, amount_byn: "100.00" }] };
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => data });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingLateCostPosted org="1" expenseId={7} version={2} entryId={9} mode="material" />);
  fireEvent.click(screen.getByText("Показать проводки"));
  await screen.findByText("Дебет 90.4 · 50.00 BYN");
  expect(screen.getByText("Дебет 43 · 50.00 BYN")).toBeInTheDocument();
  expect(fetcher.mock.calls[0][0]).toContain("/material/posting");
});

it("reads the immutable V3 pool package with signed output and inventory-value evidence", async () => {
  const original = packet();
  const poolPosting = { ...original.posting, lines: [
    { account: "41", side: "debit", amount: "102.00", currency: "BYN", quantity: null, dimensions: {} },
    { account: "20", side: "credit", amount: "2.00", currency: "BYN", quantity: null, dimensions: {} },
    { account: "60", side: "credit", amount: "100.00", currency: "BYN", quantity: null, dimensions: {} },
  ] };
  const data = { ...original, preview: { posting: poolPosting, wip_origins: [], calculation: { destinations: [] },
    command: { command_version: 3, material_outputs: [{ output_entry_id: 12, amount_byn: "-2.00" }] },
    outputs: [{ output_entry_id: 12, amount_byn: "-2.00", prospective_evidence: { matrix: [
      { account: "43", side: "credit", amount: "1.00", dimensions: {} },
      { account: "90.4", side: "credit", amount: "1.00", dimensions: {} },
      { account: "20", side: "debit", amount: "2.00", dimensions: {} }] } }] },
    command: { command_version: 3, material_outputs: [{ output_entry_id: 12, amount_byn: "-2.00" }] },
    output_revisions: [{ output_entry_id: 12, output_revision_id: 19, amount_byn: "-2.00" }], inventory_value_links: [] };
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => data });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingLateCostPosted org="1" expenseId={7} version={2} entryId={9} mode="pool" />);
  fireEvent.click(screen.getByText("Показать проводки"));
  await screen.findByText("Кредит 90.4 · 1.00 BYN");
  expect(screen.getByText("Дебет 20 · 2.00 BYN")).toBeInTheDocument();
  expect(fetcher.mock.calls[0][0]).toContain("/pool/posting");
});
