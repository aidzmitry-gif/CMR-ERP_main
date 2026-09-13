import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingSourceLink } from "./accounting-source-link";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const receipt = { id: 9, organization_id: 7, source: "procurement:receipt:9", version: 2, status: "posted", actor: "Бухгалтер", created_at: "2026-09-10", document: { invoice_reference: "ТН-27", currency: "BYN", document_date: "2026-09-01", operation_date: "2026-09-02", supplier: "Поставщик", contract: "Договор-1", warehouse: "Склад-1", explanation: "Поступление товаров", items: [{ sku: "Товар-1", lot: "Партия-1", quantity: "2.000001", net_amount: "100.01", vat_rate: "20", vat_amount: "20.00", vat_basis: "Первичный документ" }] } };

it.each([undefined, null, "кг"])("reads exact receipt amounts and unit %s through accounting only, on demand", async unit => {
  const source = { ...receipt, document: { ...receipt.document, items: receipt.document.items.map(item => ({ ...item, unit })) } };
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => source });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingSourceLink org="7" source="procurement:receipt:9" />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Открыть поступление" }));
  expect(await screen.findByText(/ТН-27 · Версия 2/)).toBeInTheDocument();
  expect(screen.getByText("2.000001")).toBeInTheDocument();
  expect(screen.getByText("100.01")).toBeInTheDocument();
  expect(screen.getByText(unit ?? "Не указана")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith("/api/accounting/organizations/7/receipts/9/source", expect.objectContaining({ cache: "no-store" }));
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

it("rejects a response for a different organization and allows retry", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ ...receipt, organization_id: 8 }) }).mockResolvedValueOnce({ ok: true, json: async () => receipt });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingSourceLink org="7" source="procurement:receipt:9" />);
  fireEvent.click(screen.getByRole("button", { name: "Открыть поступление" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("другой операции");
  expect(screen.queryByText("100.01")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку" }));
  expect(await screen.findByText("100.01")).toBeInTheDocument();
});

it("discards a late source response when organization changes", async () => {
  let finish!: (value: unknown) => void;
  const fetcher = vi.fn().mockReturnValue(new Promise(resolve => { finish = resolve; }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<AccountingSourceLink org="7" source="procurement:receipt:9" />);
  fireEvent.click(screen.getByRole("button", { name: "Открыть поступление" }));
  view.rerender(<AccountingSourceLink org="8" source="procurement:receipt:9" />);
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  finish({ ok: true, json: async () => receipt });
  await waitFor(() => expect(screen.queryByText("100.01")).not.toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Открыть поступление" })).toBeInTheDocument();
});
