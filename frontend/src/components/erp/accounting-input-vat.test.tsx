import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingInputVat } from "./accounting-input-vat";

afterEach(() => vi.unstubAllGlobals());
const props = { org: "1", start: "2026-09-01", end: "2026-09-30", onEntry: vi.fn() };
const data = {
  totals: { debit: "20.01", credit: "5.00", opening_debit: "7.00", opening_credit: "2.00" },
  rows_needing_metadata_review: 1,
  rows: [{ entry_id: 42, line_id: 8, source: "invoice:7", source_version: 2, posting_date: "2026-09-10", opening: false, correction_of: 41, account_code: "18.1", account_title: "VAT", side: "debit", amount: "20.01", dimensions: {}, review_issues: ["missing_vat_basis"] }],
};
const ok = (body: unknown) => ({ ok: true, json: async () => body });

it("shows exact totals, review limits and links to the posted entry", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ok(data)));
  const onEntry = vi.fn();
  render(<AccountingInputVat {...props} onEntry={onEntry} />);
  fireEvent.click(await screen.findByRole("button", { name: "Операция № 42 · invoice:7" }));
  expect(onEntry).toHaveBeenCalledWith(42);
  expect(screen.getByText("7.00 BYN")).toBeInTheDocument();
  expect(screen.getByText("2.00 BYN")).toBeInTheDocument();
  expect(screen.getByText(/право на вычет, ЭСЧФ/)).toBeInTheDocument();
  expect(screen.getByText("Корректировка операции № 41")).toBeInTheDocument();
  expect(screen.getByText(/Проверьте ставку и основание/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Открыть первичную накладную" })).not.toBeInTheDocument();
});

it("links procurement purchases to their posted revision and shows settlement snapshots", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ok({ ...data, rows: [{ ...data.rows[0], operation: "inventory_purchase", source: "procurement:receipt:17", dimensions: { counterparty: "Supplier snapshot", contract: "Contract snapshot", settlement_document: "Invoice snapshot" } }] })));
  render(<AccountingInputVat {...props} />);
  expect(await screen.findByRole("link", { name: "Открыть первичную накладную" })).toHaveAttribute("href", "/erp/procurement/receipts/posted/42?org=1");
  expect(screen.getByText(/Supplier snapshot · Договор: Contract snapshot · Документ расчётов: Invoice snapshot/)).toBeInTheDocument();
});

it("rejects late responses from the previous company and allows retry", async () => {
  let resolveFirst!: (value: unknown) => void;
  let fail = true;
  vi.stubGlobal("fetch", vi.fn((url: string) => url.includes("/1/")
    ? new Promise((resolve) => { resolveFirst = resolve; })
    : Promise.resolve(fail ? { ok: false } : ok({ ...data, rows: [] }))));
  const view = render(<AccountingInputVat {...props} />);
  view.rerender(<AccountingInputVat {...props} org="2" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить");
  await act(async () => resolveFirst(ok(data)));
  expect(screen.queryByText(/invoice:7/)).not.toBeInTheDocument();
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "Обновить ведомость" }));
  expect(await screen.findByText(/Проводок по счёту 18 за выбранный период нет/)).toBeInTheDocument();
});

it("requires a company and a valid period before loading", () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const view = render(<AccountingInputVat {...props} org="" />);
  expect(screen.getByText("Выберите юрлицо.")).toBeInTheDocument();
  view.rerender(<AccountingInputVat {...props} end="2026-08-31" />);
  expect(screen.getByRole("alert")).toHaveTextContent("корректный период");
  expect(fetcher).not.toHaveBeenCalled();
});
