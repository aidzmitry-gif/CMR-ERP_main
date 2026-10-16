import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingReceiptWarehouse } from "./accounting-receipt-warehouse";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const report = { organization_id: 1, receipt_id: 9, source_version: 2, status: "linked", rows: [{ position: 1, sku: "Material", lot: "Lot", unit: "кг", quantity: "2.00", prepared: "1.25", accepted: "1.00", rejected: "0.25", pending_qc: "0.00", unallocated: "0.75" }], receipts: [{ receipt_id: 3, number: "ПРМ-3", source_version: 2, warehouse: "Склад", status: "accepted" }] };
it("reads on demand and separates accepted, rejected and unallocated quantities", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => report });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingReceiptWarehouse org="1" receiptId={9} version={2} />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Сверить со складом" }));
  expect(await screen.findByText("0.75")).toBeInTheDocument();
  expect(screen.getByText("0.25")).toBeInTheDocument();
  expect(screen.getByText("1.00")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith("/api/accounting/organizations/1/receipts/9/warehouse-reconciliation", expect.objectContaining({ cache: "no-store" }));
});
it.each(["version_conflict", "foreign"])("does not show a misleading aggregate for %s", async kind => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => kind === "foreign" ? { ...report, organization_id: 2 } : { ...report, status: kind } }));
  render(<AccountingReceiptWarehouse org="1" receiptId={9} version={2} />);
  fireEvent.click(screen.getByRole("button", { name: "Сверить со складом" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
