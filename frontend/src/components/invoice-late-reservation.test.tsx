import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { InvoiceLateReservation } from "./invoice-late-reservation";
import type { DealDoc } from "@/lib/api";
vi.mock("@/lib/document-register-api", () => ({ fetchRegisterOrganizations: async () => [{ id: 7, name: "Компания", unp: "123" }] }));
const doc: DealDoc = { id: 3, kind: "invoice", number: "1", amount: 200, status: "issued", version: 1, content_sha256: "a".repeat(64), reserve_mode: "on_order", reserve_status: "unreserved", valid_until: "2026-09-15", onec_ref: null };
beforeEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); });
it("reserves from original lines and restores the same request after remount", async () => {
  const reserved = { ...doc, reserve_status: "reserved" };
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(Response.json({ organization_id: 7, deal_id: 1, document_id: 3, document_version: 1, content_sha256: doc.content_sha256,
    lines: [{ line_no: 1, name: "Товар", sku_code: "SKU", unit: "шт", qty: "2.00" }],
    availability: { organization_id: 7, source: "wms_physical", rows: [{ sku_code: "SKU", warehouse: "W", physical: "2.00", reserved: "0.00", free: "2.00" }] } }))
    .mockRejectedValueOnce(new Error("lost"))
    .mockResolvedValueOnce(Response.json({ document: reserved, reservation_digest: "b".repeat(64), replayed: true }))
    .mockResolvedValueOnce(Response.json([reserved]));
  const refresh = vi.fn(async () => {});
  const view = render(<InvoiceLateReservation dealId="1" doc={doc} refresh={refresh} />);
  await screen.findByRole("option", { name: "Компания · 123" });
  fireEvent.change(screen.getByLabelText("Юрлицо"), { target: { value: "7" } });
  fireEvent.click(screen.getByText("Проверить доступность"));
  await screen.findByText("1. Товар · SKU · 2.00 шт");
  fireEvent.change(screen.getByLabelText("Склад распределения 1"), { target: { value: "W" } });
  fireEvent.change(screen.getByLabelText("Основание проверки склада"), { target: { value: "Поступление проверено" } });
  fireEvent.click(screen.getByLabelText("Подтверждаю полноту журнала склада"));
  fireEvent.click(screen.getByText("Подтвердить резерв"));
  await screen.findByRole("alert");
  view.unmount();
  render(<InvoiceLateReservation dealId="1" doc={reserved} refresh={refresh} />);
  const retry = await screen.findByText("Повторить исходный запрос резерва");
  await waitFor(() => expect(retry).not.toBeDisabled());
  fireEvent.click(retry);
  await screen.findByRole("status");
  expect(fetcher.mock.calls[1][1]?.body).toBe(fetcher.mock.calls[2][1]?.body);
  expect(refresh).toHaveBeenCalledOnce();
});
