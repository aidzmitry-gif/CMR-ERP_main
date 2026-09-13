import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingReceiptPreview } from "./accounting-receipt-preview";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const source = { id: 9, version: 2, document: { operation_date: "2026-09-02", items: [{ sku: "Товар", vat_amount: "0.00" }] } };
const accounts = [{ code: "60", title: "Поставщик", category: "liability", cash: false }, { code: "41", title: "Товары", category: "asset", cash: false }];
it("blocks calculation when no policy applies to the selected date", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.includes("accounts?") ? accounts : [{ id: 3, effective_from: "2027-01-01", reference: "Будущая политика" }] })));
  render(<AccountingReceiptPreview org="7" source={source} />);
  await screen.findByRole("option", { name: "60 · Поставщик" });
  fireEvent.change(screen.getByLabelText("Счёт расчётов с поставщиком"), { target: { value: "60" } });
  fireEvent.change(screen.getByLabelText(/Счёт запасов/), { target: { value: "41" } });
  expect(screen.getByText(/учётная политика не получена/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Рассчитать проводки поступления" })).toBeDisabled();
});
function fixture() {
  const fetcher = vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.includes("accounts?") ? accounts : url.endsWith("policies") ? [{ id: 3, effective_from: "2026-01-01", reference: "Политика 2026" }] : { digest: "a".repeat(64), organization_id: 7, source: "procurement:receipt:9", source_version: 2, posted: false, lines: [{ account: "41", title: "Товары", side: "debit", amount: "100.01", quantity: "2.000001", dimensions: { warehouse: "Склад" } }] } }));
  vi.stubGlobal("fetch", fetcher); return fetcher;
}
it("requires explicit accounts, sends exact source version and invalidates on edit", async () => {
  const fetcher = fixture();
  render(<AccountingReceiptPreview org="7" source={source} />);
  await screen.findByText("Учётная политика: Политика 2026");
  const button = screen.getByRole("button", { name: "Рассчитать проводки поступления" });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Счёт расчётов с поставщиком"), { target: { value: "60" } });
  fireEvent.change(screen.getByLabelText(/Счёт запасов/), { target: { value: "41" } });
  fireEvent.click(button);
  expect(await screen.findByText(/100.01 BYN · количество 2.000001/)).toBeInTheDocument();
  const call = fetcher.mock.calls.find(([url]) => url.endsWith("/preview"))!;
  expect(JSON.parse(call[1].body)).toEqual({ expected_version: 2, posting_date: "2026-09-02", policy_id: 3, settlement_account: "60", vat_account: null, inventory_accounts: ["41"] });
  fireEvent.change(screen.getByLabelText("Счёт расчётов с поставщиком"), { target: { value: "" } });
  expect(screen.queryByText(/100.01 BYN/)).not.toBeInTheDocument();
});
it("requires input VAT account when the source contains VAT", async () => {
  fixture();
  render(<AccountingReceiptPreview org="7" source={{ ...source, document: { ...source.document, items: [{ sku: "Товар", vat_amount: "20.00" }] } }} />);
  await screen.findByText("Учётная политика: Политика 2026");
  fireEvent.change(screen.getByLabelText("Счёт расчётов с поставщиком"), { target: { value: "60" } });
  fireEvent.change(screen.getByLabelText(/Счёт запасов/), { target: { value: "41" } });
  expect(screen.getByLabelText("Счёт входного НДС")).toHaveValue("");
  expect(screen.getByRole("button", { name: "Рассчитать проводки поступления" })).toBeDisabled();
});
